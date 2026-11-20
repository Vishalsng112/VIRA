"""Plugins package: stable extension SDK plus the manager implementation."""
from .api import Plugin, PluginContext, PermissionDenied
from .manifest import PLUGIN_API_VERSION, PluginManifest, ManifestError

__all__ = [
    "Plugin", "PluginContext", "PermissionDenied",
    "PluginManifest", "ManifestError", "PLUGIN_API_VERSION",
]
