"""Workspace file tools, constrained to one configured root."""
from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field

from ...contract import BaseTool, StrictModel, ToolContext, ToolError, ToolSideEffects


def _root(context: ToolContext) -> Path:
    raw = context.workspace_root or os.getenv("VIRA_WORKSPACE_ROOT") or "."
    return Path(raw).expanduser().resolve()


def _resolve(root: Path, value: str) -> Path:
    candidate = (root / (value or ".")).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ToolError("path_escape", "Path escapes the workspace root.") from exc
    return candidate


class ReadFileInput(StrictModel):
    path: str = Field(min_length=1, description="Path relative to the workspace root.")


class ReadFileOutput(StrictModel):
    path: str
    content: str
    bytes: int


class WriteFileInput(StrictModel):
    path: str = Field(min_length=1)
    content: str


class WriteFileOutput(StrictModel):
    path: str
    bytes: int


class DirectoryEntry(StrictModel):
    path: str
    type: str
    size: int | None = None


class ListDirectoryInput(StrictModel):
    path: str = "."
    max_results: int = Field(default=200, ge=1, le=1000)


class ListDirectoryOutput(StrictModel):
    path: str
    entries: list[DirectoryEntry]
    truncated: bool = False
    next_cursor: str | None = None


class FileMatch(StrictModel):
    path: str
    line: int
    text: str


class SearchFilesInput(StrictModel):
    pattern: str = Field(min_length=1, max_length=200)
    path: str = "."
    max_results: int = Field(default=100, ge=1, le=1000)


class SearchFilesOutput(StrictModel):
    matches: list[FileMatch]
    truncated: bool = False
    next_cursor: str | None = None


class MakeDirectoryInput(StrictModel):
    path: str = Field(min_length=1)


class MakeDirectoryOutput(StrictModel):
    path: str


class ReadFileTool(BaseTool):
    namespace = "workspace"
    name = "read_file"
    title = "Read a workspace file"
    description = "Read a UTF-8 text file inside the configured workspace."
    when_to_use = "Use when you know the path of a file to inspect."
    when_not_to_use = "Do not use for unknown paths; search or list first."
    category = "workspace"
    tags = ("file", "read", "workspace", "code", "text")
    side_effects = ToolSideEffects.read
    input_model = ReadFileInput
    output_model = ReadFileOutput

    async def run(self, params: ReadFileInput, context: ToolContext) -> ReadFileOutput:
        root = _root(context)
        target = _resolve(root, params.path)
        if not target.is_file():
            raise ToolError("not_a_file", f"Not a file: {params.path}")
        try:
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ToolError("read_failed", str(exc)) from exc
        return ReadFileOutput(
            path=str(target.relative_to(root)),
            content=content,
            bytes=len(content.encode("utf-8")),
        )


class WriteFileTool(BaseTool):
    namespace = "workspace"
    name = "write_file"
    title = "Write a workspace file"
    description = "Write a UTF-8 text file inside the configured workspace."
    when_to_use = "Use when creating or replacing a known file with complete content."
    when_not_to_use = "Do not use for partial edits; read the file and submit the full new content."
    category = "workspace"
    tags = ("file", "write", "workspace", "code", "create")
    side_effects = ToolSideEffects.write
    idempotent = True
    input_model = WriteFileInput
    output_model = WriteFileOutput

    async def run(self, params: WriteFileInput, context: ToolContext) -> WriteFileOutput:
        root = _root(context)
        target = _resolve(root, params.path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(params.content, encoding="utf-8")
        except OSError as exc:
            raise ToolError("write_failed", str(exc)) from exc
        return WriteFileOutput(
            path=str(target.relative_to(root)),
            bytes=len(params.content.encode("utf-8")),
        )


class ListDirectoryTool(BaseTool):
    namespace = "workspace"
    name = "list_directory"
    title = "List a workspace directory"
    description = "List files and directories under a workspace path."
    when_to_use = "Use to discover the structure before reading or searching files."
    when_not_to_use = "Do not use for large recursive scans; use search_files."
    category = "workspace"
    tags = ("file", "list", "directory", "workspace", "tree")
    side_effects = ToolSideEffects.read
    input_model = ListDirectoryInput
    output_model = ListDirectoryOutput

    async def run(self, params: ListDirectoryInput, context: ToolContext) -> ListDirectoryOutput:
        root = _root(context)
        target = _resolve(root, params.path)
        if not target.is_dir():
            raise ToolError("not_a_directory", f"Not a directory: {params.path}")
        entries: list[DirectoryEntry] = []
        try:
            for item in sorted(target.iterdir(), key=lambda p: p.name.lower()):
                if len(entries) >= params.max_results:
                    break
                entries.append(DirectoryEntry(
                    path=str(item.relative_to(root)),
                    type="directory" if item.is_dir() else "file",
                    size=None if item.is_dir() else item.stat().st_size,
                ))
        except OSError as exc:
            raise ToolError("list_failed", str(exc)) from exc
        return ListDirectoryOutput(
            path=str(target.relative_to(root)),
            entries=entries,
            truncated=len(entries) >= params.max_results,
        )


class SearchFilesTool(BaseTool):
    namespace = "workspace"
    name = "search_files"
    title = "Search workspace files"
    description = "Search text file contents for a literal phrase."
    when_to_use = "Use when you know a symbol or phrase but not the file path."
    when_not_to_use = "Do not use for binary files or very large unrelated trees."
    category = "workspace"
    tags = ("file", "search", "grep", "workspace", "code")
    side_effects = ToolSideEffects.read
    timeout_seconds = 45
    input_model = SearchFilesInput
    output_model = SearchFilesOutput

    async def run(self, params: SearchFilesInput, context: ToolContext) -> SearchFilesOutput:
        root = _root(context)
        target = _resolve(root, params.path)
        if not target.is_dir():
            raise ToolError("not_a_directory", f"Not a directory: {params.path}")
        matches: list[FileMatch] = []
        for item in target.rglob("*"):
            if len(matches) >= params.max_results:
                break
            if not item.is_file():
                continue
            try:
                resolved = item.resolve()
                resolved.relative_to(root)
                for line_no, line in enumerate(
                    item.read_text(encoding="utf-8").splitlines(), 1
                ):
                    if params.pattern in line:
                        matches.append(FileMatch(
                            path=str(item.relative_to(root)),
                            line=line_no,
                            text=line[:500],
                        ))
                        if len(matches) >= params.max_results:
                            break
            except (OSError, UnicodeError, ValueError):
                continue
        return SearchFilesOutput(
            matches=matches,
            truncated=len(matches) >= params.max_results,
        )


class MakeDirectoryTool(BaseTool):
    namespace = "workspace"
    name = "make_directory"
    title = "Create a workspace directory"
    description = "Create a directory and any missing parents inside the workspace."
    when_to_use = "Use before writing files into a new project or folder."
    when_not_to_use = "Do not use to create paths outside the workspace."
    category = "workspace"
    tags = ("file", "directory", "mkdir", "workspace")
    side_effects = ToolSideEffects.write
    input_model = MakeDirectoryInput
    output_model = MakeDirectoryOutput

    async def run(self, params: MakeDirectoryInput, context: ToolContext) -> MakeDirectoryOutput:
        root = _root(context)
        target = _resolve(root, params.path)
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ToolError("mkdir_failed", str(exc)) from exc
        return MakeDirectoryOutput(path=str(target.relative_to(root)))


TOOLS = [ReadFileTool, WriteFileTool, ListDirectoryTool, SearchFilesTool, MakeDirectoryTool]
