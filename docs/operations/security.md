# Security

Report suspected vulnerabilities privately to `samamuniharish@gmail.com`; do
not disclose credentials or sensitive production data. The project prioritizes
the latest released version for security fixes.

## Deployment checklist

- Start with minimal capture and expand only with a reviewed use case.
- Classify artifact fields and apply disclosure policy at each boundary.
- Keep secrets in a managed secret store or deployment environment.
- Set retention and access controls for every selected storage or integration.
- Choose and document the appropriate fail-open or fail-closed mode.
- Test redaction, omission, and export behavior with sensitive-data fixtures.

Explainability supplements application observability and communication. It does
not replace authorization, access control, audit logging, or incident response.
