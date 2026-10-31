"""Build / test verification for missions (the "run it, read the errors, send them back" loop).

Two layers, both producing the same ``Issue`` records:

1. ``static_issues``  - needs no toolchain: YAML validity (pubspec.yaml!), Flutter project shape, Dart bracket balance,
   unresolved ``package:`` / relative imports, undeclared dependencies, empty files.
2. ``run_checks``     - actually runs the stack's own tooling inside the project folder
   (``flutter pub get`` / ``flutter analyze`` / ``flutter test``, ``npm install`` / ``npm test``, ``python -m compileall`` / ``pytest``)
   with a timeout and capped output.  A missing tool is reported as *skipped*, never as a project bug.

``route_issues`` maps every problem to the agent that wrote the offending file so the Master can open fix tasks.
Command execution can be switched off with ``mission.execute_checks: false`` in config.yaml.
"""
import asyncio
import os
import re
import shutil
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:                                           # pragma: no cover
    yaml = None

OUT_CAP = 6000


@dataclass
class Issue:
    path: str                  # workspace-relative file ("" = project level)
    problem: str
    source: str = "static"     # static | command name
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CmdResult:
    cmd: List[str]
    code: Optional[int]        # None = could not run
    output: str = ""
    skipped: str = ""          # reason, e.g. "flutter not installed"
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.code == 0 and not self.timed_out

    @property
    def label(self) -> str:
        return " ".join(self.cmd)


# --------------------------------------------------------------------------- static checks
def _strip_dart(src: str) -> str:
    """Remove comments and string contents so bracket counting is not fooled."""
    out, i, n = [], 0, len(src)
    while i < n:
        c, two = src[i], src[i:i + 2]
        if two == "//":
            while i < n and src[i] != "\n":
                i += 1
        elif two == "/*":
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
        elif c in "'\"":
            q = src[i:i + 3] if src[i:i + 3] in ("'''", '"""') else c
            raw = i > 0 and src[i - 1] == "r"
            i += len(q)
            while i < n and not src.startswith(q, i):
                if src[i] == "\\" and not raw:
                    i += 1
                if len(q) == 1 and src[i:i + 1] == "\n":
                    break
                i += 1
            i += len(q)
            out.append('""')
            continue
        else:
            out.append(c)
            i += 1
    return "".join(out)


def dart_balance(src: str) -> str:
    pairs, stack, line = {")": "(", "]": "[", "}": "{"}, [], 1
    for ch in _strip_dart(src):
        if ch == "\n":
            line += 1
        elif ch in "([{":
            stack.append((ch, line))
        elif ch in pairs:
            if not stack or stack[-1][0] != pairs[ch]:
                return f"unbalanced '{ch}' near line {line}"
            stack.pop()
    return f"unclosed '{stack[-1][0]}' opened at line {stack[-1][1]}" if stack else ""


def _yaml_error(text: str) -> str:
    if yaml is None:
        return ""
    try:
        yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark else ""
        return f"invalid YAML{where}: {getattr(exc, 'problem', None) or str(exc).splitlines()[0]}"
    return ""


_DART_IMPORT = re.compile(r"""^\s*(?:import|export|part)\s+['"]([^'"]+)['"]""", re.M)
_SDK_PKGS = {"flutter", "flutter_test", "flutter_localizations", "flutter_web_plugins", "integration_test"}


