#!/usr/bin/env python3
"""VIRA tool-use benchmark.

Two complementary modes:

* **Offline (default, no server needed).** Runs deterministic agent-loop
  scenarios for device questions, database questions, RAG, web failure
  recovery, repeated calls, malformed JSON and unknown tools. This is the
  baseline recorded in ``docs/dev/benchmarks/tool-use.md`` and it also runs in
  CI through ``vira/tests/test_benchmark.py``.
* **Live (``--url`` + credentials).** Sends representative questions to a
  running VIRA server and records which tools the agent actually called and
  whether the answer arrived. Use this to measure the 9/10 first-run target on
  your recommended local model.

Examples::

    python3 scripts/benchmark.py --offline
    VIRA_USERNAME=you VIRA_PASSWORD=... python3 scripts/benchmark.py --runs 10
    VIRA_TOKEN=<session> python3 scripts/benchmark.py --runs 10
    python3 scripts/benchmark.py --offline --write docs/dev/benchmarks/tool-use.md
"""
from __future__ import annotations

import argparse
import getpass
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from vira.agent.benchmark import run_offline  # noqa: E402

from demo import normalize_url, request_json, stream_chat  # noqa: E402

LIVE_QUESTIONS = [
    {
        "name": "device_question",
        "category": "device",
        "message": "How many devices are connected with my account? Use a tool to check.",
        "expect_any": ["insights", "user_context", "database"],
        "expect_text": "",
    },
    {
        "name": "database_question",
        "category": "database",
        "message": "How many devices are connected with the server? Use the read-only database tool.",
        "expect_any": ["database"],
        "expect_text": "",
    },
    {
        "name": "rag_question",
        "category": "rag",
        "message": "Search my knowledge base for notes about VIRA and summarize what you find.",
        "expect_any": ["rag"],
        "expect_text": "",
    },
    {
        "name": "web_question",
        "category": "web",
        "message": "Search the web for the official Ollama website and tell me its URL.",
        "expect_any": ["web_search", "web_browse"],
        "expect_text": "ollama",
    },
]


def _short(name: str) -> str:
    return str(name or "").split(".")[-1]


def ask_live(url: str, token: str, conversation_id: str, question: Dict[str, Any],
             cookie: Optional[str] = None) -> Dict[str, Any]:
    started = time.monotonic()
    tools: List[str] = []
    failures: List[str] = []
    checks: List[str] = []
    answer = None
    error = None
    try:
        for event in stream_chat(url, token, conversation_id, question["message"],
                                 timeout=300, cookie=cookie):
            kind = event.get("type")
            if kind == "tool_start":
                tools.append(_short(event.get("tool")))
            elif kind == "tool_end" and event.get("ok") is False:
                failures.append(_short(event.get("tool")))
            elif kind == "check":
                checks.append(str(event.get("text") or event.get("message") or ""))
            elif kind == "done":
                answer = str(event.get("response") or "")
            elif kind == "error":
                error = str(event.get("detail") or "chat error")
    except Exception as exc:  # noqa: BLE001 - benchmark records, never crashes
        error = str(exc)
    elapsed = round(time.monotonic() - started, 2)

    matched_tool = any(any(token in tool for token in question["expect_any"]) for tool in tools)
    text_ok = not question.get("expect_text") or question["expect_text"] in (answer or "").lower()
    graceful_rag = (
        question["category"] == "rag"
        and not matched_tool
        and any(word in (answer or "").lower() for word in ("no document", "nothing", "not found", "empty"))
    )
    passed = error is None and answer is not None and (matched_tool or graceful_rag) and text_ok
    detail = (
        "tool calls: " + (", ".join(tools) or "none")
        + (f" · failures: {', '.join(failures)}" if failures else "")
    )
    return {
        "name": question["name"],
        "category": question["category"],
        "passed": passed,
        "detail": detail,
        "answer": (answer or "")[:400],
        "error": error,
        "tools": tools,
        "seconds": elapsed,
    }


def _cookie_from_file(path: str) -> Optional[str]:
    """Read the vira_session value from a Netscape cookie file."""
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if "vira_session" not in line:
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                return f"{parts[5]}={parts[6]}"
    except OSError:
        return None
    return None


