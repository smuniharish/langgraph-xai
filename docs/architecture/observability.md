# Observability architecture

## Kid-level view

Observability answers “is it working?”; explainability answers “what approved
facts and choices can we show?”

## Production view

Correlate runtime artifacts with traces or metrics using IDs and context, but
keep artifact schema and disclosure semantics independent from telemetry.
Export only policy-approved fields and define retention at the destination.

![Observability boundary](../assets/diagrams/observability-boundary.png)

## Common mistakes

Do not equate a span with evidence, export payloads because an exporter is
enabled, or use telemetry as an authorization or audit system.

