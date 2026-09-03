-- Canonical final schema. Run with: psql -d parrot -f infrastructure/sql/schema/schema.sql
-- ALTER statements below only enable/force RLS (PostgreSQL has no CREATE TABLE
-- equivalent); there are no data migration UPDATEs or compatibility ALTERs.
\set ON_ERROR_STOP on
CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='parrot_app') THEN
   CREATE ROLE parrot_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
 END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='parrot_owner') THEN
   CREATE ROLE parrot_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
 END IF;
END $$;

CREATE TABLE IF NOT EXISTS tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- 租户唯一标识
    slug VARCHAR(64) NOT NULL UNIQUE,  -- 租户唯一编码
    name VARCHAR(128) NOT NULL,  -- 租户名称
    status VARCHAR(16) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'deleted')),  -- 租户状态
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,  -- 租户扩展元数据
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),  -- 创建时间
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()  -- 更新时间
);

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- 用户唯一标识
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,  -- 所属租户标识
    username VARCHAR(64),  -- 租户内用户名
    email VARCHAR(320) NOT NULL,  -- 用户邮箱
    display_name VARCHAR(128),  -- 显示名称
    role VARCHAR(32) NOT NULL DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member')),  -- 用户角色
    status VARCHAR(16) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled', 'deleted')),  -- 用户状态
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),  -- 创建时间
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),  -- 更新时间
    UNIQUE (tenant_id, email)
);

CREATE TABLE IF NOT EXISTS gateway_api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- 网关 Key 唯一标识
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,  -- 所属租户标识
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,  -- 创建或归属用户标识
    key_prefix VARCHAR(64) NOT NULL UNIQUE,  -- 网关 Key 前缀
    key_hash CHAR(64) NOT NULL UNIQUE,  -- 网关 Key HMAC 哈希
    name VARCHAR(128) NOT NULL,  -- Key 名称
    scopes JSONB NOT NULL DEFAULT '["chat.completions"]'::jsonb,  -- 授权范围
    status VARCHAR(16) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked', 'expired')),  -- Key 状态
    expires_at TIMESTAMPTZ,  -- 过期时间
    last_used_at TIMESTAMPTZ,  -- 最近使用时间
    revoked_at TIMESTAMPTZ,  -- 撤销时间
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),  -- 创建时间
    CHECK (expires_at IS NULL OR expires_at > created_at)
);

CREATE TABLE IF NOT EXISTS provider_api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- Provider 凭据唯一标识
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,  -- 所属租户标识
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,  -- 创建或归属用户标识
    provider VARCHAR(32) NOT NULL,  -- 渠道商名称
    api_key TEXT NOT NULL,  -- 兼容字段：上游 API Key（过渡期明文）
    name VARCHAR(128) NOT NULL,  -- 凭据名称
    key_hint VARCHAR(16),  -- 脱敏展示提示（通常为末四位）
    secret_ciphertext TEXT,  -- 加密后的上游 API Key
    secret_ref VARCHAR(512),  -- 外部密钥管理系统引用
    status VARCHAR(16) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),  -- 凭据状态
    expires_at TIMESTAMPTZ,  -- 凭据过期时间
    last_used_at TIMESTAMPTZ,  -- 最近使用时间
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),  -- 创建时间
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),  -- 更新时间
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,  -- 凭据扩展元数据
    UNIQUE (tenant_id, name)
);

CREATE TABLE IF NOT EXISTS billing_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- 计费账户唯一标识
    tenant_id UUID NOT NULL UNIQUE REFERENCES tenants(id) ON DELETE CASCADE,  -- 所属租户标识
    currency CHAR(3) NOT NULL DEFAULT 'USD',  -- 货币代码
    balance_micro BIGINT NOT NULL DEFAULT 0,  -- 账户余额，货币最小单位
    credit_limit_micro BIGINT NOT NULL DEFAULT 0,  -- 允许透支额度，货币最小单位
    status VARCHAR(16) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'closed')),  -- 账户状态
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),  -- 创建时间
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),  -- 更新时间
    CHECK (credit_limit_micro >= 0)
);

