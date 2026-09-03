-- Upgrade an existing database to the current billing/reconciliation schema.
-- Run after schema.sql's original billing tables exist.
\set ON_ERROR_STOP on

BEGIN;

ALTER TABLE billing_prices
    ADD COLUMN IF NOT EXISTS model_multiplier INTEGER NOT NULL DEFAULT 1000;
ALTER TABLE billing_prices
    DROP CONSTRAINT IF EXISTS billing_prices_model_multiplier_check;
ALTER TABLE billing_prices
    ADD CONSTRAINT billing_prices_model_multiplier_check
    CHECK (model_multiplier BETWEEN 1 AND 10000);

ALTER TABLE billing_usage_records
    ADD COLUMN IF NOT EXISTS trace_id UUID,
    ADD COLUMN IF NOT EXISTS estimated_price_id UUID REFERENCES billing_prices(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS estimated_input_tokens INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS estimated_output_tokens INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS estimated_cached_input_tokens INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS estimated_amount_micro BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS estimated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS actual_input_tokens INTEGER,
    ADD COLUMN IF NOT EXISTS actual_output_tokens INTEGER,
    ADD COLUMN IF NOT EXISTS actual_cached_input_tokens INTEGER,
    ADD COLUMN IF NOT EXISTS estimated_input_price_micro_per_million BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS estimated_output_price_micro_per_million BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS estimated_cached_input_price_micro_per_million BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS actual_price_id UUID REFERENCES billing_prices(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS actual_input_price_micro_per_million BIGINT,
    ADD COLUMN IF NOT EXISTS actual_output_price_micro_per_million BIGINT,
    ADD COLUMN IF NOT EXISTS actual_cached_input_price_micro_per_million BIGINT,
    ADD COLUMN IF NOT EXISTS actual_amount_micro BIGINT,
    ADD COLUMN IF NOT EXISTS reconciliation_status VARCHAR(16) NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS reconciliation_delta_micro BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS reconciled_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS reserved_amount_micro BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS reserved_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS token_source VARCHAR(16) NOT NULL DEFAULT 'estimated',
    ADD COLUMN IF NOT EXISTS usage_available BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS usage_raw JSONB,
    ADD COLUMN IF NOT EXISTS user_multiplier_snapshot INTEGER NOT NULL DEFAULT 1000,
    ADD COLUMN IF NOT EXISTS channel_multiplier_snapshot INTEGER NOT NULL DEFAULT 1000,
    ADD COLUMN IF NOT EXISTS model_multiplier_snapshot INTEGER NOT NULL DEFAULT 1000,
    ADD COLUMN IF NOT EXISTS combined_multiplier_snapshot BIGINT NOT NULL DEFAULT 1000000000,
    ADD COLUMN IF NOT EXISTS released_amount_micro BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS balance_delta_micro BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS is_stream BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS finalized_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS refund_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS error_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS error_message TEXT;

ALTER TABLE provider_api_keys
    DROP COLUMN IF EXISTS monthly_quota_micro,
    DROP COLUMN IF EXISTS quota_enabled;
DROP INDEX IF EXISTS idx_provider_api_keys_quota;

ALTER TABLE billing_usage_records
    ADD COLUMN IF NOT EXISTS quota_month_start DATE;

CREATE TABLE IF NOT EXISTS billing_provider_monthly_quotas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_api_key_id UUID NOT NULL REFERENCES provider_api_keys(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    month_start DATE NOT NULL,
    quota_micro BIGINT NOT NULL,
    reserved_micro BIGINT NOT NULL DEFAULT 0,
    consumed_micro BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider_api_key_id, month_start),
    CHECK (quota_micro >= 0 AND reserved_micro >= 0 AND consumed_micro >= 0),
    CHECK (reserved_micro + consumed_micro <= quota_micro)
);

CREATE INDEX IF NOT EXISTS idx_billing_provider_quota_month
    ON billing_provider_monthly_quotas (provider_api_key_id, month_start DESC);

ALTER TABLE billing_provider_monthly_quotas ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_provider_monthly_quotas FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS billing_provider_quotas_tenant_isolation ON billing_provider_monthly_quotas;
CREATE POLICY billing_provider_quotas_tenant_isolation
    ON billing_provider_monthly_quotas
    USING (tenant_id::text = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT, UPDATE, DELETE ON billing_provider_monthly_quotas TO parrot_app;

ALTER TABLE billing_usage_records
    DROP CONSTRAINT IF EXISTS billing_usage_records_token_source_check,
    DROP CONSTRAINT IF EXISTS billing_usage_records_status_check,
    DROP CONSTRAINT IF EXISTS billing_usage_records_multiplier_check,
    DROP CONSTRAINT IF EXISTS billing_usage_records_reconciliation_status_check,
    DROP CONSTRAINT IF EXISTS billing_usage_records_reserved_amount_check,
    DROP CONSTRAINT IF EXISTS billing_usage_records_estimated_tokens_check;
ALTER TABLE billing_usage_records
    ADD CONSTRAINT billing_usage_records_token_source_check
        CHECK (token_source IN ('provider', 'estimated', 'mixed')),
    ADD CONSTRAINT billing_usage_records_status_check
        CHECK (status IN ('reserved', 'in_progress', 'finalized', 'pending', 'completed', 'failed', 'refunded')),
    ADD CONSTRAINT billing_usage_records_multiplier_check
        CHECK (user_multiplier_snapshot BETWEEN 1 AND 10000
           AND channel_multiplier_snapshot BETWEEN 1 AND 10000
           AND model_multiplier_snapshot BETWEEN 1 AND 10000),
    ADD CONSTRAINT billing_usage_records_reconciliation_status_check
        CHECK (reconciliation_status IN ('pending', 'matched', 'adjusted', 'manual')),
    ADD CONSTRAINT billing_usage_records_estimated_tokens_check
        CHECK (estimated_input_tokens >= 0 AND estimated_output_tokens >= 0
           AND estimated_cached_input_tokens >= 0 AND estimated_amount_micro >= 0),
    ADD CONSTRAINT billing_usage_records_reserved_amount_check
        CHECK (reserved_amount_micro >= 0 AND released_amount_micro >= 0);

ALTER TABLE billing_ledger_entries
    DROP CONSTRAINT IF EXISTS billing_ledger_entries_entry_type_check;
ALTER TABLE billing_ledger_entries
    ADD CONSTRAINT billing_ledger_entries_entry_type_check
        CHECK (entry_type IN ('credit', 'reservation', 'debit', 'release', 'refund', 'adjustment'));

CREATE TABLE IF NOT EXISTS billing_reconciliation_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'failed')),
    usage_count INTEGER NOT NULL DEFAULT 0,
    estimated_total_micro BIGINT NOT NULL DEFAULT 0,
    actual_total_micro BIGINT NOT NULL DEFAULT 0,
    delta_total_micro BIGINT NOT NULL DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    UNIQUE (tenant_id, period_start, period_end),
    CHECK (period_end > period_start),
    CHECK (usage_count >= 0)
);

