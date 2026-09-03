-- Canonical data/records entrypoint. Run schema.sql first.
-- Supply secrets at invocation time; do not commit real credentials here.
-- Example:
-- psql -d parrot \
--   -v gateway_prefix='david_20260830' \
--   -v gateway_secret='replace-with-random-secret' \
--   -v gateway_pepper='' \
--   -v provider_name='deepseek' \
--   -v provider_api_key='replace-with-provider-key' \
--   -f infrastructure/sql/records/records.sql

\set ON_ERROR_STOP on
\if :{?gateway_prefix}
\else
\set gateway_prefix 'shawn_local'
\endif
\if :{?gateway_secret}
\else
\set gateway_secret 'bb2be7b94df3f0eb015bcd1dd6c0db466cad4a3b9cce385b9b4e3e9457300487'
\endif
\if :{?gateway_pepper}
\else
\set gateway_pepper ''
\endif
\if :{?provider_name}
\else
\set provider_name 'kimi'
\endif
\if :{?provider_api_key}
\else
\set provider_api_key 'replace-with-provider-key'
\endif

BEGIN;

INSERT INTO tenants (slug, name, status)
VALUES ('steno', 'Steno', 'active')
ON CONFLICT (slug) DO UPDATE
SET name = EXCLUDED.name, status = EXCLUDED.status, updated_at = now();

SELECT id AS tenant_id FROM tenants WHERE slug = 'steno'\gset

INSERT INTO users (tenant_id, username, email, display_name, role, status)
VALUES (:'tenant_id', 'david', 'david@steno.local', 'david', 'owner', 'active')
ON CONFLICT (tenant_id, email) DO UPDATE
SET username = EXCLUDED.username,
    display_name = EXCLUDED.display_name,
    role = EXCLUDED.role,
    status = EXCLUDED.status,
    updated_at = now();

SELECT id AS user_id FROM users
WHERE tenant_id = :'tenant_id' AND username = 'david'\gset

INSERT INTO billing_accounts (tenant_id, currency)
VALUES (:'tenant_id', 'USD')
ON CONFLICT (tenant_id) DO NOTHING;

INSERT INTO gateway_api_keys (
    tenant_id, user_id, key_prefix, key_hash, name, scopes, status
)
VALUES (
    :'tenant_id', :'user_id', :'gateway_prefix',
    encode(hmac((:'gateway_prefix' || '_' || :'gateway_secret')::bytea,
                :'gateway_pepper'::bytea, 'sha256'), 'hex'),
    'david-gateway-key', '["chat.completions.invoke", "models.read"]'::jsonb,
    'active'
)
ON CONFLICT (key_prefix) DO UPDATE
SET tenant_id = EXCLUDED.tenant_id,
    user_id = EXCLUDED.user_id,
    key_hash = EXCLUDED.key_hash,
    scopes = EXCLUDED.scopes,
    status = 'active';

INSERT INTO provider_api_keys (
    tenant_id, user_id, provider, api_key, name, key_hint, status
)
VALUES (
    :'tenant_id', :'user_id', :'provider_name', :'provider_api_key',
    :'provider_name' || '-default', right(:'provider_api_key', 4), 'active'
)
ON CONFLICT (tenant_id, name) DO UPDATE
SET user_id = EXCLUDED.user_id,
    provider = EXCLUDED.provider,
    api_key = EXCLUDED.api_key,
    key_hint = EXCLUDED.key_hint,
    status = 'active',
    updated_at = now();

COMMIT;

-- The plaintext Gateway Key is displayed only by this invocation.
SELECT 'steno' AS tenant, 'david' AS username,
       :'gateway_prefix' || '_' || :'gateway_secret' AS gateway_api_key,
       :'provider_name' AS provider;
