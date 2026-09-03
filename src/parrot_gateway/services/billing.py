from __future__ import annotations

import math
import uuid
from collections.abc import Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from parrot_gateway.domain.errors import BillingError
from parrot_gateway.domain.models import IRChatRequest, IRChatResponse
from parrot_gateway.services.tokenizers import TokenizerRegistry


class BillingService:
    """Two-phase token billing backed by the PostgreSQL billing tables."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        tokenizer_registry: TokenizerRegistry | None = None,
    ) -> None:
        self._sessions = session_factory
        self._tokenizers = tokenizer_registry or TokenizerRegistry()

    async def reserve(
        self,
        request: IRChatRequest,
        tenant_id: str,
        *,
        user_id: str | None = None,
        gateway_key_id: str | None = None,
        provider: str,
    ) -> str:
        estimated_input = await self._tokenizers.count_messages(
            provider, request.model, request.messages
        )
        estimated_output = request.max_completion_tokens or request.max_tokens or 4096
        async with self._sessions() as session:
            await session.execute(
                text("select set_config('app.tenant_id', :tenant, true)"), {"tenant": tenant_id}
            )
            price = (
                (
                    await session.execute(
                        text("""
                SELECT * FROM billing_prices
                WHERE provider=:provider AND active
                  AND effective_from <= now()
                  AND (effective_to IS NULL OR effective_to > now())
                  AND (model=:model OR (match_type='prefix' AND :model LIKE model || '%') OR match_type='default')
                ORDER BY CASE WHEN model=:model AND match_type='exact' THEN 3 WHEN match_type='prefix' THEN 2 ELSE 1 END DESC, effective_from DESC
                LIMIT 1
            """),
                        {"provider": provider, "model": request.model},
                    )
                )
                .mappings()
                .first()
            )
            if price is None:
                raise BillingError(f"No billing price configured for {provider}/{request.model}", 503)
            amount = _cost(estimated_input, estimated_output, price)
            provider_key = (
                await session.execute(
                    text("""SELECT id FROM provider_api_keys
                           WHERE tenant_id=:tenant AND provider=:provider AND status='active'
                           ORDER BY created_at DESC LIMIT 1"""),
                    {"tenant": tenant_id, "provider": provider},
                )
            ).mappings().first()
            provider_key_id = provider_key["id"] if provider_key else None
            quota_month = None
            if provider_key_id:
                quota_month = (
                    await session.execute(
                        text("""SELECT month_start FROM billing_provider_monthly_quotas
                            WHERE provider_api_key_id=:key
                              AND month_start=date_trunc('month', current_date)::date"""),
                        {"key": provider_key_id},
                    )
                ).scalar_one_or_none()
                if quota_month is not None:
                    reserved = (
                        await session.execute(
                            text("""UPDATE billing_provider_monthly_quotas
                                SET reserved_micro=reserved_micro+:amount, updated_at=now()
                                WHERE provider_api_key_id=:key
                                  AND month_start=:month
                                  AND reserved_micro + consumed_micro + :amount <= quota_micro
                                RETURNING id"""),
                            {"key": provider_key_id, "month": quota_month, "amount": amount},
                        )
                    ).first()
                    if reserved is None:
                        raise BillingError("Monthly Provider API key quota exceeded", 429)
            updated = await session.execute(
                text("""
                UPDATE billing_accounts
                SET balance_micro = balance_micro - :amount, updated_at = now()
                WHERE tenant_id=:tenant AND status='active'
                  AND balance_micro + credit_limit_micro >= :amount
                RETURNING id
            """),
                {"tenant": tenant_id, "amount": amount},
            )
            account = updated.first()
            if account is None:
                raise BillingError("Insufficient billing balance")
            record_id = str(uuid.uuid4())
            await session.execute(
                text("""
                INSERT INTO billing_usage_records (
                    id, request_id, tenant_id, user_id, gateway_api_key_id, provider, model,
                    provider_api_key_id,
                    estimated_price_id, estimated_input_tokens, estimated_output_tokens,
                    estimated_amount_micro, reserved_amount_micro, reserved_at, status,
                    estimated_input_price_micro_per_million,
                    estimated_output_price_micro_per_million,
                    estimated_cached_input_price_micro_per_million,
                    quota_month_start,
                    is_stream, user_multiplier_snapshot, channel_multiplier_snapshot,
                    model_multiplier_snapshot, combined_multiplier_snapshot
                ) VALUES (:id, :request_id, :tenant, :user_id, :key, :provider, :model,
                    :provider_key, :price, :input_tokens, :output_tokens, :amount, :amount, now(), 'reserved',
                    :input_price, :output_price, :cached_input_price,
                    :quota_month,
                    :is_stream, 1000, 1000, :model_multiplier, :combined_multiplier)
            """),
                {
                    "id": record_id,
                    "request_id": str(uuid.uuid4()),
                    "tenant": tenant_id,
                    "user_id": user_id,
                    "key": gateway_key_id,
                    "provider_key": provider_key_id,
                    "provider": provider,
                    "model": request.model,
                    "price": price["id"],
                    "input_tokens": estimated_input,
                    "output_tokens": estimated_output,
                    "amount": amount,
                    "input_price": price["input_price_micro_per_million"],
                    "output_price": price["output_price_micro_per_million"],
                    "cached_input_price": price.get("cached_input_price_micro_per_million", 0),
                    "quota_month": quota_month,
                    "is_stream": request.stream,
                    "model_multiplier": price["model_multiplier"],
                    "combined_multiplier": price["model_multiplier"] * 1000 * 1000,
                },
            )
            await session.commit()
            return record_id

    async def finalize(
        self,
        record_id: str,
        response: IRChatResponse | None = None,
        *,
        failed: bool = False,
        tenant_id: str | None = None,
    ) -> None:
        usage: Mapping[str, object] = response.usage if response and response.usage else {}
        async with self._sessions() as session:
            if tenant_id:
                await session.execute(
                    text("select set_config('app.tenant_id', :tenant, true)"),
                    {"tenant": tenant_id},
                )
            row = (
                (
                    await session.execute(
                        text("SELECT * FROM billing_usage_records WHERE id=:id FOR UPDATE"),
                        {"id": record_id},
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return
            quota_params = {
                "key": row.get("provider_api_key_id"),
                "month": row.get("quota_month_start"),
            }
            if failed:
                await session.execute(
                    text(
                        """UPDATE billing_accounts SET balance_micro=balance_micro+:amount, updated_at=now() WHERE tenant_id=:tenant"""
                    ),
                    {"amount": row["reserved_amount_micro"], "tenant": row["tenant_id"]},
                )
                await session.execute(
                    text(
                        """UPDATE billing_usage_records SET status='refunded', refund_at=now(), released_amount_micro=reserved_amount_micro, reconciliation_status='adjusted' WHERE id=:id"""
                    ),
                    {"id": record_id},
                )
                if quota_params["key"] and quota_params["month"]:
                    await session.execute(
                        text("""UPDATE billing_provider_monthly_quotas
                            SET reserved_micro=GREATEST(0, reserved_micro-:amount), updated_at=now()
                            WHERE provider_api_key_id=:key AND month_start=:month"""),
                        {**quota_params, "amount": row["reserved_amount_micro"]},
                    )
            elif not usage:
                if quota_params["key"] and quota_params["month"]:
                    await session.execute(
                        text("""UPDATE billing_provider_monthly_quotas
                            SET reserved_micro=GREATEST(0, reserved_micro-:amount),
                                consumed_micro=consumed_micro+:amount, updated_at=now()
                            WHERE provider_api_key_id=:key AND month_start=:month"""),
                        {**quota_params, "amount": row["reserved_amount_micro"]},
                    )
                await session.execute(
                    text("""UPDATE billing_usage_records
                        SET actual_input_tokens=estimated_input_tokens,
                            actual_output_tokens=estimated_output_tokens,
                            actual_amount_micro=reserved_amount_micro,
                            balance_delta_micro=0,
                            reconciliation_delta_micro=0,
                            token_source='estimated', usage_available=false,
                            status='finalized', finalized_at=now(),
                            reconciliation_status='matched'
                        WHERE id=:id"""),
                    {"id": record_id},
                )
            else:
                actual_input = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
                actual_output = int(
                    usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
                )
                actual = _cost(actual_input, actual_output, row)
                delta = row["reserved_amount_micro"] - actual
                if quota_params["key"] and quota_params["month"]:
                    await session.execute(
                        text("""UPDATE billing_provider_monthly_quotas
                            SET reserved_micro=GREATEST(0, reserved_micro-:reserved),
                                consumed_micro=consumed_micro+:actual, updated_at=now()
                            WHERE provider_api_key_id=:key AND month_start=:month"""),
                        {**quota_params, "reserved": row["reserved_amount_micro"], "actual": actual},
                    )
                await session.execute(
                    text(
                        "UPDATE billing_accounts SET balance_micro=balance_micro+CAST(:delta AS BIGINT), updated_at=now() WHERE tenant_id=:tenant"
                    ),
                    {"delta": delta, "tenant": row["tenant_id"]},
                )
                await session.execute(
                    text(
                        """UPDATE billing_usage_records
                        SET actual_input_tokens=:input,
                            actual_output_tokens=:output,
                            actual_amount_micro=CAST(:actual AS BIGINT),
                            balance_delta_micro=CAST(:delta AS BIGINT),
                            reconciliation_delta_micro=CAST(:delta AS BIGINT),
                            token_source='provider',
                            usage_available=true,
                            status='finalized',
                            finalized_at=now(),
                            reconciliation_status=CASE
                                WHEN CAST(:delta AS BIGINT) = CAST(0 AS BIGINT) THEN 'matched'
                                ELSE 'adjusted'
                            END
                        WHERE id=:id"""
                    ),
                    {
                        "id": record_id,
                        "input": actual_input,
                        "output": actual_output,
                        "actual": actual,
                        "delta": delta,
                    },
                )
            await session.commit()


def _estimate_tokens(messages: list[dict[str, object]]) -> int:
    return max(
        1,
        math.ceil(
            sum(len(str(m.get("content", ""))) + len(str(m.get("role", ""))) for m in messages) / 4
        ),
    )


def _cost(input_tokens: int, output_tokens: int, price: Mapping[str, object]) -> int:
    input_price = price.get(
        "estimated_input_price_micro_per_million",
        price.get("input_price_micro_per_million", 0),
    )
    output_price = price.get(
        "estimated_output_price_micro_per_million",
        price.get("output_price_micro_per_million", 0),
    )
    return math.ceil(
        (
            input_tokens * int(input_price)
            + output_tokens * int(output_price)
        )
        / 1_000_000
    )
