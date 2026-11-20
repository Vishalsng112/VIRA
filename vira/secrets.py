"""Small secrets utility: master key, Fernet encryption and payload helpers."""
import base64
import hashlib
import os
import stat
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

PREFIX = "enc:v1:"
DEFAULT_KEY_FILE = Path("data/.vira_master_key")


def _load_key() -> bytes:
    env = os.environ.get("VIRA_MASTER_KEY")
    if env:
        raw = env.encode("utf-8")
        if len(raw) == 44:
            return raw
        return base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
    key_file = Path(os.environ.get("VIRA_MASTER_KEY_FILE", DEFAULT_KEY_FILE))
    if key_file.exists():
        return key_file.read_bytes().strip()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    fd = os.open(str(key_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "wb") as handle:
        handle.write(key)
    return key


class SecretBox:
    def __init__(self, key: Optional[bytes] = None):
        self._fernet = Fernet(key or _load_key())

    def encrypt(self, text: str) -> str:
        if text.startswith(PREFIX):
            return text
        return PREFIX + self._fernet.encrypt(text.encode("utf-8")).decode("ascii")

    def decrypt(self, text: str) -> str:
        if not text.startswith(PREFIX):
            return text
        try:
            return self._fernet.decrypt(text[len(PREFIX):].encode("ascii")).decode("utf-8")
        except InvalidToken:
            return text

    def encrypt_payload(self, payload: Optional[str]) -> Optional[str]:
        return None if payload is None else self.encrypt(payload)

    def decrypt_payload(self, payload: Optional[str]) -> Optional[str]:
        return None if payload is None else self.decrypt(payload)


_box: Optional[SecretBox] = None


def get_secret_box() -> SecretBox:
    global _box
    if _box is None:
        _box = SecretBox()
    return _box


def encrypt_text(text: str) -> str:
    return get_secret_box().encrypt(text)


def decrypt_text(text: str) -> str:
    return get_secret_box().decrypt(text)


def encrypt_payload(payload: Optional[str]) -> Optional[str]:
    return get_secret_box().encrypt_payload(payload)


def decrypt_payload(payload: Optional[str]) -> Optional[str]:
    return get_secret_box().decrypt_payload(payload)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(prog="vira-secrets")
    sub = parser.add_subparsers(dest="cmd", required=True)
    enc = sub.add_parser("encrypt")
    enc.add_argument("value")
    dec = sub.add_parser("decrypt")
    dec.add_argument("value")
    args = parser.parse_args()
    if args.cmd == "encrypt":
        print(encrypt_text(args.value))
    else:
        print(decrypt_text(args.value))


if __name__ == "__main__":
    main()
