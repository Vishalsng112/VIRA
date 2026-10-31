"""Sandboxed project workspace: the only place mission agents may write.

Every path is validated (no absolute paths, no '..', no hidden dirs, size caps), so an
LLM that hallucinates ``../../etc/passwd`` cannot escape.  Light, safe checks (python
syntax, JSON) are run on write and fed back to the author - nothing is ever executed.
"""
import ast
import io
import json
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List

ALLOWED_DOT = {".gitignore", ".env.example", ".dockerignore", ".editorconfig"}


class WorkspaceError(ValueError):
    pass


class Workspace:
    def __init__(self, root, max_file_bytes: int = 300_000, max_files: int = 500):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_file_bytes, self.max_files = max_file_bytes, max_files
        self.meta: Dict[str, Dict[str, Any]] = {}       # rel path -> {author, version, check, t}

    def _safe(self, rel: str) -> Path:
        rel = str(rel).replace("\\", "/").strip().lstrip("/")
        if not rel or len(rel) > 200 or "\0" in rel:
            raise WorkspaceError("invalid path")
        parts = rel.split("/")
        for part in parts:
            if part in ("", ".", "..") or (part.startswith(".") and part not in ALLOWED_DOT):
                raise WorkspaceError(f"path not allowed: {rel}")
        p = (self.root / rel).resolve()
        if self.root not in p.parents:
            raise WorkspaceError("path escapes workspace")
        return p

    @staticmethod
    def check(rel: str, content: str) -> str:
        """Return '' if fine, else a short problem description (never executes code)."""
        try:
            if rel.endswith(".py"):
                ast.parse(content)
            elif rel.endswith(".json"):
                json.loads(content)
        except SyntaxError as exc:
            return f"python syntax error line {exc.lineno}: {exc.msg}"
        except ValueError as exc:
            return f"invalid JSON: {exc}"
        if "<file path=" in content or "</file>" in content:
            return "file contains stray <file> tags"
        return ""

    def write(self, rel: str, content: str, author: str = "?") -> Dict[str, Any]:
        p = self._safe(rel)
        if len(content.encode("utf-8", "ignore")) > self.max_file_bytes:
            raise WorkspaceError("file too large")
        if not p.exists() and len(self.meta) >= self.max_files:
            raise WorkspaceError("too many files")
        p.parent.mkdir(parents=True, exist_ok=True)
        if content and not content.endswith("\n"):
            content += "\n"
        p.write_text(content, encoding="utf-8")
        rel = p.relative_to(self.root).as_posix()
        old = self.meta.get(rel, {})
        info = {"path": rel, "author": author, "version": old.get("version", 0) + 1,
                "check": self.check(rel, content), "bytes": len(content.encode()),
                "lines": content.count("\n"), "t": time.time()}
        self.meta[rel] = info
        return info

    def read(self, rel: str, limit: int = 0) -> str:
        p = self._safe(rel)
        if not p.is_file():
            raise WorkspaceError(f"no such file: {rel}")
        text = p.read_text(encoding="utf-8", errors="replace")
        return text[:limit] + f"\n... [truncated, {len(text)} chars]" if limit and len(text) > limit else text

    def exists(self, rel: str) -> bool:
        try:
            return self._safe(rel).is_file()
        except WorkspaceError:
            return False

    def files(self) -> List[Dict[str, Any]]:
        out = []
        for p in sorted(self.root.rglob("*")):
            if p.is_file():
                rel = p.relative_to(self.root).as_posix()
                m = self.meta.get(rel, {})
                out.append({"path": rel, "bytes": p.stat().st_size, "author": m.get("author", ""),
                            "version": m.get("version", 1), "check": m.get("check", "")})
        return out

    def tree_text(self, max_items: int = 120) -> str:
        fs = self.files()
        lines = [f"- {f['path']} ({f['bytes']}B, by {f['author'] or '?'})" + (f" !! {f['check']}" if f["check"] else "")
                 for f in fs[:max_items]]
        return "\n".join(lines) + (f"\n... +{len(fs) - max_items} more" if len(fs) > max_items else "") or "(empty)"

    def zip_bytes(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in self.files():
                z.write(self.root / f["path"], f["path"])
        return buf.getvalue()