CREATE TABLE IF NOT EXISTS billing_provider_monthly_quotas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- 配额记录唯一标识
    provider_api_key_id UUID NOT NULL REFERENCES provider_api_keys(id) ON DELETE CASCADE,  -- Provider Key
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,  -- 所属租户
    month_start DATE NOT NULL,  -- 自然月起始日期
    quota_micro BIGINT NOT NULL,  -- 本月总配额
    reserved_micro BIGINT NOT NULL DEFAULT 0,  -- 预扣金额
    consumed_micro BIGINT NOT NULL DEFAULT 0,  -- 已确认消费金额
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),  -- 创建时间
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),  -- 更新时间
    UNIQUE (provider_api_key_id, month_start),
    CHECK (quota_micro >= 0 AND reserved_micro >= 0 AND consumed_micro >= 0),
    CHECK (reserved_micro + consumed_micro <= quota_micro)
);

CREATE TABLE IF NOT EXISTS billing_prices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- 价格记录唯一标识
    provider VARCHAR(32) NOT NULL,  -- 渠道商名称
    model VARCHAR(128) NOT NULL,  -- 模型名称或模型前缀
    match_type VARCHAR(16) NOT NULL DEFAULT 'exact' CHECK (match_type IN ('exact', 'prefix', 'default')),  -- 模型匹配方式：精确、前缀或默认
    currency CHAR(3) NOT NULL DEFAULT 'USD',  -- 货币代码
    input_price_micro_per_million BIGINT NOT NULL DEFAULT 0,  -- 每百万输入 Token 价格
    output_price_micro_per_million BIGINT NOT NULL DEFAULT 0,  -- 每百万输出 Token 价格
    cached_input_price_micro_per_million BIGINT NOT NULL DEFAULT 0,  -- 每百万缓存输入 Token 价格
    model_multiplier INTEGER NOT NULL DEFAULT 1000,  -- 模型倍率，千分位，1000 表示 1.0 倍
    effective_from TIMESTAMPTZ NOT NULL DEFAULT now(),  -- 价格生效时间
    effective_to TIMESTAMPTZ,  -- 价格失效时间
    active BOOLEAN NOT NULL DEFAULT true,  -- 是否启用
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,  -- 价格扩展元数据
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),  -- 创建时间
    CHECK (input_price_micro_per_million >= 0 AND output_price_micro_per_million >= 0 AND cached_input_price_micro_per_million >= 0),
    CHECK (model_multiplier BETWEEN 1 AND 10000),
    CHECK (effective_to IS NULL OR effective_to > effective_from)
);

