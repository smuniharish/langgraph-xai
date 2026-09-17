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
- [ ] `uv run pytest -m "not live and not postgres"` passes.
- [ ] Relevant docs under `docs/` were updated (if this changes public API,
      configuration, or behavior).
- [ ] `CHANGELOG.md` has an entry under `[Unreleased]` (if this is a
      user-visible change).

## Architectural notes (if applicable)

<!--
If this PR adds a new provider, storage backend, attribution/explanation
engine, or capability: confirm it is wired through an existing Protocol and
the plugin registry, and that XAIRuntime itself did not need to change.
-->
