#!/usr/bin/env python3
"""VIRA five-minute proof.

Runs a real end-to-end demo against a local VIRA server:

1. signs in as a VIRA user;
2. creates a conversation;
3. asks the Chatbot about the signed-in account's devices;
4. asks about all devices on the server;
5. shows the live tool activity and final answers;
6. verifies that the database tools reject writes and secret columns.

It uses only the Python standard library. It does not start the server and does
not store credentials.

Usage:
    VIRA_USERNAME=you VIRA_PASSWORD=... python3 scripts/demo.py

Optional:
    python3 scripts/demo.py --url http://localhost:8000 --ask "How many devices..."
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
import uuid
from pathlib import Path
from urllib import error, request

DEFAULT_QUESTIONS = [
    "How many devices are connected with my account? Use the database tools.",
    "How many devices are connected with the server? Use the database tools.",
]


def normalize_url(value: str) -> str:
    url = (value or "").strip()
    if not url:
        url = "http://localhost:8000"
    if "://" not in url:
        url = f"http://{url}"
    return url.rstrip("/")


def request_json(
    url: str,
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    token: str | None = None,
    cookie: str | None = None,
    timeout: float = 30,
) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = request.Request(f"{url}{path}", data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
            detail = payload.get("detail") or payload.get("error") or raw
        except ValueError:
            detail = raw
        raise RuntimeError(f"{path} returned HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(
            f"Cannot reach {url}. Is the VIRA server running?"
        ) from exc
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise RuntimeError(f"{path} returned non-JSON data: {raw[:200]!r}") from exc


def stream_chat(
    url: str,
    token: str,
    conversation_id: str,
    message: str,
    *,
    timeout: float = 300,
    cookie: str | None = None,
):
    payload = json.dumps(
        {"conversation_id": conversation_id, "message": message}
    ).encode("utf-8")
    req = request.Request(f"{url}/chat/stream", data=payload, method="POST")
    req.add_header("Accept", "application/x-ndjson")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if cookie:
        req.add_header("Cookie", cookie)
    req.add_header("Idempotency-Key", str(uuid.uuid4()))
    try:
        response = request.urlopen(req, timeout=timeout)
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
            detail = payload.get("detail") or payload.get("error") or raw
        except ValueError:
            detail = raw
        raise RuntimeError(f"Chat failed with HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(
            f"Cannot reach {url}. Is the VIRA server running?"
        ) from exc

    with response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue


def short_tool(name: str) -> str:
    return str(name or "tool").split(".")[-1]


def display_answer(value: str) -> str:
    """Display-only cleanup.

    The server may include model reasoning wrappers in the raw answer. The demo
    is a presentation layer, so it shows only the final answer. The client-side
    parser work is tracked separately in Phase 2 of ROADMAP.md.
    """
    text = value or ""
    closing = list(re.finditer(r"</think[^>]*>", text, flags=re.IGNORECASE))
    if closing:
        text = text[closing[-1].end() :]
    else:
        legacy = text.lower().rfind("</think")
        if legacy >= 0:
            start = legacy + len("</think")
            while start < len(text) and text[start] in "> \t\r\n":
                start += 1
            text = text[start:]
    text = re.sub(r"</?think[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<\|[^|>]*\|>", "", text)
    return text.strip()


def ask_question(url: str, token: str, conversation_id: str, question: str) -> str:
    print(f"\nYou: {question}")
    tool_calls = 0
    last_status = ""
    answer = None
    for event in stream_chat(url, token, conversation_id, question):
        kind = event.get("type")
        if kind == "status":
            label = event.get("label") or event.get("message")
            if label and label != last_status:
                last_status = label
                print(f"  … {label}")
        elif kind == "tool_start":
            tool_calls += 1
            print(f"  → {short_tool(event.get('tool'))}")
        elif kind == "tool_end":
            ok = event.get("ok") is not False
            millis = event.get("ms")
            suffix = f" ({millis} ms)" if isinstance(millis, int) else ""
            print(f"    {'✓' if ok else '✗'} {short_tool(event.get('tool'))}{suffix}")
        elif kind == "check":
            message = event.get("text") or event.get("message")
            if message:
                print(f"  ! {message}")
        elif kind == "done":
            answer = event.get("response")
        elif kind == "error":
            raise RuntimeError(
                event.get("detail") or "The Chatbot returned an error."
            )
    if answer is None:
        raise RuntimeError("The stream closed before VIRA answered.")
    print(f"\nVIRA: {display_answer(str(answer))}")
    print(f"      ({tool_calls} tool call{'s' if tool_calls != 1 else ''})")
    return display_answer(str(answer))


def safety_check() -> bool:
    """Show the read-only database boundary without touching the database."""
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    print("\n[4/4] Checking the read-only database boundary")
    try:
        from vira.tools.database_query import validate_sql
    except Exception as exc:  # noqa: BLE001 - demo must explain missing installs
        print(f"  ! Could not import the validator: {exc}")
        print("  ! Run this script from the VIRA repository root.")
        return False
    checks = [
        ("DELETE FROM devices", False),
        ("UPDATE users SET role = 'admin'", False),
        ("SELECT password_hash FROM users", False),
        ("SELECT COUNT(*) FROM devices", True),
    ]
    passed = True
    for sql, expected in checks:
        ok, reason = validate_sql(sql)
        if ok != expected:
            passed = False
            print(f"  ✗ unexpected result for {sql!r}: {reason}")
            continue
        if expected:
            print(f"  ✓ allowed: {sql}")
        else:
            print(f"  ✓ rejected: {sql} — {reason}")
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("VIRA_URL", "http://localhost:8000"))
    parser.add_argument("--username", default=os.getenv("VIRA_USERNAME", ""))
    parser.add_argument("--password", default=os.getenv("VIRA_PASSWORD", ""))
    parser.add_argument(
        "--ask",
        action="append",
        default=None,
        help="Ask one custom question (repeatable). Defaults to the two device questions.",
    )
    parser.add_argument("--skip-safety", action="store_true")
    args = parser.parse_args()

    url = normalize_url(args.url)
    username = args.username.strip()
    password = args.password
    if not username:
        username = input("VIRA username: ").strip()
    if not password:
        if sys.stdin.isatty():
            password = getpass.getpass("VIRA password: ")
        else:
            print(
                "Set VIRA_PASSWORD or pass --password when running non-interactively.",
                file=sys.stderr,
            )
            return 2

    print("VIRA five-minute proof")
    print(f"Server: {url}")
    print("[1/4] Signing in")
    try:
        login = request_json(
            url,
            "/api/v1/auth/login",
            method="POST",
            body={"username": username, "password": password},
        )
        principal = login.get("principal") or {}
        token = principal.get("session_id")
        if not token:
            raise RuntimeError("The server did not return a session.")
        print(f"  ✓ signed in as {principal.get('username', username)}")
    except Exception as exc:  # noqa: BLE001 - friendly demo errors
        print(f"  ✗ {exc}", file=sys.stderr)
        print(
            "  If this is a fresh server, open it in a browser and create the "
            "administrator first.",
            file=sys.stderr,
        )
        return 1

    try:
        print("[2/4] Creating a demo conversation")
        conversation = request_json(
            url,
            "/api/v1/conversations",
            method="POST",
            body={"title": "VIRA Phase 1 demo", "incognito": False},
            token=token,
        )
        conversation_id = conversation.get("id")
        if not conversation_id:
            raise RuntimeError("The server did not return a conversation id.")
        print(f"  ✓ conversation {conversation_id}")

        print("[3/4] Asking the Chatbot")
        questions = args.ask or DEFAULT_QUESTIONS
        for question in questions:
            ask_question(url, token, conversation_id, question)
    except Exception as exc:  # noqa: BLE001 - friendly demo errors
        print(f"  ✗ {exc}", file=sys.stderr)
        print(
            "  Check that the Chatbot agent is enabled and a model is available.",
            file=sys.stderr,
        )
        return 1

    if not args.skip_safety and not safety_check():
        return 1

    print("\nDemo complete.")
    print("What you just saw: authenticated chat, live agent tool calls, and a")
    print("read-only database boundary that rejects writes and secret columns.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