CREATE TABLE IF NOT EXISTS billing_usage_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- 用量记录唯一标识
    request_id UUID NOT NULL UNIQUE,  -- 网关请求唯一标识，用于幂等
    trace_id UUID,  -- 分布式链路追踪标识
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,  -- 所属租户标识
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,  -- 请求用户标识
    gateway_api_key_id UUID REFERENCES gateway_api_keys(id) ON DELETE SET NULL,  -- 使用的网关 Key
    provider_api_key_id UUID REFERENCES provider_api_keys(id) ON DELETE SET NULL,  -- 使用的 Provider Key
    provider VARCHAR(32) NOT NULL,  -- 实际渠道商
    model VARCHAR(128) NOT NULL,  -- 实际模型
    estimated_price_id UUID REFERENCES billing_prices(id) ON DELETE SET NULL,  -- 测算时使用的价格版本
    estimated_input_tokens INTEGER NOT NULL DEFAULT 0,  -- 请求阶段测算的输入 Token 数
    estimated_output_tokens INTEGER NOT NULL DEFAULT 0,  -- 请求阶段测算的输出 Token 数
    estimated_cached_input_tokens INTEGER NOT NULL DEFAULT 0,  -- 请求阶段测算的缓存输入 Token 数
    estimated_amount_micro BIGINT NOT NULL DEFAULT 0,  -- 请求阶段测算金额
    estimated_at TIMESTAMPTZ NOT NULL DEFAULT now(),  -- 测算时间
    reserved_amount_micro BIGINT NOT NULL DEFAULT 0,  -- 预扣金额
    reserved_at TIMESTAMPTZ,  -- 预扣时间
    quota_month_start DATE,  -- 配额所属自然月
    actual_input_tokens INTEGER,  -- Provider 返回的实际输入 Token 数
    actual_output_tokens INTEGER,  -- Provider 返回的实际输出 Token 数
    actual_cached_input_tokens INTEGER,  -- Provider 返回的实际缓存输入 Token 数
    token_source VARCHAR(16) NOT NULL DEFAULT 'estimated'  -- Token 来源：Provider、估算或混合
        CHECK (token_source IN ('provider', 'estimated', 'mixed')),
    usage_available BOOLEAN NOT NULL DEFAULT false,  -- Provider 是否返回 usage
    usage_raw JSONB,  -- Provider 原始 usage JSON
    estimated_input_price_micro_per_million BIGINT NOT NULL DEFAULT 0,  -- 测算输入 Token 单价
    estimated_output_price_micro_per_million BIGINT NOT NULL DEFAULT 0,  -- 测算输出 Token 单价
    estimated_cached_input_price_micro_per_million BIGINT NOT NULL DEFAULT 0,  -- 测算缓存输入 Token 单价
    actual_price_id UUID REFERENCES billing_prices(id) ON DELETE SET NULL,  -- 对账时使用的实际价格版本
    actual_input_price_micro_per_million BIGINT,  -- 实际输入 Token 单价
    actual_output_price_micro_per_million BIGINT,  -- 实际输出 Token 单价
    actual_cached_input_price_micro_per_million BIGINT,  -- 实际缓存输入 Token 单价
    user_multiplier_snapshot INTEGER NOT NULL DEFAULT 1000,  -- 用户倍率快照，千分位
    channel_multiplier_snapshot INTEGER NOT NULL DEFAULT 1000,  -- 渠道倍率快照，千分位
    model_multiplier_snapshot INTEGER NOT NULL DEFAULT 1000,  -- 模型倍率快照，千分位
    combined_multiplier_snapshot BIGINT NOT NULL DEFAULT 1000000000,  -- 合并倍率快照，十亿分位
    actual_amount_micro BIGINT,  -- 按实际用量计算的金额
    reconciliation_status VARCHAR(16) NOT NULL DEFAULT 'pending'  -- 对账状态
        CHECK (reconciliation_status IN ('pending', 'matched', 'adjusted', 'manual')),
    reconciliation_delta_micro BIGINT NOT NULL DEFAULT 0,  -- 测算与实际金额差额
    reconciled_at TIMESTAMPTZ,  -- 完成对账时间
    released_amount_micro BIGINT NOT NULL DEFAULT 0,  -- 释放的预扣金额
    balance_delta_micro BIGINT NOT NULL DEFAULT 0,  -- 余额调整差额
    currency CHAR(3) NOT NULL DEFAULT 'USD',  -- 货币代码
    status VARCHAR(16) NOT NULL DEFAULT 'reserved' CHECK (status IN ('reserved', 'in_progress', 'finalized', 'completed', 'failed', 'refunded')),  -- 请求处理状态
    is_stream BOOLEAN NOT NULL DEFAULT false,  -- 是否为流式请求
    finalized_at TIMESTAMPTZ,  -- 最终结算时间
    refund_at TIMESTAMPTZ,  -- 退款时间
    error_code VARCHAR(64),  -- 错误编码
    error_message TEXT,  -- 错误信息
    latency_ms INTEGER,  -- 上游请求耗时（毫秒）
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,  -- 用量扩展元数据
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),  -- 记录创建时间
    CHECK (estimated_input_tokens >= 0 AND estimated_output_tokens >= 0 AND estimated_cached_input_tokens >= 0),
    CHECK (estimated_amount_micro >= 0),
    CHECK (reserved_amount_micro >= 0 AND released_amount_micro >= 0),
    CHECK (user_multiplier_snapshot BETWEEN 1 AND 10000 AND channel_multiplier_snapshot BETWEEN 1 AND 10000 AND model_multiplier_snapshot BETWEEN 1 AND 10000),
    CHECK (estimated_input_price_micro_per_million >= 0 AND estimated_output_price_micro_per_million >= 0 AND estimated_cached_input_price_micro_per_million >= 0),
    CHECK (actual_input_price_micro_per_million IS NULL OR actual_input_price_micro_per_million >= 0),
    CHECK (actual_output_price_micro_per_million IS NULL OR actual_output_price_micro_per_million >= 0),
    CHECK (actual_cached_input_price_micro_per_million IS NULL OR actual_cached_input_price_micro_per_million >= 0),
    CHECK (actual_input_tokens IS NULL OR actual_input_tokens >= 0),
    CHECK (actual_output_tokens IS NULL OR actual_output_tokens >= 0),
    CHECK (actual_cached_input_tokens IS NULL OR actual_cached_input_tokens >= 0),
    CHECK (actual_amount_micro IS NULL OR actual_amount_micro >= 0)
);

