# Troubleshooting

## No artifacts appear

Confirm the runtime instance is constructed and attached to supported
boundaries, then check capture mode and explicit event emission. A provider
credential alone does not enable capture.

## Export is empty or redacted

Inspect policy decisions at capture and export, verify the adapter receives
canonical artifacts, and confirm the field is not reference-only by design.
Do not weaken policy to make a test pass.

## Diagram verification fails

Install `@mermaid-js/mermaid-cli@11.17.0` globally, then run
`node scripts/render-diagrams.mjs`. `node scripts/render-diagrams.mjs --check` is
deterministic and fails when a PNG is missing or stale.

## Strict docs build fails

Run `mkdocs build --strict`, fix broken nav or relative links, and ensure every
new page is included intentionally. Do not hide warnings by disabling strict
mode.

## Graph succeeds but explanation fails

Check the configured failure mode and adapter logs. Distinguish graph success,
canonicalization success, storage success, and export success; they are
separate outcomes.
