"""``vira doctor``: a dependency-free first-run health check.

It verifies the things that most often break a first VIRA session before the
user reaches the browser: Docker/Compose, Ollama, the selected model and its
context size, port conflicts, the Chatbot agent, database writability and the
master key used for encryption at rest.

Run it as::

    python -m vira doctor
    python3 -m vira.doctor --json
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib import error, parse, request

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Check:
    name: str
    status: str  # ok | warn | fail | skip
    summary: str
    detail: Optional[str] = None
    fix: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "summary": self.summary,
            "detail": self.detail,
            "fix": self.fix,
        }


@dataclass
class Report:
    checks: List[Check] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(check.status == "fail" for check in self.checks)

    def add(self, check: Check) -> None:
        self.checks.append(check)

    def as_dict(self) -> Dict[str, Any]:
        counts = {status: 0 for status in ("ok", "warn", "fail", "skip")}
        for check in self.checks:
            counts[check.status] = counts.get(check.status, 0) + 1
        return {
            "ok": not self.failed,
            "counts": counts,
            "checks": [check.as_dict() for check in self.checks],
        }


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    path = Path(config_path or os.environ.get("VIRA_CONFIG", "config.yaml"))
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        return {}
    try:
        import yaml

        with path.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def check_config(path: Optional[str]) -> Check:
    resolved = Path(path or os.environ.get("VIRA_CONFIG", "config.yaml"))
    if not resolved.is_absolute():
        resolved = ROOT / resolved
    if not resolved.exists():
        return Check(
            "configuration", "fail", f"No config file at {resolved}",
            fix="Run VIRA from the repository root or set VIRA_CONFIG to your config.yaml.",
        )
    try:
        import yaml

        with resolved.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise ValueError("top level is not a mapping")
    except Exception as exc:
        return Check("configuration", "fail", f"Could not parse {resolved}: {exc}",
                     fix="Fix the YAML syntax in config.yaml.")
    return Check("configuration", "ok", f"Loaded {resolved}")


def _run(command: List[str], timeout: float = 5.0) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout)


def check_docker() -> Check:
    docker = _which("docker")
    if not docker:
        return Check(
            "docker", "warn", "Docker is not installed",
            detail="Source installs do not need Docker; the one-command installer does.",
            fix="Install Docker Engine/Desktop, or keep running VIRA with run.py.",
        )
    try:
        info = _run([docker, "info"])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Check("docker", "warn", f"Docker is installed but did not respond: {exc}",
                     fix="Start Docker and re-run the doctor.")
    if info.returncode != 0:
        return Check("docker", "warn", "Docker is installed but the daemon is not reachable",
                     detail=(info.stderr or info.stdout or "").strip()[:300],
                     fix="Start Docker Desktop or `sudo systemctl start docker`.")
    try:
        compose = _run([docker, "compose", "version"])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Check("docker", "warn", f"Docker Compose did not respond: {exc}",
                     fix="Install the Docker Compose v2 plugin.")
    if compose.returncode != 0:
        return Check("docker", "warn", "Docker Compose v2 is not available",
                     detail=(compose.stderr or compose.stdout or "").strip()[:300],
                     fix="Install the Docker Compose plugin (`docker compose version`).")
    version = (compose.stdout or "").splitlines()[0] if compose.stdout else "Compose ready"
    return Check("docker", "ok", f"Docker daemon reachable · {version}")


def _which(name: str) -> Optional[str]:
    try:
        from shutil import which

        return which(name)
    except Exception:
        return None


def check_ollama(base_url: str) -> Check:
    from vira.llm.catalog import list_ollama_models

    try:
        models = list_ollama_models(base_url, timeout=3)
    except (error.URLError, error.HTTPError, OSError, ValueError) as exc:
        return Check(
            "ollama", "fail", f"Cannot reach Ollama at {base_url}",
            detail=str(exc),
            fix="Start Ollama (`ollama serve`) or set VIRA_OLLAMA_URL to the right endpoint.",
        )
    return Check("ollama", "ok", f"Ollama reachable at {base_url} · {len(models)} model(s)")


def check_model(config: Dict[str, Any], base_url: str, ollama_ok: bool) -> Check:
    from vira.llm.catalog import (
        configured_context,
        configured_model,
        list_ollama_models,
        model_context_length,
        show_ollama_model,
    )

    model = configured_model(config)
    if not model:
        return Check("model", "fail", "No Ollama model is configured",
                     fix="Set llm.default_model and an llm.models entry in config.yaml.")
    if not ollama_ok:
        return Check("model", "skip", f"Configured model: {model} (Ollama is unreachable)")

    try:
        installed = {item["name"] for item in list_ollama_models(base_url, timeout=3)}
    except Exception as exc:
        return Check("model", "skip", f"Could not list models: {exc}")

    if model not in installed:
        return Check(
            "model", "fail", f"Configured model '{model}' is not installed",
            detail="Installed: " + (", ".join(sorted(installed)) or "none"),
            fix=f"Run `ollama pull {model}` (or choose one of the installed models).",
        )

    detail = None
    shown = {}
    try:
        shown = show_ollama_model(model, base_url, timeout=3)
        context = model_context_length(shown)
    except Exception:
        context = None
    parameter_size = str((shown.get("details") or {}).get("parameter_size") or "").strip()
    if parameter_size:
        detail = f"parameters: {parameter_size}"
    try:
        billions = float(parameter_size.rstrip("Bb"))
    except ValueError:
        billions = None
    if billions is not None and billions < 4:
        return Check(
            "model", "warn", f"'{model}' is very small ({parameter_size})",
            detail="Tool use may be unreliable below about 4B parameters. Chat works, but multi-step tools can loop or return malformed JSON.",
            fix="Use qwen3.5:9b or larger for reliable tool use, or configure a cloud provider.",
        )
    wanted = configured_context(config)
    if context:
        detail = f"trained/pulled context: {context:,} tokens"
    if wanted:
        detail = (detail + " · " if detail else "") + f"configured num_ctx: {wanted:,} tokens"
        if wanted < 8192:
            return Check("model", "warn", f"'{model}' is installed but num_ctx is only {wanted:,}",
                         detail=detail,
                         fix="Raise llm.models[].num_ctx to at least 8192 for tool-heavy chats.")
    if not context and not wanted:
        return Check("model", "warn", f"'{model}' is installed; context size is unknown",
                     fix="Set llm.models[].num_ctx (8192 or more) to avoid truncated prompts.")
    return Check("model", "ok", f"'{model}' is installed and ready", detail=detail)


def check_port(url: str) -> Check:
    parsed = parse.urlparse(url if "://" in url else f"http://{url}")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with request.urlopen(f"{parsed.scheme or 'http'}://{host}:{port}/livez", timeout=2) as response:
            if response.status == 200:
                return Check("port", "ok", f"VIRA is already answering on {host}:{port}")
    except (error.URLError, error.HTTPError, OSError, ValueError):
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host if host not in ("0.0.0.0", "::") else "127.0.0.1", port))
    except OSError as exc:
        return Check("port", "fail", f"Port {port} is already in use",
                     detail=str(exc),
                     fix=f"Stop the other process, or start VIRA with VIRA_PORT=<free port>.")
    return Check("port", "ok", f"Port {port} is free")


def check_chatbot(config: Dict[str, Any]) -> Check:
    agents = config.get("agents") or []
    chatbot = next(
        (agent for agent in agents
         if str(agent.get("class", "")).lower() == "chatagent"
         or str(agent.get("name", "")).lower() == "chatbot"),
        None,
    )
    if chatbot is None:
        return Check("chatbot", "fail", "No Chatbot agent is configured",
                     fix="Add the Chatbot agent block to config.yaml (see the default config).")
    if not chatbot.get("enabled", True):
        return Check("chatbot", "fail", "The Chatbot agent is disabled",
                     fix="Set agents[].enabled: true for the Chatbot and restart VIRA.")
    return Check("chatbot", "ok", f"Chatbot agent enabled ({chatbot.get('name', 'Chatbot')})")


def check_database(config: Dict[str, Any]) -> Check:
    database_url = os.environ.get("VIRA_DATABASE_URL", "")
    if database_url.startswith(("postgres://", "postgresql://")):
        try:
            import psycopg

            with psycopg.connect(database_url, connect_timeout=3) as conn:
                conn.execute("SELECT 1")
            return Check("database", "ok", "PostgreSQL is reachable and writable")
        except Exception as exc:
            return Check("database", "fail", f"Cannot use PostgreSQL: {exc}",
                         fix="Check VIRA_DATABASE_URL, the server and the password.")
    sqlite_url = database_url or str(config.get("auth", {}).get("database_url", "sqlite:///data/vira.sqlite3"))
    path_text = sqlite_url[len("sqlite:///"):] if sqlite_url.startswith("sqlite:///") else sqlite_url
    path = Path(path_text)
    if not path.is_absolute():
        path = ROOT / path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            with path.open("rb"):
                pass
        else:
            with tempfile.NamedTemporaryFile(dir=str(path.parent), prefix=".vira-doctor-", delete=True):
                pass
    except OSError as exc:
        return Check("database", "fail", f"Database path is not writable: {path}",
                     detail=str(exc),
                     fix="Fix ownership/permissions or point auth.database_url at a writable path.")
    return Check("database", "ok", f"SQLite database is writable at {path}")


def check_master_key() -> Check:
    if os.environ.get("VIRA_MASTER_KEY"):
        return Check("master_key", "ok", "Master key provided by VIRA_MASTER_KEY")
    key_file = Path(os.environ.get("VIRA_MASTER_KEY_FILE", "data/.vira_master_key"))
    if not key_file.is_absolute():
        key_file = ROOT / key_file
    if key_file.exists():
        try:
            data = key_file.read_bytes().strip()
        except OSError as exc:
            return Check("master_key", "fail", f"Cannot read {key_file}: {exc}",
                         fix="Fix the file permissions, or set VIRA_MASTER_KEY.")
        if not data:
            return Check("master_key", "fail", f"{key_file} is empty",
                         fix="Restore the key from a backup, or remove it to generate a new one.")
        return Check("master_key", "ok", f"Master key found at {key_file}",
                     detail="Back this file up separately; encrypted values cannot be recovered without it.")
    return Check(
        "master_key", "warn", "No master key yet",
        detail="VIRA creates data/.vira_master_key on the first encrypted write.",
        fix="Complete setup, then back up data/.vira_master_key separately from the database.",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def run_doctor(config_path: Optional[str] = None, url: str = "http://localhost:8000",
               include_docker: bool = True) -> Report:
    from vira.llm.catalog import configured_ollama_url

    report = Report()
    report.add(check_config(config_path))
    config = load_config(config_path)

    if include_docker:
        report.add(check_docker())

    base_url = configured_ollama_url(config)
    ollama = check_ollama(base_url)
    report.add(ollama)
    report.add(check_model(config, base_url, ollama.status == "ok"))
    report.add(check_port(url))
    report.add(check_chatbot(config))
    report.add(check_database(config))
    report.add(check_master_key())
    return report


_SYMBOLS = {"ok": "✓", "warn": "!", "fail": "✕", "skip": "·"}


def print_report(report: Report, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(report.as_dict(), indent=2))
        return
    print("VIRA doctor")
    print("=" * 60)
    for check in report.checks:
        print(f"  {_SYMBOLS.get(check.status, '?')} {check.name:<14} {check.summary}")
        if check.detail:
            print(f"      {check.detail}")
        if check.fix and check.status in ("warn", "fail"):
            print(f"      fix: {check.fix}")
    counts = report.as_dict()["counts"]
    print("=" * 60)
    print(f"  {counts['ok']} ok · {counts['warn']} warning(s) · {counts['fail']} failure(s)")
    if report.failed:
        print("  Follow the fixes above, then re-run `python -m vira doctor`.")
    else:
        print("  No blocking problems found. Open the web console to create the admin account.")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vira doctor",
        description="Check Docker, Ollama, the selected model, ports, the Chatbot, the database and the master key.",
    )
    parser.add_argument("--url", default=os.environ.get("VIRA_URL", "http://localhost:8000"),
                        help="URL the server should answer on (default: http://localhost:8000)")
    parser.add_argument("--config", default=os.environ.get("VIRA_CONFIG"),
                        help="Path to config.yaml (default: ./config.yaml or VIRA_CONFIG)")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    parser.add_argument("--no-docker", action="store_true", help="Skip the Docker check (source installs)")
    args = parser.parse_args(argv)

    report = run_doctor(args.config, args.url, include_docker=not args.no_docker)
    print_report(report, as_json=args.json)
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
