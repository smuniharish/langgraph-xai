# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Test coverage for every `InstrumentedGraph` execution method (`invoke`,
  `ainvoke`, `stream`, `astream`, `batch`, `abatch`), including error,
  partial-failure (`return_exceptions=True`), and cancellation paths.
- `CODE_OF_CONDUCT.md`, `CODEOWNERS`, GitHub issue templates, a pull request
  template, and a docs deployment workflow.

### Changed

- Removed unused, unexported `decision.engines`, `evidence.service`, and
  `provenance.service` modules. Their functionality is already available
  through `XAIRuntime.record_decision()`, `XAIRuntime.record_evidence()`, and
  `ProvenanceStore.parents()` / `.children()` / `.lineage()`, which are the
  supported public API for these operations.

## [0.1.0]

### Added

- Initial public release of `langgraph-xai`.
- Canonical explainability models: `Execution`, `ProvenanceLink`, `Evidence`,
  `Decision`, `Attribution`, `Explanation`, and policy primitives.
- `XAIRuntime` with a provider registry, run lifecycle management
  (`start_run` / `finish_run`), and `instrument()` for wrapping compiled
  LangGraph graphs.
- Storage backends: in-memory (`InMemoryProvenanceStore`) and PostgreSQL
  (`PostgresProvenanceStore`).
- Observability integrations: LangSmith, Langfuse, and OpenTelemetry.
- Attribution engines (rule-based, heuristic, hybrid) and explanation
  engines (template-based and LLM-based).
- Policy-aware disclosure via `PolicyProvider` with audience-scoped exposure
  rules.
- Documentation site (MkDocs Material) covering concepts, guides, API
  reference, and integrations.