def _flutter_issues(ws, files: List[str]) -> List[Issue]:
    issues: List[Issue] = []
    try:
        spec = yaml.safe_load(ws.read("pubspec.yaml")) if yaml else {}
    except Exception:
        return issues                                            # YAML error already reported separately
    if not isinstance(spec, dict):
        return [Issue("pubspec.yaml", "pubspec.yaml must be a YAML mapping with name, environment, dependencies")]
    name = str(spec.get("name") or "")
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        issues.append(Issue("pubspec.yaml", f"'name' must be lower_snake_case (got {name!r})"))
    if not isinstance(spec.get("environment"), dict) or "sdk" not in spec["environment"]:
        issues.append(Issue("pubspec.yaml", "missing 'environment: sdk: \">=3.0.0 <4.0.0\"'"))
    deps = spec.get("dependencies") or {}
    dev = spec.get("dev_dependencies") or {}
    if not isinstance(deps, dict) or "flutter" not in deps:
        issues.append(Issue("pubspec.yaml", "dependencies must contain 'flutter: {sdk: flutter}'"))
    elif not (isinstance(deps["flutter"], dict) and deps["flutter"].get("sdk") == "flutter"):
        issues.append(Issue("pubspec.yaml", "'flutter' dependency must be written as  flutter:\\n    sdk: flutter"))
    declared = set(deps if isinstance(deps, dict) else []) | set(dev if isinstance(dev, dict) else [])
    if not ws.exists("lib/main.dart"):
        issues.append(Issue("lib/main.dart", "missing entry point lib/main.dart"))
    elif not re.search(r"\bvoid\s+main\s*\(", ws.read("lib/main.dart")):
        issues.append(Issue("lib/main.dart", "lib/main.dart has no 'void main()' function"))
    have = set(files)
    for rel in files:
        if not rel.endswith(".dart"):
            continue
        src = ws.read(rel)
        bal = dart_balance(src)
        if bal:
            issues.append(Issue(rel, f"Dart syntax: {bal}"))
        base = rel.rsplit("/", 1)[0] if "/" in rel else ""
        for imp in _DART_IMPORT.findall(src):
            if imp.startswith("dart:"):
                continue
            if imp.startswith("package:"):
                pkg, _, sub = imp[8:].partition("/")
                if pkg == name:
                    if f"lib/{sub}" not in have:
                        issues.append(Issue(rel, f"import '{imp}' points to a file that does not exist (lib/{sub})"))
                elif pkg not in declared and pkg not in _SDK_PKGS:
                    issues.append(Issue(rel, f"imports package '{pkg}' which is not listed in pubspec.yaml dependencies",
                                        extra={"also": "pubspec.yaml"}))
            else:
                parts: List[str] = []
                for seg in (base + "/" + imp).split("/") if base else imp.split("/"):
                    if seg == "..":
                        if parts:
                            parts.pop()
                    elif seg not in (".", ""):
                        parts.append(seg)
                if "/".join(parts) not in have:
                    issues.append(Issue(rel, f"import '{imp}' points to a file that does not exist"))
    return issues


def static_issues(ws) -> List[Issue]:
    """Toolchain-free checks over the whole project."""
    issues: List[Issue] = []
    files = [f["path"] for f in ws.files()]
    for rel in files:
        if rel.endswith((".yaml", ".yml")):
            err = _yaml_error(ws.read(rel))
            if err:
                issues.append(Issue(rel, err))
        if rel.endswith((".dart", ".py", ".js", ".ts", ".dart", ".json", ".yaml")) and not ws.read(rel, limit=50).strip():
            issues.append(Issue(rel, "file is empty"))
    if "pubspec.yaml" in files:
        issues += _flutter_issues(ws, files)
    if "package.json" in files:
        try:
            import json
            pkg = json.loads(ws.read("package.json"))
            if not isinstance(pkg, dict) or not pkg.get("name"):
                issues.append(Issue("package.json", "package.json needs at least a 'name'"))
        except ValueError:
            pass                                                 # reported by Workspace.check
    return issues


# --------------------------------------------------------------------------- command checks
def detect_commands(ws) -> List[List[str]]:
    files = {f["path"] for f in ws.files()}
    cmds: List[List[str]] = []
    if "pubspec.yaml" in files:
        flutter = "flutter" if shutil.which("flutter") or not shutil.which("dart") else "dart"
        if flutter == "flutter":
            cmds += [["flutter", "pub", "get"], ["flutter", "analyze", "--no-fatal-infos", "--no-fatal-warnings"]]
            if any(p.startswith("test/") and p.endswith("_test.dart") for p in files):
                cmds.append(["flutter", "test"])
        else:
            cmds += [["dart", "pub", "get"], ["dart", "analyze"]]
    if "package.json" in files:
        cmds += [["npm", "install", "--no-audit", "--no-fund"], ["npm", "run", "build", "--if-present"],
                 ["npm", "test", "--if-present"]]
    py = [p for p in files if p.endswith(".py")]
    if py:
        cmds.append(["python3", "-m", "compileall", "-q", "."])
        if any(p.startswith("tests/") or "/test_" in p or p.startswith("test_") for p in py) and shutil.which("pytest"):
            cmds.append(["pytest", "-x", "-q"])
    return cmds


