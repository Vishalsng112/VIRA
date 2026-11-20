"""Discover Ollama models and the model/context VIRA is configured to use.

Shared by ``vira doctor``, the model-selection API and the first-run guidance so
that "the configured model" and "the installed model" cannot drift apart.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional
from urllib import error, request

DEFAULT_OLLAMA_URL = "http://localhost:11434"


def configured_ollama_url(config: Optional[Dict[str, Any]] = None) -> str:
    """Resolve the Ollama endpoint the way the provider factory does."""
    env_url = os.environ.get("VIRA_OLLAMA_URL")
    if env_url:
        return env_url.rstrip("/")
    for entry in (config or {}).get("llm", {}).get("models", []) or []:
        if entry.get("provider") == "ollama" and entry.get("base_url"):
            return str(entry["base_url"]).rstrip("/")
    return DEFAULT_OLLAMA_URL


def configured_model(config: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Return the model VIRA will ask Ollama to run."""
    env_model = os.environ.get("VIRA_OLLAMA_MODEL")
    if env_model:
        return env_model
    llm = (config or {}).get("llm", {}) or {}
    default = llm.get("default_model")
    for entry in llm.get("models", []) or []:
        if entry.get("provider") == "ollama":
            return os.environ.get("VIRA_OLLAMA_MODEL") or entry.get("model") or default
    return default


def configured_context(config: Optional[Dict[str, Any]] = None) -> Optional[int]:
    """Return ``num_ctx`` for the configured Ollama model, if set."""
    for entry in (config or {}).get("llm", {}).get("models", []) or []:
        if entry.get("provider") == "ollama" and entry.get("num_ctx"):
            try:
                return int(entry["num_ctx"])
            except (TypeError, ValueError):
                return None
    return None


def _get_json(url: str, timeout: float = 3.0) -> Any:
    req = request.Request(url, headers={"Accept": "application/json"})
    with request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def list_ollama_models(base_url: Optional[str] = None, timeout: float = 3.0) -> List[Dict[str, Any]]:
    """Return installed Ollama models. Raises on an unreachable endpoint."""
    base = (base_url or DEFAULT_OLLAMA_URL).rstrip("/")
    data = _get_json(f"{base}/api/tags", timeout=timeout)
    models = []
    for item in data.get("models", []) or []:
        name = item.get("name") or item.get("model")
        if not name:
            continue
        details = item.get("details") or {}
        models.append({
            "name": name,
            "size": item.get("size"),
            "parameter_size": details.get("parameter_size"),
            "quantization": details.get("quantization_level"),
            "family": details.get("family"),
            "modified_at": item.get("modified_at"),
        })
    models.sort(key=lambda item: item["name"])
    return models


def show_ollama_model(model: str, base_url: Optional[str] = None,
                      timeout: float = 3.0) -> Dict[str, Any]:
    """Return metadata for one installed model through ``/api/show``."""
    base = (base_url or DEFAULT_OLLAMA_URL).rstrip("/")
    req = request.Request(
        f"{base}/api/show",
        data=json.dumps({"model": model}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def model_context_length(show: Dict[str, Any]) -> Optional[int]:
    """Extract the trained context length from an ``/api/show`` response."""
    info = show.get("model_info") or {}
    for key, value in info.items():
        if key.endswith("context_length") and isinstance(value, int) and value > 0:
            return value
    parameters = show.get("parameters")
    if isinstance(parameters, str):
        for line in parameters.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0] == "num_ctx":
                try:
                    return int(parts[1])
                except ValueError:
                    return None
    return None


def ollama_reachable(base_url: Optional[str] = None, timeout: float = 2.0) -> bool:
    try:
        list_ollama_models(base_url, timeout=timeout)
        return True
    except (error.URLError, error.HTTPError, OSError, ValueError, json.JSONDecodeError):
        return False
