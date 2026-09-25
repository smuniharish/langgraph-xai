# langgraph-xai Agent Skills

This directory is the canonical Agent Skills distribution for
`langgraph-xai`. It contains procedural guidance for coding agents that need
to integrate, configure, test, or debug the existing `langgraph-xai` package.

It is not a Python package and does not add runtime behavior.

| Component | Location | Purpose |
| --- | --- | --- |
| langgraph-xai runtime | [`src/langgraph_xai/`](../src/langgraph_xai/) | The published Python package and its supported public API. |
| langgraph-xai Agent Skill | [`skills/langgraph-xai/`](skills/langgraph-xai/) | Canonical agent-oriented integration and operations guidance. |
| Skill validation | [`validation/`](validation/) | Validation procedure and realistic activation/task matrix. |

## Agent Skills format

The canonical skill follows the [Agent Skills
specification](https://agentskills.io/specification): a directory-scoped
Markdown instruction file with required `name` and `description` YAML
frontmatter. Its `name` matches its containing directory (`langgraph-xai`),
and only the specification's required frontmatter is used for portability.

Compatible agents should load
[`skills/langgraph-xai/SKILL.md`](skills/langgraph-xai/SKILL.md) when working
on explainability, provenance, evidence, decisions, disclosure policy, or
instrumentation for LangGraph applications. The skill links to this
repository's authoritative documentation and examples instead of maintaining a
second copy of them.

This repository intentionally provides no Claude, Codex, or Copilot adapter
because none is required to consume the canonical `SKILL.md`.

## Maintaining the distribution

When the public API, supported integrations, or documented behavior changes:

1. Update the canonical skill and only the material affected by the verified
   change.
2. Link to the corresponding implementation, tests, examples, or
   documentation; do not duplicate runtime logic.
3. Run the process in [`validation/README.md`](validation/README.md).
4. Do not add platform-specific copies of the skill text. Add thin metadata
   only when a host's current official documentation demonstrates it is
   required.

The distribution is covered by the repository's Apache License 2.0; see
[LICENSE](../LICENSE).
