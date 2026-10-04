# Validating the langgraph-xai skill

## Automated checks

Run from the repository root:

```bash
uv run pytest tests/skill
uvx --from skills-ref agentskills validate langgraph-xai-skills/skills/langgraph-xai
```

`tests/skill` runs offline in continuous integration. It checks that:

- the skill passes the reference validator, `skills-ref`, which applies the
  specification's rules for `name`, `description`, `compatibility`, and the
  other frontmatter fields;
- `name` matches the directory, `license` is `Apache-2.0`, and
  `metadata.version` equals the package version;
- `SKILL.md` has fewer than 500 lines, and `references/` is one level deep;
- every relative link in the skill resolves;
- `scripts/verify_setup.py` passes, with warnings treated as errors;
- `assets/test_disclosure_policy.py` passes.

## Source review

Automated checks cannot tell whether guidance is correct. For every change,
check each snippet and claim against its source:

| Claim area | Source of truth |
| --- | --- |
| Public imports, signatures, and the package version | [`src/langgraph_xai/__init__.py`](../../src/langgraph_xai/__init__.py), [`pyproject.toml`](../../pyproject.toml), and the [API reference](../../docs/api/index.md) |
| Runtime construction, recording, and explanations | [`src/langgraph_xai/runtime/runtime.py`](../../src/langgraph_xai/runtime/runtime.py) |
| Configuration and failure behavior | [`src/langgraph_xai/config.py`](../../src/langgraph_xai/config.py), [configuration](../../docs/getting-started/configuration.md), and [failure modes](../../docs/how-to/failure-modes.md) |
| Entry points, interrupts, and checkpoints | [`src/langgraph_xai/instrumentation/graph.py`](../../src/langgraph_xai/instrumentation/graph.py), the [LangGraph integration](../../docs/integrations/langgraph.md), and [interrupts](../../docs/how-to/interrupts.md) |
| Disclosure and security | [disclosure policies](../../docs/how-to/disclosure-policies.md) and [security](../../docs/operations/security.md) |
| Working patterns | [`examples/`](../../examples/) and [`tests/`](../../tests/) |

If a behavior has no implementation, test, or documentation, leave it out of
the skill rather than infer it.

## Activation matrix

Review that the description and instructions lead an agent to the right
route for each task:

| Task | Activates | Route | Avoids |
| --- | --- | --- | --- |
| "Add explainability to my LangGraph agent." | Yes | Core workflow: instrument the compiled graph, record evidence and decisions in nodes. | Changing graph inputs, outputs, or control flow. |
| "Explain why the agent chose this action." | Yes | `record_decision` where the choice is made, then `collect_runs` and `explain_decision`. | Inferring reasoning from a trace or asking for chain-of-thought. |
| "Show customers a reason but not our risk score." | Yes | A `PolicyProvider` and the disclosure-policy test template. | Weakening the policy to make a test pass. |
| "Record the reviewer's approval and the resumed run." | Yes | A checkpointer and `thread_id`; interrupts, checkpoints, and `continuation_of` are automatic; `record_human_interaction` for outside approvals. | Calling `record_checkpoint` for instrumented checkpointed graphs. |
| "Store the records in PostgreSQL and send events to OpenTelemetry." | Yes | A `ProvenanceStore` subclass from the PostgreSQL store example, a plugin for evidence and decisions, and an observability adapter. | Credentials in records or code. |
| "The graph works but no run is recorded." | Yes | Troubleshooting: uninstrumented graph, unrecorded entry points, derived runnables. | Disabling instrumentation checks. |
| "Build a new agent framework that logs chain-of-thought." | No | Not this package's purpose. | Inventing capabilities. |
