# Database SQL layout

Use the canonical entrypoints for new environments:

```bash
psql -d parrot -f infrastructure/sql/schema/schema.sql
psql -d parrot -v gateway_secret="..." -v provider_api_key="..." \
  -f infrastructure/sql/records/records.sql
```

`schema/schema.sql` contains only extensions, tables, columns, indexes,
triggers, roles/grants and RLS policies. `records/records.sql` contains only
tenant/user/account/credential seed records. Secrets are supplied as `psql`
variables and are intentionally not stored in the repository.

The numbered files in this directory are retained as historical migrations.