CREATE TABLE IF NOT EXISTS billing_ledger_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- 流水唯一标识
    account_id UUID NOT NULL REFERENCES billing_accounts(id) ON DELETE CASCADE,  -- 计费账户标识
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,  -- 所属租户标识
    usage_record_id UUID REFERENCES billing_usage_records(id) ON DELETE SET NULL,  -- 关联用量记录
    entry_type VARCHAR(16) NOT NULL CHECK (entry_type IN ('credit', 'reservation', 'debit', 'release', 'refund', 'adjustment')),  -- 流水类型
    amount_micro BIGINT NOT NULL CHECK (amount_micro <> 0),  -- 本次变动金额
    balance_after_micro BIGINT NOT NULL,  -- 变动后余额
    idempotency_key VARCHAR(128) UNIQUE,  -- 业务幂等键
    description VARCHAR(256),  -- 流水说明
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,  -- 流水扩展元数据
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()  -- 创建时间
);

CREATE TABLE IF NOT EXISTS billing_reconciliation_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- 对账批次唯一标识
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,  -- 所属租户标识
    period_start TIMESTAMPTZ NOT NULL,  -- 对账周期开始时间
    period_end TIMESTAMPTZ NOT NULL,  -- 对账周期结束时间
    status VARCHAR(16) NOT NULL DEFAULT 'running'  -- 对账批次状态
        CHECK (status IN ('running', 'completed', 'failed')),
    usage_count INTEGER NOT NULL DEFAULT 0,  -- 参与对账的用量条数
    estimated_total_micro BIGINT NOT NULL DEFAULT 0,  -- 测算总金额
    actual_total_micro BIGINT NOT NULL DEFAULT 0,  -- 实际总金额
    delta_total_micro BIGINT NOT NULL DEFAULT 0,  -- 总金额差额
    error_message TEXT,  -- 失败原因
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),  -- 开始时间
    completed_at TIMESTAMPTZ,  -- 完成时间
    UNIQUE (tenant_id, period_start, period_end),
    CHECK (period_end > period_start),
    CHECK (usage_count >= 0)
);

CREATE TABLE IF NOT EXISTS billing_reconciliation_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- 对账明细唯一标识
    run_id UUID NOT NULL REFERENCES billing_reconciliation_runs(id) ON DELETE CASCADE,  -- 所属对账批次
    usage_record_id UUID NOT NULL REFERENCES billing_usage_records(id) ON DELETE CASCADE,  -- 关联用量记录
    estimated_amount_micro BIGINT NOT NULL,  -- 测算金额
    actual_amount_micro BIGINT NOT NULL,  -- 实际金额
    delta_micro BIGINT NOT NULL,  -- 金额差额
    adjustment_type VARCHAR(16) NOT NULL DEFAULT 'none'  -- 调整类型
        CHECK (adjustment_type IN ('none', 'debit', 'refund', 'manual')),
    ledger_entry_id UUID REFERENCES billing_ledger_entries(id) ON DELETE SET NULL,  -- 关联调整流水
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),  -- 创建时间
    UNIQUE (run_id, usage_record_id)
);

