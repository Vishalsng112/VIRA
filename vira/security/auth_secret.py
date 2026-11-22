"""Persistent, non-committed session secret handling."""
import os
import secrets
from pathlib import Path

WEAK_SECRETS = {
    "",
    "change-this-to-a-random-secret-key-in-production",
    "default-secret-change-me",
}


def is_weak_secret(value: object) -> bool:
    text = str(value or "").strip()
    return text in WEAK_SECRETS or len(text) < 32


def resolve_auth_secret(
    config_manager,
    data_dir: str | Path | None = None,
) -> tuple[str, str]:
    """Return a strong session secret and where it came from.

    Precedence: explicit environment variable, strong config value, runtime
    secret file, newly generated secret file. The secret is never written to
    config.yaml or to git.
    """
    for name in ("VIRA_AUTH_SECRET", "VIRA_AUTH_SECRET_KEY"):
        value = os.getenv(name, "").strip()
        if value and not is_weak_secret(value):
            config_manager.set("auth.secret_key", value)
            return value, f"environment:{name}"

    current = config_manager.get("auth.secret_key", "")
    if current and not is_weak_secret(current):
        return str(current).strip(), "config"

    root = Path(data_dir or os.getenv("VIRA_DATA_DIR", "./data"))
    path = root / "auth_secret"
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8").strip()
        except OSError:
            existing = ""
        if not is_weak_secret(existing):
            try:
                path.chmod(0o600)
            except OSError:
                pass
            config_manager.set("auth.secret_key", existing)
            return existing, "file"

    generated = secrets.token_urlsafe(48)
    try:
        root.mkdir(parents=True, exist_ok=True)
        path.write_text(generated, encoding="utf-8")
        path.chmod(0o600)
    except OSError:
        config_manager.set("auth.secret_key", generated)
        return generated, "ephemeral"
    config_manager.set("auth.secret_key", generated)
    return generated, "generated"
