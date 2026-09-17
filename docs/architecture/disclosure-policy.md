# Disclosure policy

Explainability has data-handling consequences. A disclosure policy determines
what can be captured, retained, exported, resolved, and shown.

## Policy operations

- **Allow:** retain the approved value at the boundary.
- **Omit:** do not retain or emit the value.
- **Redact:** replace sensitive portions with a safe representation.
- **Reference-only:** retain a controlled reference and metadata, not payload
  content.

## Required boundaries

Apply policy when:

1. receiving data for artifact capture;
2. writing to any persistence adapter;
3. exporting to an external integration; and
4. rendering an explanation or other user-facing output.

Policy is an application responsibility informed by its privacy, security, and
retention obligations. It should be tested with realistic sensitive-data
fixtures and reviewed when new artifact fields or integrations are added.

![Policy boundary](../assets/diagrams/policy-boundary.png)
