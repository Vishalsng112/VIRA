"""Minimal S3-compatible backend using SigV4 and aiohttp.

Works with AWS S3, MinIO, Cloudflare R2, Backblaze B2's S3 API and similar
services.  No third-party SDK is required.
"""
import hashlib
import hmac
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote, urlparse

import aiohttp

from .base import ObjectBackend


def _sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


class S3ObjectBackend(ObjectBackend):
    name = "s3"

    def __init__(self, bucket: str, access_key: str, secret_key: str,
                 region: str = "us-east-1", endpoint: str = "",
                 prefix: str = "", path_style: bool = True):
        if not bucket or not access_key or not secret_key:
            raise ValueError("S3 bucket, access key and secret key are required")
        self.bucket = bucket
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region or "us-east-1"
        self.endpoint = (endpoint or "").rstrip("/")
        self.prefix = prefix.strip("/")
        self.path_style = path_style

    def _url(self, key: str) -> str:
        key = f"{self.prefix}/{key}".lstrip("/")
        if self.endpoint:
            if self.path_style:
                return f"{self.endpoint}/{self.bucket}/{quote(key, safe='/')}"
            host = urlparse(self.endpoint).netloc
            return f"{self.endpoint.replace(host, f'{self.bucket}.{host}', 1)}/{quote(key, safe='/')}"
        return f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{quote(key, safe='/')}"

    def _headers(self, method: str, url: str, payload: bytes) -> dict:
        parsed = urlparse(url)
        now = datetime.now(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(payload).hexdigest()
        canonical_headers = (
            f"host:{parsed.netloc}\n"
            f"x-amz-content-sha256:{payload_hash}\n"
            f"x-amz-date:{amz_date}\n"
        )
        signed_headers = "host;x-amz-content-sha256;x-amz-date"
        canonical_request = "\n".join([
            method, parsed.path or "/", parsed.query, canonical_headers,
            signed_headers, payload_hash,
        ])
        scope = f"{date_stamp}/{self.region}/s3/aws4_request"
        string_to_sign = "\n".join([
            "AWS4-HMAC-SHA256", amz_date, scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ])
        signing_key = _sign(
            _sign(_sign(_sign(("AWS4" + self.secret_key).encode("utf-8"), date_stamp),
                       self.region), "s3"), "aws4_request")
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"),
                             hashlib.sha256).hexdigest()
        return {
            "Host": parsed.netloc,
            "x-amz-date": amz_date,
            "x-amz-content-sha256": payload_hash,
            "Authorization": (
                f"AWS4-HMAC-SHA256 Credential={self.access_key}/{scope}, "
                f"SignedHeaders={signed_headers}, Signature={signature}"
            ),
        }

    async def _request(self, method: str, url: str, payload: bytes = b"") -> bytes:
        headers = self._headers(method, url, payload)
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, data=payload or None, headers=headers) as response:
                body = await response.read()
                if response.status >= 300:
                    raise RuntimeError(
                        f"S3 {method} failed with HTTP {response.status}: "
                        f"{body[:300].decode('utf-8', 'replace')}"
                    )
                return body

    async def put(self, key: str, content: bytes, content_type: str) -> str:
        await self._request("PUT", self._url(key), content)
        return f"{self.prefix + '/' if self.prefix else ''}{key}"

    async def get(self, storage_key: str) -> bytes:
        return await self._request("GET", self._url(storage_key))

    async def delete(self, storage_key: str) -> None:
        await self._request("DELETE", self._url(storage_key))
