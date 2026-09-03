from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime

from parrot_gateway.domain.auth import GatewayKeyRepository


class GatewayAuthService:
    """Authenticate client keys without exposing provider credentials."""

    def __init__(
        self,
        *,
        static_key: str | None = None,
        repository: GatewayKeyRepository | None = None,
        pepper: str = "",
    ) -> None:
        self._static_key = static_key
        self._repository = repository
        self._pepper = pepper.encode()

    @property
    def enabled(self) -> bool:
        return self._static_key is not None or self._repository is not None

    async def authenticate(self, authorization: str | None):
        # Authentication is intentionally disabled when no credential backend
        # is configured, preserving local development behavior.
        if self._static_key is None and self._repository is None:
            return None
        if not authorization or not authorization.startswith("Bearer "):
            return None
        token = authorization.removeprefix("Bearer ").strip()
        if self._static_key is not None:
            return None if not hmac.compare_digest(token, self._static_key) else "static"
        if self._repository is None:
            return None
        # The prefix may itself contain underscores (for example
        # ``shawn_20260830_<secret>``), so split at the final separator.
        prefix, _, secret = token.rpartition("_")
        if not secret or not prefix:
            return None
        record = await self._repository.find_by_prefix(prefix)
        if record is None or record.status != "active":
            return None
        if record.expires_at and record.expires_at <= datetime.now(UTC):
            return None
        expected = hash_gateway_key(token, self._pepper)
        valid = hmac.compare_digest(expected, record.key_hash)
        if valid:
            await self._repository.touch(record)
        return record if valid else None

    async def verify(self, authorization: str | None) -> bool:
        return await self.authenticate(authorization) is not None


def hash_gateway_key(key: str, pepper: bytes | str = b"") -> str:
    if isinstance(pepper, str):
        pepper = pepper.encode()
    return hmac.new(pepper, key.encode(), hashlib.sha256).hexdigest()
