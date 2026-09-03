-- DeepSeek official prices (CNY per 1M tokens).
-- Source: https://api-docs.deepseek.com/zh-cn/quick_start/pricing/
-- The current schema has no peak/off-peak selector, so peak prices are the
-- active rates. Off-peak rates are retained in metadata for future scheduling.
\set ON_ERROR_STOP on

BEGIN;

INSERT INTO billing_prices (
    provider, model, match_type, currency,
    input_price_micro_per_million,
    output_price_micro_per_million,
    cached_input_price_micro_per_million,
    model_multiplier, effective_from, active, metadata
)
SELECT
    v.provider, v.model, 'exact', 'CNY',
    v.input_peak * 1000000,
    v.output_peak * 1000000,
    v.cached_input_peak * 1000000,
    1000, now(), true,
    jsonb_build_object(
        'source', 'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/',
        'pricing_basis', 'peak',
        'idle_input_price_cny_per_million', v.input_idle,
        'idle_output_price_cny_per_million', v.output_idle,
        'idle_cached_input_price_cny_per_million', v.cached_input_idle,
        'peak_hours', 'Mon-Fri 09:00-12:00,14:00-18:00 Asia/Shanghai'
    )
FROM (VALUES
    ('deepseek', 'deepseek-v4-flash', 3.0::numeric, 9.0::numeric, 0.10::numeric, 1.5::numeric, 4.5::numeric, 0.05::numeric),
    ('deepseek', 'deepseek-v4-pro', 9.0::numeric, 27.0::numeric, 0.30::numeric, 4.5::numeric, 13.5::numeric, 0.15::numeric),
    ('deepseek', 'deepseek-v4-flash-vision-exp', 3.0::numeric, 9.0::numeric, 0.10::numeric, 1.5::numeric, 4.5::numeric, 0.05::numeric)
) AS v(provider, model, input_peak, output_peak, cached_input_peak, input_idle, output_idle, cached_input_idle)
WHERE NOT EXISTS (
    SELECT 1 FROM billing_prices p
    WHERE p.provider = v.provider
      AND p.model = v.model
      AND p.match_type = 'exact'
      AND p.active = true
      AND p.metadata ->> 'source' = 'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/'
);

COMMIT;