CREATE INDEX IF NOT EXISTS idx_users_tenant_id ON users(tenant_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_tenant_email_ci ON users(tenant_id,lower(email));
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_tenant_username_ci ON users(tenant_id,lower(username)) WHERE username IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_gateway_api_keys_tenant_id ON gateway_api_keys(tenant_id);
CREATE INDEX IF NOT EXISTS idx_gateway_api_keys_user_id ON gateway_api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_gateway_api_keys_active_prefix ON gateway_api_keys(key_prefix) WHERE status='active';
CREATE INDEX IF NOT EXISTS idx_billing_provider_quota_month ON billing_provider_monthly_quotas(provider_api_key_id,month_start DESC);
CREATE INDEX IF NOT EXISTS idx_provider_api_keys_user_provider ON provider_api_keys(user_id,provider);
CREATE INDEX IF NOT EXISTS idx_provider_api_keys_tenant_status ON provider_api_keys(tenant_id,status);
CREATE INDEX IF NOT EXISTS idx_billing_prices_lookup ON billing_prices(provider,model,match_type,active,effective_from DESC);
CREATE INDEX IF NOT EXISTS idx_billing_usage_tenant_created ON billing_usage_records(tenant_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_billing_usage_trace_id ON billing_usage_records(trace_id);
CREATE INDEX IF NOT EXISTS idx_billing_usage_status ON billing_usage_records(tenant_id,status,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_billing_usage_provider_model ON billing_usage_records(provider,model,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_billing_usage_reconciliation ON billing_usage_records(tenant_id,reconciliation_status,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_billing_reconciliation_runs_tenant_period ON billing_reconciliation_runs(tenant_id,period_start DESC);
CREATE INDEX IF NOT EXISTS idx_billing_reconciliation_items_usage ON billing_reconciliation_items(usage_record_id);
CREATE INDEX IF NOT EXISTS idx_billing_ledger_tenant_created ON billing_ledger_entries(tenant_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_billing_ledger_account_created ON billing_ledger_entries(account_id,created_at DESC);

CREATE OR REPLACE FUNCTION validate_gateway_key_user_tenant() RETURNS TRIGGER AS $$ BEGIN
 IF NEW.user_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM users WHERE id=NEW.user_id AND tenant_id=NEW.tenant_id) THEN RAISE EXCEPTION 'gateway key user does not belong to tenant'; END IF; RETURN NEW; END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_gateway_key_user_tenant ON gateway_api_keys;
CREATE TRIGGER trg_gateway_key_user_tenant BEFORE INSERT OR UPDATE OF tenant_id,user_id ON gateway_api_keys FOR EACH ROW EXECUTE FUNCTION validate_gateway_key_user_tenant();
CREATE OR REPLACE FUNCTION validate_provider_key_user_tenant() RETURNS TRIGGER AS $$ BEGIN
 IF NEW.user_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM users WHERE id=NEW.user_id AND tenant_id=NEW.tenant_id) THEN RAISE EXCEPTION 'provider key user does not belong to tenant'; END IF; RETURN NEW; END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_provider_key_user_tenant ON provider_api_keys;
CREATE TRIGGER trg_provider_key_user_tenant BEFORE INSERT OR UPDATE OF tenant_id,user_id ON provider_api_keys FOR EACH ROW EXECUTE FUNCTION validate_provider_key_user_tenant();

ALTER TABLE users ENABLE ROW LEVEL SECURITY; ALTER TABLE gateway_api_keys ENABLE ROW LEVEL SECURITY; ALTER TABLE provider_api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_accounts ENABLE ROW LEVEL SECURITY; ALTER TABLE billing_prices ENABLE ROW LEVEL SECURITY; ALTER TABLE billing_usage_records ENABLE ROW LEVEL SECURITY; ALTER TABLE billing_ledger_entries ENABLE ROW LEVEL SECURITY; ALTER TABLE billing_reconciliation_runs ENABLE ROW LEVEL SECURITY; ALTER TABLE billing_reconciliation_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_provider_monthly_quotas ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY; ALTER TABLE gateway_api_keys FORCE ROW LEVEL SECURITY; ALTER TABLE provider_api_keys FORCE ROW LEVEL SECURITY; ALTER TABLE billing_accounts FORCE ROW LEVEL SECURITY; ALTER TABLE billing_usage_records FORCE ROW LEVEL SECURITY; ALTER TABLE billing_ledger_entries FORCE ROW LEVEL SECURITY; ALTER TABLE billing_reconciliation_runs FORCE ROW LEVEL SECURITY; ALTER TABLE billing_reconciliation_items FORCE ROW LEVEL SECURITY;
ALTER TABLE billing_provider_monthly_quotas FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS users_tenant_isolation ON users;
CREATE POLICY users_tenant_isolation ON users USING(tenant_id::text=current_setting('app.tenant_id',true));
DROP POLICY IF EXISTS gateway_keys_tenant_isolation ON gateway_api_keys;
CREATE POLICY gateway_keys_tenant_isolation ON gateway_api_keys USING(tenant_id::text=current_setting('app.tenant_id',true) OR key_prefix=current_setting('app.key_lookup_prefix',true));
DROP POLICY IF EXISTS provider_keys_tenant_isolation ON provider_api_keys;
CREATE POLICY provider_keys_tenant_isolation ON provider_api_keys USING(tenant_id::text=current_setting('app.tenant_id',true)) WITH CHECK(tenant_id::text=current_setting('app.tenant_id',true));
DROP POLICY IF EXISTS billing_accounts_tenant_isolation ON billing_accounts;
CREATE POLICY billing_accounts_tenant_isolation ON billing_accounts USING(tenant_id::text=current_setting('app.tenant_id',true)) WITH CHECK(tenant_id::text=current_setting('app.tenant_id',true));
DROP POLICY IF EXISTS billing_prices_read ON billing_prices;
CREATE POLICY billing_prices_read ON billing_prices FOR SELECT USING(current_setting('app.tenant_id',true) IS NOT NULL);
DROP POLICY IF EXISTS billing_usage_tenant_isolation ON billing_usage_records;
CREATE POLICY billing_usage_tenant_isolation ON billing_usage_records USING(tenant_id::text=current_setting('app.tenant_id',true)) WITH CHECK(tenant_id::text=current_setting('app.tenant_id',true));
DROP POLICY IF EXISTS billing_ledger_tenant_isolation ON billing_ledger_entries;
CREATE POLICY billing_ledger_tenant_isolation ON billing_ledger_entries USING(tenant_id::text=current_setting('app.tenant_id',true)) WITH CHECK(tenant_id::text=current_setting('app.tenant_id',true));
DROP POLICY IF EXISTS billing_reconciliation_runs_tenant_isolation ON billing_reconciliation_runs;
CREATE POLICY billing_reconciliation_runs_tenant_isolation ON billing_reconciliation_runs USING(tenant_id::text=current_setting('app.tenant_id',true)) WITH CHECK(tenant_id::text=current_setting('app.tenant_id',true));
DROP POLICY IF EXISTS billing_reconciliation_items_tenant_isolation ON billing_reconciliation_items;
CREATE POLICY billing_reconciliation_items_tenant_isolation ON billing_reconciliation_items USING(EXISTS (SELECT 1 FROM billing_reconciliation_runs r WHERE r.id=run_id AND r.tenant_id::text=current_setting('app.tenant_id',true))) WITH CHECK(EXISTS (SELECT 1 FROM billing_reconciliation_runs r WHERE r.id=run_id AND r.tenant_id::text=current_setting('app.tenant_id',true)));
DROP POLICY IF EXISTS billing_provider_quotas_tenant_isolation ON billing_provider_monthly_quotas;
CREATE POLICY billing_provider_quotas_tenant_isolation ON billing_provider_monthly_quotas USING(tenant_id::text=current_setting('app.tenant_id',true)) WITH CHECK(tenant_id::text=current_setting('app.tenant_id',true));

REVOKE ALL ON tenants,users,gateway_api_keys,provider_api_keys,billing_accounts,billing_prices,billing_usage_records,billing_ledger_entries,billing_reconciliation_runs,billing_reconciliation_items,billing_provider_monthly_quotas FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO parrot_app;
GRANT SELECT,INSERT,UPDATE,DELETE ON tenants,users,gateway_api_keys,provider_api_keys,billing_accounts,billing_usage_records,billing_ledger_entries,billing_reconciliation_runs,billing_reconciliation_items,billing_provider_monthly_quotas TO parrot_app;
GRANT SELECT ON billing_prices TO parrot_app;