async def run_cmd(cmd: List[str], cwd, timeout: int = 300) -> CmdResult:
    if not shutil.which(cmd[0]):
        return CmdResult(cmd, None, skipped=f"'{cmd[0]}' is not installed on the VIRA server")
    env = {k: v for k, v in os.environ.items() if not k.endswith(("KEY", "TOKEN", "SECRET", "PASSWORD"))}
    env.update(CI="true", PUB_ENVIRONMENT="vira_mission", FLUTTER_SUPPRESS_ANALYTICS="true", NO_COLOR="1")
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, cwd=str(cwd), env=env, stdin=asyncio.subprocess.DEVNULL,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    except OSError as exc:
        return CmdResult(cmd, None, skipped=str(exc))
    try:
        raw, _ = await asyncio.wait_for(proc.communicate(), timeout)
        timed = False
    except asyncio.TimeoutError:
        proc.kill()
        raw, _ = await proc.communicate()
        timed = True
    text = raw.decode("utf-8", "replace")
    if len(text) > OUT_CAP * 3:
        text = text[:OUT_CAP] + "\n...[middle cut]...\n" + text[-OUT_CAP * 2:]
    code = proc.returncode
    if cmd[0] == "pytest" and code == 5:                     # pytest: "no tests collected" is not a build failure
        code = 0
    return CmdResult(cmd, code, text, timed_out=timed)


_PATH_LINE = re.compile(r"((?:[\w.\-]+/)*[\w.\-]+\.(?:dart|py|js|jsx|ts|tsx|yaml|yml|json|kt|java|swift))(?::(\d+))?")


def issues_from_result(res: CmdResult, known: List[str]) -> List[Issue]:
    """Turn a failed command into issues, one per workspace file mentioned in its output (else one project-level issue)."""
    if res.ok or res.skipped:
        return []
    kn = set(known)
    per: Dict[str, List[str]] = {}
    lines = res.output.splitlines()
    for i, ln in enumerate(lines):
        for m in _PATH_LINE.finditer(ln):
            rel = m.group(1).lstrip("./")
            if rel in kn:
                per.setdefault(rel, []).append(ln.strip()[:300])
    head = f"`{res.label}` " + ("timed out" if res.timed_out else f"failed (exit {res.code})")
    tail = "\n".join(lines[-25:])[:1500]
    if not per:
        return [Issue("", f"{head}:\n{tail}", source=res.label)]
    return [Issue(rel, f"{head}:\n" + "\n".join(dict.fromkeys(msgs[:8])), source=res.label) for rel, msgs in list(per.items())[:6]]


async def run_checks(ws, timeout: int = 300, execute: bool = True) -> Tuple[List[CmdResult], List[Issue]]:
    """Run the detected commands in order; stop at the first failing install step (later steps would only echo it)."""
    results, issues = [], []
    known = [f["path"] for f in ws.files()]
    if not execute:
        return results, issues
    for cmd in detect_commands(ws):
        res = await run_cmd(cmd, ws.root, timeout)
        results.append(res)
        found = issues_from_result(res, known)
        issues += found
        if found and cmd[1:2] in (["pub"], ["install"]):
            break
    return results, issues


def route_issues(issues: List[Issue], ws, agents: Dict[str, Any], roles: List[Dict[str, Any]], cap: int = 6) -> List[Dict[str, Any]]:
    """Group issues by the agent that wrote the file -> fix-task dicts {owner,title,files,description}."""
    non_qa = [r["key"] for r in roles if not any(x in r["key"] for x in ("qa", "review", "test"))] or [r["key"] for r in roles]
    default = non_qa[0]
    grouped: Dict[str, Dict[str, Any]] = {}
    for it in issues:
        author = ws.meta.get(it.path, {}).get("author") if it.path else ""
        owner = author if author in agents and author != "master" else default
        g = grouped.setdefault(owner, {"owner": owner, "files": [], "msgs": []})
        for p in [it.path, it.extra.get("also")]:
            if p and p not in g["files"]:
                g["files"].append(p)
        g["msgs"].append(f"[{it.source}] {it.path or 'project'}: {it.problem}")
    out = []
    for g in list(grouped.values())[:cap]:
        out.append({"owner": g["owner"], "files": g["files"][:6], "title": f"Fix build errors ({len(g['msgs'])})",
                    "description": ("The project failed automatic verification. Fix EVERY problem below by outputting the complete "
                                    "corrected files (and any missing file). Do not change unrelated behaviour.\n"
                                    + "\n".join(g["msgs"]))[:2500]})
    return out


def summarize(results: List[CmdResult], issues: List[Issue]) -> str:
    rows = []
    for r in results:
        rows.append(f"- `{r.label}`: " + (f"SKIPPED - {r.skipped}" if r.skipped else "OK" if r.ok else
                                           "TIMEOUT" if r.timed_out else f"FAILED (exit {r.code})"))
    rows += [f"- {i.path or 'project'}: {i.problem.splitlines()[0][:200]}" for i in issues]
    return "\n".join(rows) or "- no checks applicable"
