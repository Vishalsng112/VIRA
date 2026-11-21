"""Firebase Cloud Messaging HTTP v1 sender.

Uses a service-account JSON file and a cached OAuth2 access token. No Google
SDK is required: the JWT assertion is signed with ``cryptography``, which VIRA
already depends on. FCM delivers to Android and, when APNs is configured in the
Firebase project, to iOS/macOS.
"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from loguru import logger

SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
TOKEN_URI = "https://oauth2.googleapis.com/token"


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _post(url: str, data: bytes, headers: Dict[str, str],
          timeout: float = 10) -> Optional[Dict[str, Any]]:
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=max(1, timeout)) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        logger.warning("FCM request failed: {}", exc)
        return None


class FCMSender:
    def __init__(self, service_account_file: str, project_id: Optional[str] = None,
                 *, timeout: float = 10):
        with open(service_account_file, encoding="utf-8") as handle:
            self.account = json.load(handle)
        self.project_id = (project_id or self.account.get("project_id") or "").strip()
        if not self.project_id:
            raise ValueError("FCM project_id is required")
        self.client_email = self.account["client_email"]
        self.token_uri = self.account.get("token_uri") or TOKEN_URI
        self.private_key = serialization.load_pem_private_key(
            self.account["private_key"].encode("utf-8"), password=None)
        self.timeout = timeout
        self._token: Optional[str] = None
        self._expires_at = 0.0

    def _access_token(self) -> Optional[str]:
        now = int(time.time())
        if self._token and now < self._expires_at - 60:
            return self._token
        header = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        claims = _b64(json.dumps({
            "iss": self.client_email,
            "scope": SCOPE,
            "aud": self.token_uri,
            "iat": now,
            "exp": now + 3600,
        }).encode())
        signing_input = f"{header}.{claims}".encode("ascii")
        signature = self.private_key.sign(
            signing_input, padding.PKCS1v15(), hashes.SHA256())
        assertion = f"{header}.{claims}.{_b64(signature)}"
        body = urllib.parse.urlencode({
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        }).encode("utf-8")
        data = _post(
            self.token_uri, body,
            {"Content-Type": "application/x-www-form-urlencoded"},
            self.timeout,
        )
        if not data or not data.get("access_token"):
            return None
        self._token = str(data["access_token"])
        self._expires_at = now + int(data.get("expires_in", 3600))
        return self._token

    def send(self, token: str, title: str, body: str,
             data: Optional[Dict[str, Any]] = None) -> bool:
        access = self._access_token()
        if not access:
            return False
        payload = {
            "message": {
                "token": token,
                "notification": {"title": title[:200], "body": body[:4000]},
                "data": {str(k): str(v) for k, v in (data or {}).items()},
            }
        }
        url = (f"https://fcm.googleapis.com/v1/projects/"
               f"{urllib.parse.quote(self.project_id)}/messages:send")
        result = _post(
            url,
            json.dumps(payload).encode("utf-8"),
            {"Authorization": f"Bearer {access}", "Content-Type": "application/json"},
            self.timeout,
        )
        return result is not None

    def send_many(self, tokens: Iterable[str], title: str, body: str,
                  data: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
        sent = failed = 0
        for token in tokens:
            if self.send(token, title, body, data):
                sent += 1
            else:
                failed += 1
        return {"sent": sent, "failed": failed}
