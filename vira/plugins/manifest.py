"""Plugin manifest parsing and validation.

A plugin directory contains one of::

    vira-plugin.json
    plugin.json
    vira-plugin.toml

Example ``vira-plugin.json``::

    {
      "id": "acme.weather",
      "name": "Weather Tools",
      "version": "1.0.0",
      "api_version": "1",
      "entrypoint": "plugin.py:WeatherPlugin",
      "permissions": ["tools.register", "http.routes", "storage"],
      "config": {"units": "metric"}
    }
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

PLUGIN_API_VERSION = "1"
MANIFEST_NAMES = ("vira-plugin.json", "plugin.json", "vira-plugin.toml")
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{1,80}$")


class ManifestError(ValueError):
    pass


@dataclass
class PluginManifest:
    id: str
    name: str
    version: str
    api_version: str = PLUGIN_API_VERSION
    description: str = ""
    author: str = ""
    license: str = ""
    homepage: str = ""
    entrypoint: str = ""
    permissions: List[str] = field(default_factory=list)
    requires: Dict[str, str] = field(default_factory=dict)
    config: Dict[str, Any] = field(default_factory=dict)
    categories: List[str] = field(default_factory=list)
    ui: Dict[str, Any] = field(default_factory=dict)
    legacy: bool = False
    directory: str = ""

    def validate(self) -> "PluginManifest":
        if not _ID.match(self.id or ""):
            raise ManifestError(
                "plugin id must be 2-81 lowercase letters, digits, dots, dashes or underscores"
            )
        if self.api_version != PLUGIN_API_VERSION:
            raise ManifestError(
                f"unsupported plugin api_version {self.api_version!r}; "
                f"this server supports {PLUGIN_API_VERSION!r}"
            )
        if not self.name or not self.version:
            raise ManifestError("name and version are required")
        if not self.legacy and not self.entrypoint:
            raise ManifestError("entrypoint is required, for example plugin.py:Plugin")
        return self

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "api_version": self.api_version,
            "description": self.description,
            "author": self.author,
            "license": self.license,
            "homepage": self.homepage,
            "entrypoint": self.entrypoint,
            "permissions": list(self.permissions),
            "requires": dict(self.requires),
            "config": dict(self.config),
            "categories": list(self.categories),
            "ui": dict(self.ui),
            "directory": self.directory,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], directory: str = "") -> "PluginManifest":
        permissions = data.get("permissions") or []
        categories = data.get("categories") or data.get("tags") or []
        return cls(
            id=str(data.get("id") or "").strip().lower(),
            name=str(data.get("name") or "").strip(),
            version=str(data.get("version") or "").strip(),
            api_version=str(data.get("api_version") or PLUGIN_API_VERSION),
            description=" ".join(str(data.get("description") or "").split()),
            author=str(data.get("author") or ""),
            license=str(data.get("license") or ""),
            homepage=str(data.get("homepage") or ""),
            entrypoint=str(data.get("entrypoint") or ""),
            permissions=[str(item) for item in permissions if str(item).strip()],
            requires={str(k): str(v) for k, v in (data.get("requires") or {}).items()},
            config=dict(data.get("config") or {}),
            categories=[str(item) for item in categories if str(item).strip()],
            ui=dict(data.get("ui") or {}),
            directory=directory,
        ).validate()

    @classmethod
    def from_directory(cls, directory: Path) -> "PluginManifest":
        for name in MANIFEST_NAMES:
            path = directory / name
            if not path.is_file():
                continue
            if path.suffix == ".toml":
                import tomllib
                data = tomllib.loads(path.read_text(encoding="utf-8"))
            else:
                data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ManifestError(f"{name} must contain an object")
            return cls.from_dict(data, str(directory))
        raise ManifestError(f"no manifest found in {directory}")

    @classmethod
    def legacy_python(cls, path: Path) -> "PluginManifest":
        return cls(
            id=path.stem.lower().replace("_", "-"),
            name=path.stem.replace("_", " ").title(),
            version="0.0.0",
            description="Legacy single-file plugin",
            entrypoint=f"{path.name}:auto",
            permissions=[],
            legacy=True,
            directory=str(path.parent),
        ).validate()
