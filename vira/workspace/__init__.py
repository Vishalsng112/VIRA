"""Shared, user-visible project workspaces.

A workspace is the durable unit: a directory users can open on the host.  An
agent gets an isolated sandbox *attached* to a workspace, and several agents can
attach to the same workspace without sharing a process namespace.
"""
from .service import WorkspaceService, get_service, resolve_workspace

__all__ = ["WorkspaceService", "get_service", "resolve_workspace"]
