-- Kimi official Chat Completion prices (CNY per 1M tokens).
-- Source: https://platform.kimi.com/docs/pricing/chat
-- Current public models: Kimi K3, Kimi K2.7 Code and Kimi K2.6.
\set ON_ERROR_STOP on

BEGIN;

INSERT INTO billing_prices (
    provider,
    model,
    match_type,
    currency,
    input_price_micro_per_million,
    output_price_micro_per_million,
    cached_input_price_micro_per_million,
    model_multiplier,
    effective_from,
    active,
    metadata
)
SELECT
    v.provider,
    v.model,
    'exact',
    'CNY',
    (v.input_price_cny * 1000000)::BIGINT,
    (v.output_price_cny * 1000000)::BIGINT,
    (v.cached_input_price_cny * 1000000)::BIGINT,
    1000,
    now(),
    true,
    jsonb_build_object(
        'source', 'https://platform.kimi.com/docs/pricing/chat',
        'pricing_unit', 'CNY per 1M tokens',
        'price_basis', 'public list price'
    )
FROM (VALUES
    ('kimi', 'kimi-k3', 20.00::numeric, 100.00::numeric, 2.00::numeric),
    ('kimi', 'kimi-k2.7', 6.50::numeric, 27.00::numeric, 1.30::numeric),
    ('kimi', 'kimi-k2.6', 6.50::numeric, 27.00::numeric, 1.10::numeric)
) AS v(provider, model, input_price_cny, output_price_cny, cached_input_price_cny)
WHERE NOT EXISTS (
    SELECT 1
    FROM billing_prices p
    WHERE p.provider = v.provider
      AND p.model = v.model
      AND p.match_type = 'exact'
      AND p.active = true
      AND p.metadata ->> 'source' = 'https://platform.kimi.com/docs/pricing/chat'
);

COMMIT;