CREATE TABLE IF NOT EXISTS billing_reconciliation_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES billing_reconciliation_runs(id) ON DELETE CASCADE,
    usage_record_id UUID NOT NULL REFERENCES billing_usage_records(id) ON DELETE CASCADE,
    estimated_amount_micro BIGINT NOT NULL,
    actual_amount_micro BIGINT NOT NULL,
    delta_micro BIGINT NOT NULL,
    adjustment_type VARCHAR(16) NOT NULL DEFAULT 'none'
        CHECK (adjustment_type IN ('none', 'debit', 'refund', 'manual')),
    ledger_entry_id UUID REFERENCES billing_ledger_entries(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, usage_record_id)
);

CREATE INDEX IF NOT EXISTS idx_billing_usage_trace_id
    ON billing_usage_records (trace_id);
CREATE INDEX IF NOT EXISTS idx_billing_usage_status
    ON billing_usage_records (tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_billing_usage_reconciliation
    ON billing_usage_records (tenant_id, reconciliation_status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_billing_reconciliation_runs_tenant_period
    ON billing_reconciliation_runs (tenant_id, period_start DESC);
CREATE INDEX IF NOT EXISTS idx_billing_reconciliation_items_usage
    ON billing_reconciliation_items (usage_record_id);

COMMIT;