def _git_revision() -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def render_markdown(offline: List[Any], live: List[Dict[str, Any]],
                    runs: int, url: Optional[str]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        "# Tool-use benchmark",
        "",
        f"Generated: {now} · revision `{_git_revision()}`",
        "",
        "This benchmark has two layers. The deterministic layer runs without a",
        "model and checks the agent loop's tool selection and recovery behaviour.",
        "The live layer measures a real model and is intentionally run on the",
        "machine that will serve users.",
        "",
        "## Deterministic baseline (offline)",
        "",
        "| Scenario | Category | Result | Tool calls | Steps | What it checks |",
        "|---|---|---|---|---|---|",
    ]
    for item in offline:
        lines.append(
            f"| `{item.name}` | {item.category} | {'PASS' if item.passed else 'FAIL'} "
            f"| {', '.join(item.tool_calls) or '—'} | {item.steps} | {item.detail} |"
        )
    passed = sum(1 for item in offline if item.passed)
    lines += [
        "",
        f"Offline result: **{passed}/{len(offline)} scenarios passed**.",
        "",
    ]
    if live:
        lines += [
            f"## Live run ({runs} repetition{'s' if runs != 1 else ''})",
            "",
            f"Server: `{url}` · model: see your `config.yaml`.",
            "",
            "| Scenario | Result | Runs passed | Tools observed | Detail |",
            "|---|---|---|---|---|",
        ]
        for item in live:
            lines.append(
                f"| `{item['name']}` | {'PASS' if item['passed'] else 'FAIL'} "
                f"| {item['passed_runs']}/{item['runs']} | {', '.join(item['tools']) or '—'} "
                f"| {item['detail']} |"
            )
        lines.append("")
    else:
        lines += [
            "## Live run",
            "",
            "Not recorded in this file. Run it against your server and model:",
            "",
            "```bash",
            "VIRA_USERNAME=you VIRA_PASSWORD=... python3 scripts/benchmark.py --runs 10 \\",
            "  --write docs/dev/benchmarks/tool-use-live.md",
            "```",
            "",
            "The Phase 2 target is at least 9/10 successful runs on the recommended",
            "local model, with device, database and RAG questions answered from tools.",
            "",
        ]
    lines += [
        "## Reproduce",
        "",
        "```bash",
        "python3 scripts/benchmark.py --offline",
        "python3 -m unittest vira.tests.test_benchmark -v",
        "```",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true",
                        help="Only run deterministic scenarios (no server or model).")
    parser.add_argument("--url", default=os.getenv("VIRA_URL", "http://localhost:8000"))
    parser.add_argument("--username", default=os.getenv("VIRA_USERNAME", ""))
    parser.add_argument("--password", default=os.getenv("VIRA_PASSWORD", ""))
    parser.add_argument("--token", default=os.getenv("VIRA_TOKEN", ""),
                        help="Existing VIRA session ID, sent as a Bearer token.")
    parser.add_argument("--cookie", default=os.getenv("VIRA_COOKIE", ""),
                        help="Raw Cookie header value (for example vira_session=...).")
    parser.add_argument("--cookie-file", default="",
                        help="Netscape cookie file containing vira_session.")
    parser.add_argument("--keep-conversation", action="store_true",
                        help="Keep the benchmark conversation instead of deleting it.")
    parser.add_argument("--runs", type=int, default=1,
                        help="Repetitions of each live question (default: 1).")
    parser.add_argument("--write", default=None,
                        help="Write the Markdown report to this path.")
    args = parser.parse_args()

    offline = run_offline()
    for item in offline:
        print(f"{'PASS' if item.passed else 'FAIL'} offline/{item.category:<12} {item.name}: {item.detail}")

    live_results: List[Dict[str, Any]] = []
    if not args.offline:
        cookie = args.cookie.strip() or (
            _cookie_from_file(args.cookie_file) if args.cookie_file else None
        )
        url = normalize_url(args.url)
        token = args.token.strip()
        conversation_id = None
        try:
            if token:
                me = request_json(url, "/api/v1/auth/me", token=token)
                username = me.get("username") or "token-session"
            elif cookie:
                me = request_json(url, "/api/v1/auth/me", cookie=cookie)
                username = me.get("username") or "cookie-session"
            else:
                username = args.username.strip() or input(
                    "VIRA username (blank to skip live run): "
                ).strip()
                password = args.password
                if username and not password:
                    if sys.stdin.isatty():
                        password = getpass.getpass("VIRA password: ")
                    else:
                        print("Set VIRA_PASSWORD for a non-interactive live run.", file=sys.stderr)
                        username = ""
                if not username:
                    raise RuntimeError("skipped")
                login = request_json(url, "/api/v1/auth/login", method="POST",
                                     body={"username": username, "password": password})
                token = (login.get("principal") or {}).get("session_id")
                if not token:
                    raise RuntimeError("login returned no session")
            conversation = request_json(
                url, "/api/v1/conversations", method="POST",
                body={"title": "Tool-use benchmark"}, token=token or None, cookie=cookie,
            )
            conversation_id = conversation["id"]
        except Exception as exc:  # noqa: BLE001
            if str(exc) != "skipped":
                print(f"Live run skipped: {exc}", file=sys.stderr)
        else:
            print(f"Live run as {username} at {url}")
            runs = max(1, args.runs)
            try:
                for question in LIVE_QUESTIONS:
                    attempts = [
                        ask_live(url, token, conversation_id, question, cookie=cookie)
                        for _ in range(runs)
                    ]
                    passed_runs = sum(1 for item in attempts if item["passed"])
                    # The roadmap target is at least 9/10 successful runs.
                    meets_target = passed_runs / runs >= 0.9
                    live_results.append({
                        "name": question["name"],
                        "category": question["category"],
                        "passed": meets_target,
                        "passed_runs": passed_runs,
                        "runs": runs,
                        "tools": sorted({tool for item in attempts for tool in item["tools"]}),
                        "detail": attempts[-1]["detail"],
                        "answers": [item["answer"] for item in attempts],
                    })
                    print(f"{'PASS' if meets_target else 'FAIL'} live/{question['category']:<12} "
                          f"{question['name']}: {passed_runs}/{runs}")
            finally:
                if conversation_id and not args.keep_conversation:
                    try:
                        request_json(
                            url, f"/api/v1/conversations/{conversation_id}",
                            method="DELETE", token=token or None, cookie=cookie,
                        )
                    except Exception as exc:  # noqa: BLE001
                        print(f"Could not delete the benchmark conversation: {exc}", file=sys.stderr)

    report = render_markdown(offline, live_results, args.runs, args.url)
    if args.write:
        output = Path(args.write)
        if not output.is_absolute():
            output = ROOT / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8")
        print(f"Wrote {output}")
    else:
        print()
        print(report)

    offline_ok = all(item.passed for item in offline)
    live_ok = all(item["passed"] for item in live_results) if live_results else True
    return 0 if offline_ok and live_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
