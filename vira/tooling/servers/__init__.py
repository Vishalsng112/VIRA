"""Domain tool packs used by the MCP servers."""
from __future__ import annotations

from . import database, runtime, vira_core, web, workspace

DOMAINS = {
    "web": web,
    "runtime": runtime,
    "workspace": workspace,
    "database": database,
    "vira": vira_core,
}


def tools_for(domain: str):
    return DOMAINS[domain].TOOLS


def manifest_for(domain: str):
    return DOMAINS[domain].MANIFEST


def all_tools():
    result = []
    for domain in DOMAINS.values():
        result.extend(domain.TOOLS)
    return result


__all__ = [
    "DOMAINS",
    "all_tools",
    "database",
    "manifest_for",
    "runtime",
    "tools_for",
    "vira_core",
    "web",
    "workspace",
]
