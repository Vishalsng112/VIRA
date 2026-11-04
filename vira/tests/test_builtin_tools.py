import asyncio
import json

from vira.tools.builtin import FilesystemTool, GitTool, ShellTool, UtilityTool, create_builtin_tools
from vira.tools.registry import ToolRegistry


def payload(result):
    return json.loads(result.content[0].text)


def test_builtin_pack_is_discoverable():
    names = [tool.name for tool in create_builtin_tools(".")]
    assert names == ["filesystem", "shell", "git", "utility", "web"]
    registry = ToolRegistry()
    registry.register_builtins(".")
    assert registry.list() == names
    metadata = registry.metadata()
    assert metadata[0]["name"] == "filesystem"
    assert metadata[0]["provider"] == "local"


def test_registry_replacing_a_tool_does_not_create_duplicate_aliases():
    registry = ToolRegistry()
    registry.register(UtilityTool())
    registry.register(UtilityTool())
    assert registry.list() == ["utility"]
    assert registry.get("utility") is not None


def test_filesystem_is_root_contained(tmp_path):
    tool = FilesystemTool(tmp_path)
    written = asyncio.run(tool.execute("write", path="src/a.txt", content="hello"))
    assert payload(written)["path"] == "src/a.txt"
    read = asyncio.run(tool.execute("read", path="src/a.txt"))
    assert payload(read)["content"] == "hello"
    escaped = asyncio.run(tool.execute("read", path="../outside.txt"))
    assert escaped.isError


def test_filesystem_search_ignores_external_symlinks(tmp_path):
    outside = tmp_path.parent / "outside-tool-test.txt"
    outside.write_text("secret", encoding="utf-8")
    (tmp_path / "linked.txt").symlink_to(outside)
    result = asyncio.run(FilesystemTool(tmp_path).execute("search", pattern="secret"))
    assert payload(result)["matches"] == []
    outside.unlink()


def test_shell_rejects_unsafe_commands(tmp_path):
    tool = ShellTool(tmp_path)
    rejected = asyncio.run(tool.execute("echo hello"))
    assert rejected.isError
    chained = asyncio.run(tool.execute("pwd; whoami"))
    assert chained.isError


def test_git_tool_uses_read_only_operations(tmp_path):
    result = asyncio.run(GitTool(tmp_path).execute("status"))
    assert result.isError or payload(result)["command"][:2] == ["git", "status"]


def test_utility_calculates_without_eval():
    result = asyncio.run(UtilityTool().execute("calculate", expression="2 + 3 * 4"))
    assert payload(result)["result"] == 14
    rejected = asyncio.run(UtilityTool().execute("calculate", expression="__import__('os')"))
    assert rejected.isError
