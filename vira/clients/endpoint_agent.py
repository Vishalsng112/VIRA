"""Reference VIRA endpoint client (design Phase 4, section 8.2).

Runs on any OS where Python and psutil are available and speaks only the public
``/api/v1`` contract, so Android/iOS/desktop clients can follow the same flow:

1. ``enroll``  - sign in as a user, register this device, store the credential
                 (shown once by the server) in a 0600 file.
2. ``run``     - heartbeat, collect permitted sensors, queue events durably on
                 disk, send bounded batches with retries and backoff.

    python -m vira.clients.endpoint_agent enroll --server http://host:8000 \\
        --username alice --name "Alice laptop"
    python -m vira.clients.endpoint_agent run

The client never chooses its device id, owner or scopes; it only presents the
credential the server issued.  Event ids are UUIDs so retries are idempotent.
"""
import argparse
import asyncio
import getpass
import json
import os
import platform
import random
import sqlite3
import stat
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp

CLIENT_VERSION = "0.3.0"
DEFAULT_HOME = Path(os.environ.get("VIRA_CLIENT_HOME", Path.home() / ".config" / "vira-endpoint"))
_PLATFORMS = {"linux": "linux", "darwin": "macos", "windows": "windows"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ----------------------------------------------------------------------- #
# credential + queue storage
# ----------------------------------------------------------------------- #
class CredentialStore:
    """0600 JSON file.  On mobile platforms use Keystore/Keychain instead."""

    def __init__(self, home: Path = DEFAULT_HOME):
        self.home = home
        self.path = home / "device.json"

    def save(self, server: str, device_id: str, token: str) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w") as fh:
            json.dump({"server": server, "device_id": device_id, "token": token}, fh)

    def load(self) -> Dict[str, str]:
        with open(self.path) as fh:
            return json.load(fh)


class EventQueue:
    """Durable offline queue with a monotonically increasing device sequence."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path))
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS queue (seq INTEGER PRIMARY KEY, body TEXT NOT NULL)")
        self._db.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v INTEGER)")
        self._db.commit()

    def _next_sequence(self) -> int:
        row = self._db.execute("SELECT v FROM meta WHERE k = 'seq'").fetchone()
        nxt = (row[0] if row else 0) + 1
        self._db.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('seq', ?)", (nxt,))
        return nxt

    def push(self, event_type: str, component: str, payload: Dict[str, Any],
             max_backlog: int = 5000) -> None:
        seq = self._next_sequence()
        event = {
            "event_id": str(uuid.uuid4()), "type": event_type, "schema_version": 1,
            "occurred_at": _now(), "source_component": component,
            "device_sequence": seq, "payload": payload,
        }
        self._db.execute("INSERT INTO queue (seq, body) VALUES (?, ?)", (seq, json.dumps(event)))
        # Bounded: drop the oldest when the server is unreachable for a long time.
        self._db.execute("DELETE FROM queue WHERE seq <= (SELECT MAX(seq) FROM queue) - ?", (max_backlog,))
        self._db.commit()

    def peek(self, limit: int) -> List[Dict[str, Any]]:
        rows = self._db.execute("SELECT seq, body FROM queue ORDER BY seq LIMIT ?", (limit,)).fetchall()
        return [{"_seq": r[0], **json.loads(r[1])} for r in rows]

    def ack(self, seqs: List[int]) -> None:
        self._db.executemany("DELETE FROM queue WHERE seq = ?", [(s,) for s in seqs])
        self._db.commit()

    def depth(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM queue").fetchone()[0]


# ----------------------------------------------------------------------- #
# sensors: only what the platform permits; failures become capability status
# ----------------------------------------------------------------------- #
def collect_hardware() -> Dict[str, Any]:
    import psutil  # imported lazily so enrolment works without it
    data: Dict[str, Any] = {
        "cpu": {"usage_percent": psutil.cpu_percent(interval=0.1),
                "logical_cores": psutil.cpu_count()},
        "memory": {"percent": psutil.virtual_memory().percent,
                   "total": psutil.virtual_memory().total},
    }
    try:
        data["disk"] = {"percent": psutil.disk_usage(os.path.abspath(os.sep)).percent}
    except Exception:
        pass
    try:
        battery = psutil.sensors_battery()
        if battery is not None:
            data["battery"] = {"available": True, "percent": battery.percent,
                               "power_plugged": battery.power_plugged}
    except Exception:
        pass
    return data


# ----------------------------------------------------------------------- #
# client
# ----------------------------------------------------------------------- #
class ViraEndpointClient:
    def __init__(self, server: str, device_id: str, token: str, queue: EventQueue,
                 batch_size: int = 100):
        self.server = server.rstrip("/")
        self.device_id = device_id
        self._headers = {"Authorization": f"Bearer {token}"}
        self.queue = queue
        self.batch_size = batch_size
        self.revoked = False
        self._backoff = 1.0

    def _url(self, suffix: str) -> str:
        return f"{self.server}/api/v1/devices/{self.device_id}/{suffix}"

    async def heartbeat(self, http: aiohttp.ClientSession, capabilities: List[str],
                        capability_status: Dict[str, str]) -> bool:
        body = {"client_version": CLIENT_VERSION, "os_version": platform.release(),
                "capabilities": capabilities, "capability_status": capability_status,
                "queue_backlog": self.queue.depth()}
        async with http.post(self._url("heartbeat"), json=body, headers=self._headers) as resp:
            if resp.status == 401:
                self.revoked = True
            return resp.status == 200

    async def flush(self, http: aiohttp.ClientSession) -> int:
        """Send one batch.  Returns events acknowledged (accepted + duplicates)."""
        pending = self.queue.peek(self.batch_size)
        if not pending:
            return 0
        events = [{k: v for k, v in e.items() if k != "_seq"} for e in pending]
        seq_by_id = {e["event_id"]: e["_seq"] for e in pending}
        try:
            async with http.post(self._url("events:batch"), json={"events": events},
                                 headers=self._headers) as resp:
                if resp.status == 401:
                    self.revoked = True          # credential revoked/expired: stop sending
                    return 0
                if resp.status == 429:
                    delay = float(resp.headers.get("Retry-After", "5"))
                    await asyncio.sleep(delay + random.random())
                    return 0
                if resp.status >= 500:
                    raise aiohttp.ClientError(f"server error {resp.status}")
                if resp.status != 200:
                    # Permanent client error for the whole batch: drop it rather than loop forever.
                    self.queue.ack(list(seq_by_id.values()))
                    return 0
                result = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            await asyncio.sleep(self._backoff + random.random())      # backoff with jitter
            self._backoff = min(self._backoff * 2, 60.0)
            return 0
        self._backoff = 1.0
        done = [seq_by_id[r["event_id"]] for r in result["results"]
                if r.get("event_id") in seq_by_id and r["status"] in ("accepted", "duplicate", "rejected")]
        # Rejected items are permanent (bad type/schema): acknowledging them avoids poison loops.
        self.queue.ack(done)
        return len(done)

    async def run(self, interval: float = 5.0, heartbeat_every: float = 30.0) -> None:
        capabilities = ["hardware_state"]
        status: Dict[str, str] = {}
        timeout = aiohttp.ClientTimeout(total=30)
        last_heartbeat = 0.0
        async with aiohttp.ClientSession(timeout=timeout) as http:
            while not self.revoked:
                try:
                    self.queue.push("sensor.hardware.state", "hardware_sensor", collect_hardware())
                    status["hardware_state"] = "available"
                except Exception:
                    status["hardware_state"] = "unavailable"
                try:
                    if time.monotonic() - last_heartbeat >= heartbeat_every:
                        await self.heartbeat(http, capabilities, status)
                        last_heartbeat = time.monotonic()
                    while not self.revoked and await self.flush(http):
                        pass
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    await asyncio.sleep(self._backoff + random.random())
                    self._backoff = min(self._backoff * 2, 60.0)
                await asyncio.sleep(interval)
        print("Credential revoked or expired; stopping. Re-enrol this device.", file=sys.stderr)


async def enroll(server: str, username: str, password: str, name: str,
                 store: CredentialStore) -> str:
    server = server.rstrip("/")
    async with aiohttp.ClientSession() as http:
        async with http.post(f"{server}/api/v1/auth/login",
                             json={"username": username, "password": password}) as resp:
            if resp.status != 200:
                raise SystemExit("Login failed")
            session_id = (await resp.json())["principal"]["session_id"]
        body = {
            "display_name": name,
            "platform": _PLATFORMS.get(platform.system().lower(), "other"),
            "device_type": "laptop",
            "os_version": platform.release(),
            "client_version": CLIENT_VERSION,
            "capabilities": ["hardware_state"],
        }
        async with http.post(f"{server}/api/v1/devices", json=body,
                             headers={"Authorization": f"Bearer {session_id}"}) as resp:
            if resp.status != 201:
                raise SystemExit(f"Registration failed ({resp.status})")
            created = await resp.json()
        await http.post(f"{server}/api/v1/auth/logout",
                        headers={"Authorization": f"Bearer {session_id}"})
    store.save(server, created["device_id"], created["credential"]["token"])
    return created["device_id"]


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(prog="vira-endpoint")
    sub = parser.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("enroll")
    e.add_argument("--server", required=True)
    e.add_argument("--username", required=True)
    e.add_argument("--name", default=platform.node() or "endpoint")
    r = sub.add_parser("run")
    r.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args(argv)
    store = CredentialStore()
    if args.cmd == "enroll":
        device_id = asyncio.run(enroll(args.server, args.username,
                                       getpass.getpass("Password: "), args.name, store))
        print(f"Enrolled device {device_id}; credential stored at {store.path}")
    else:
        cred = store.load()
        client = ViraEndpointClient(cred["server"], cred["device_id"], cred["token"],
                                    EventQueue(store.home / "queue.sqlite3"))
        asyncio.run(client.run(interval=args.interval))


if __name__ == "__main__":
    main()
