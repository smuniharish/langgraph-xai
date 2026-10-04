<!--
Thanks for contributing to langgraph-xai! Please fill out this template —
it helps reviewers understand and validate your change quickly.
-->

## Summary

<!-- What does this PR change, and why? -->

## Related issue(s)

<!-- Link any related issues, e.g. "Closes #123". -->

## Type of change

- [ ] Bug fix
- [ ] New feature (protocol, provider, canonical model field, capability)
- [ ] Documentation
- [ ] Refactor / internal cleanup (no behavior change)
- [ ] Other (describe above)

## Checklist

- [ ] I read [CONTRIBUTING.md](../CONTRIBUTING.md).
- [ ] New/changed public behavior is covered by tests.
- [ ] `uv run ruff check .` and `uv run ruff format --check .` pass.
- [ ] `uv run pyrefly check` passes.
- [ ] `uv run pytest --cov=langgraph_xai --cov-branch` passes with 100% coverage.
- [ ] `uv run mkdocs build --strict` passes, and diagrams were re-rendered if
      a `diagrams/*.mmd` source changed.
- [ ] Relevant docs under `docs/` were updated (if this changes public API,
      configuration, or behavior).
- [ ] `CHANGELOG.md` has an entry under `[Unreleased]` (if this is a
      user-visible change).

## Capture and disclosure impact

<!--
Does this change what is captured, stored, exported to a tracing backend, or
disclosed in an explanation? Describe the effect, or write "None".
New providers should implement an existing capability contract (the
ProvenanceStore base class or a protocol) without changes to XAIRuntime.
-->