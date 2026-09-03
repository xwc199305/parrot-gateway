from __future__ import annotations

from datetime import datetime
from typing import Protocol


class GatewayKeyRecord(Protocol):
    key_hash: str
    status: str
    expires_at: datetime | None


class GatewayKeyRepository(Protocol):
    async def find_by_prefix(self, prefix: str) -> GatewayKeyRecord | None: ...

    async def touch(self, record: GatewayKeyRecord) -> None: ...
