from __future__ import annotations

import logging
from typing import Dict, Any, Optional

import httpx
import hmac
import hashlib
import base64

from app.core.config import get_settings

_logger = logging.getLogger(__name__)


class QStashPublisher:
    def __init__(self):
        self.s = get_settings()

    async def enqueue(self, job: Dict[str, Any]) -> None:
        """
        Publish a job to QStash to be delivered to our webhook.
        Requires QSTASH_TOKEN and QSTASH_DESTINATION_URL.
        """
        if not self.s.QSTASH_TOKEN or not self.s.QSTASH_DESTINATION_URL:
            raise RuntimeError("QStash requires QSTASH_TOKEN and QSTASH_DESTINATION_URL")

        headers = {
            "Authorization": f"Bearer {self.s.QSTASH_TOKEN}",
            "Content-Type": "application/json",
            # QStash expects this header to know where to forward:
            "Upstash-Forward-Url": self.s.QSTASH_DESTINATION_URL,
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(f"{self.s.QSTASH_URL}/v2/publish", headers=headers, json=job)
            resp.raise_for_status()
            _logger.info("Published job to QStash")

    @staticmethod
    def verify_signature(headers: Dict[str, str], body: bytes) -> bool:
        """
        Strict verification required: this function must validate the signature.
        Implemented per Upstash docs using CURRENT/NEXT signing keys.
        """
        sig_header = headers.get("Upstash-Signature") or ""
        if not sig_header:
            return False

        # Normalize header: allow either "sha256=<b64>" or just "<b64>"
        if sig_header.startswith("sha256="):
            provided = sig_header.split("=", 1)[1]
        else:
            provided = sig_header.strip()

        # Compute HMAC-SHA256(body) with both current and next signing keys (keys are base64 or raw)
        def compute_b64_digest(key_str: Optional[str]) -> Optional[str]:
            if not key_str:
                return None
            try:
                key = base64.b64decode(key_str)
            except Exception:
                key = key_str.encode("utf-8")
            digest = hmac.new(key, body, hashlib.sha256).digest()
            return base64.b64encode(digest).decode("utf-8")

        s = get_settings()
        digests = []
        for k in (s.QSTASH_CURRENT_SIGNING_KEY, s.QSTASH_NEXT_SIGNING_KEY):
            d = compute_b64_digest(k)
            if d:
                digests.append(d)

        # Constant-time comparison against any valid digest
        for d in digests:
            if hmac.compare_digest(provided, d):
                return True

        return False
