# langgraph-xai Agent Skill validation

This directory documents the repeatable validation process for the canonical
skill. It is intentionally not a second runtime test suite and does not
provide a host-specific package.

The [Agent Skills specification](https://agentskills.io/specification) defines
`name` and `description` as the required frontmatter. No official validator is
specified there, so validation combines structural checks with source-backed
content review.

## Structural validation

For every change:

1. Confirm [`../skills/langgraph-xai/SKILL.md`](../skills/langgraph-xai/SKILL.md)
   exists and starts with YAML frontmatter.
2. Confirm `name` is exactly `langgraph-xai` (the directory name), contains
   only lowercase letters and hyphens, and is at most 64 characters.
3. Confirm `description` is non-empty, at most 1,024 characters, and states
   both the capability and when to activate it.
4. Confirm only `name` and `description` appear in frontmatter unless the
   current specification and a demonstrated host requirement justify more.
5. Resolve every relative Markdown target in the skill, this README, and the
   distribution README; no target may point to a deleted file.
6. Confirm the distribution contains one `skills/langgraph-xai/` canonical
   knowledge source and no Claude/Codex/Copilot duplicate.
7. Search the distribution for stale package names, invented CLI commands,
   credentials, chain-of-thought collection guidance, and unrelated projects.

## Source-accuracy review

Review every code snippet and factual claim against its source:

| Claim area | Source of truth |
| --- | --- |
| Public imports and package version | [`src/langgraph_xai/__init__.py`](../../src/langgraph_xai/__init__.py) and [`pyproject.toml`](../../pyproject.toml) |
| Runtime construction, defaults, registration, and recording | [`src/langgraph_xai/runtime/runtime.py`](../../src/langgraph_xai/runtime/runtime.py) |
| Configuration and failure behavior | [`src/langgraph_xai/config.py`](../../src/langgraph_xai/config.py), [configuration](../../docs/operations/configuration.md), and [failure modes](../../docs/how-to/failure-modes.md) |
| LangGraph invocation and interrupt behavior | [`src/langgraph_xai/instrumentation/graph.py`](../../src/langgraph_xai/instrumentation/graph.py) and [LangGraph integration](../../docs/integrations/langgraph.md) |
| Policy and security boundaries | [disclosure policies](../../docs/how-to/disclosure-policies.md) and [security](../../docs/operations/security.md) |
| Executable workflows | [`examples/`](../../examples/) and [`tests/`](../../tests/) |

If a behavior lacks an implementation, test, or authoritative document, omit
it from the skill rather than infer an API.

## Agent-task matrix

The following matrix is reviewed against the canonical
[`SKILL.md`](../skills/langgraph-xai/SKILL.md), its source links, the runtime
implementation, and the linked examples/tests.

| Task | Activates | Grounded route | Avoids |
| --- | --- | --- | --- |
| “Add explainability to my LangGraph agent.” | Yes | LangGraph integration guide → compiled graph instrumentation. | Replacing graph control flow or changing inputs/outputs. |
| “Explain why the agent selected this action.” | Yes | Explicit `record_decision` and `ExplanationContext` workflow. | Inferring private reasoning from a trace. |
| “Add a post-run explanation to a web handler.” | Yes | Post-run explanation guide → manual run lifecycle. | Mixing manual and automatic instrumentation for the same call. |
| “Capture a human approval interrupt and resume.” | Yes | Interrupt guide and instrumentation behavior. | Custom duplicate lifecycle bookkeeping. |
| “Store provenance in PostgreSQL and export traces.” | Yes | Storage and observability documentation plus provider registration. | Implicit credentials or unreviewed disclosure. |
| “An explanation exporter reveals sensitive fields.” | Yes | Disclosure-policy and security documentation. | Weakening redaction to make an export pass. |
| “The graph succeeds but no explanation appears.” | Yes | Failure-mode and troubleshooting workflow. | Treating graph and explainability outcomes as identical. |
| “Build a new workflow agent with chain-of-thought traces.” | No | Explain that this package is not an agent framework or chain-of-thought recorder. | Inventing unsupported capabilities. |

## Repository validation

Skill-only work should run the structural/link/source review above and inspect
the resulting Git diff. If runtime files change, run the CI-equivalent checks
documented in [CONTRIBUTING.md](../../CONTRIBUTING.md). This distribution must
not require a `langgraph-xai` runtime change.
