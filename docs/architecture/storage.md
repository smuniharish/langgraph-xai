# Storage architecture

## Kid-level view

Storage is the filing cabinet; it should keep useful labels without keeping
every private paper.

## Production view

Persistence adapters store canonical, policy-approved artifacts with schema
version, tenant/run boundaries, retention, access controls, and consistency
semantics. A PostgreSQL DSN belongs to the host or adapter, not canonical
configuration.

## Why and example

Use references for large or sensitive sources and retain enough metadata to
report unresolved references. Test deletion and retention, not just writes.

## Common mistakes

Do not persist raw prompts by default, mix tenants, or assume a successful
write means an external export succeeded.

