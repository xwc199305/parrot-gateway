from __future__ import annotations

from datetime import datetime

from sqlalchemy import BIGINT, JSON, DateTime, Integer, String, Uuid, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class GatewayApiKey(Base):
    __tablename__ = "gateway_api_keys"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    key_prefix: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    tenant_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), index=True)
    user_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    name: Mapped[str] = mapped_column(String(128))
    scopes: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["chat.completions"])
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProviderApiKey(Base):
    __tablename__ = "provider_api_keys"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), index=True)
    user_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    api_key: Mapped[str] = mapped_column(String(512))
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    key_hint: Mapped[str | None] = mapped_column(String(16), nullable=True)
    secret_ciphertext: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    secret_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # ``metadata`` is reserved by SQLAlchemy's Declarative API. Keep the
    # database column name while exposing a safe Python attribute.
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class BillingPrice(Base):
    __tablename__ = "billing_prices"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(128))
    match_type: Mapped[str] = mapped_column(String(16))
    currency: Mapped[str] = mapped_column(String(3))
    input_price_micro_per_million: Mapped[int] = mapped_column(BIGINT)
    output_price_micro_per_million: Mapped[int] = mapped_column(BIGINT)
    cached_input_price_micro_per_million: Mapped[int] = mapped_column(BIGINT)
    model_multiplier: Mapped[int] = mapped_column(Integer, default=1000)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(default=True)


class BillingAccount(Base):
    __tablename__ = "billing_accounts"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), unique=True)
    currency: Mapped[str] = mapped_column(String(3))
    balance_micro: Mapped[int] = mapped_column(BIGINT, default=0)
    credit_limit_micro: Mapped[int] = mapped_column(BIGINT, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active")


class SqlGatewayKeyRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def find_by_prefix(self, prefix: str) -> GatewayApiKey | None:
        async with self._session_factory() as session:
            await session.execute(
                text("select set_config('app.key_lookup_prefix', :prefix, true)"),
                {"prefix": prefix},
            )
            statement = select(GatewayApiKey).where(GatewayApiKey.key_prefix == prefix)
            return await session.scalar(statement)

    async def touch(self, record: GatewayApiKey) -> None:
        from datetime import UTC, datetime

        async with self._session_factory() as session:
            await session.execute(
                text("select set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": record.tenant_id},
            )
            await session.execute(
                update(GatewayApiKey)
                .where(GatewayApiKey.id == record.id)
                .values(last_used_at=datetime.now(UTC))
            )
            await session.commit()

    async def find_for_tenant(self, tenant_id: str, prefix: str) -> GatewayApiKey | None:
        """Tenant-scoped lookup used by management and authorization code."""
        async with self._session_factory() as session:
            await session.execute(
                text("select set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": tenant_id},
            )
            statement = select(GatewayApiKey).where(
                GatewayApiKey.tenant_id == tenant_id,
                GatewayApiKey.key_prefix == prefix,
            )
            return await session.scalar(statement)

    async def list_for_tenant(self, tenant_id: str) -> list[GatewayApiKey]:
        """Return only keys visible to the requested tenant."""
        async with self._session_factory() as session:
            await session.execute(
                text("select set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": tenant_id},
            )
            statement = select(GatewayApiKey).where(GatewayApiKey.tenant_id == tenant_id)
            return list((await session.scalars(statement)).all())

    async def get_provider_key(self, provider: str, tenant_id: str) -> str | None:
        async with self._session_factory() as session:
            await session.execute(
                text("select set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": tenant_id},
            )
            statement = select(ProviderApiKey).where(
                ProviderApiKey.provider == provider,
                ProviderApiKey.tenant_id == tenant_id,
                ProviderApiKey.status == "active",
            )
            record = await session.scalar(statement)
            return record.api_key if record else None

    async def get_any_provider_key(self, provider: str) -> str | None:
        """Bootstrap lookup for single-tenant deployments."""
        async with self._session_factory() as session:
            statement = select(ProviderApiKey).where(
                ProviderApiKey.provider == provider,
                ProviderApiKey.status == "active",
            )
            record = await session.scalar(statement)
            return record.api_key if record else None


def create_session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    return async_sessionmaker(engine, expire_on_commit=False)
