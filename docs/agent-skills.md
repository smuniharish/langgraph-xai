# Agent Skills

`langgraph-xai` publishes one portable Agent Skill that teaches coding agents
how to integrate, configure, test, and debug `langgraph-xai` in an
application. The skill is guidance for agents; it is not part of the Python
package and does not change how `langgraph-xai` is installed.

| Component | Location |
| --- | --- |
| langgraph-xai Python package | [`src/langgraph_xai/`](https://github.com/smuniharish/langgraph-xai/tree/master/src/langgraph_xai) |
| The Agent Skill | [`langgraph-xai-skills/skills/langgraph-xai/`](https://github.com/smuniharish/langgraph-xai/tree/master/langgraph-xai-skills/skills/langgraph-xai) |
| Its instructions | [`SKILL.md`](https://github.com/smuniharish/langgraph-xai/blob/master/langgraph-xai-skills/skills/langgraph-xai/SKILL.md) |

## What the skill contains

The skill follows the [Agent Skills specification](https://agentskills.io/specification).
Agents read `SKILL.md` first and open the other files only when a task needs
them:

- **`SKILL.md`**: when to use the skill, the core workflow, and the rules an
  integration follows. Its frontmatter has `name`, `description`, `license`,
  `compatibility`, and `metadata.version`, the `langgraph-xai` release it
  describes.
- **`references/API.md`**: public imports, runtime methods, settings, records,
  and provider contracts.
- **`references/RECIPES.md`**: complete patterns for instrumenting graphs and
  agents, human-in-the-loop, disclosure policies, storage, tracing backends,
  failure modes, and LLM-phrased explanations.
- **`references/TROUBLESHOOTING.md`**: symptoms, causes, and fixes.
- **`scripts/verify_setup.py`**: an offline check that the project's
  environment has compatible versions, and that a small instrumented graph
  records, explains, and links runs correctly.
- **`assets/test_disclosure_policy.py`**: a pytest template that tests what
  each audience may and may not see.

The repository validates the skill on every change: the reference validator,
link checks, the setup script, and the template run in its test suite. There
is no separate Claude, Codex, Cursor, or Copilot copy of the skill.

## Install from skills.sh

The [skills CLI](https://www.skills.sh/docs/cli) installs skills from a GitHub
source. Install the `langgraph-xai` skill directory directly:

```bash
npx skills add https://github.com/smuniharish/langgraph-xai/tree/master/langgraph-xai-skills/skills/langgraph-xai
```

This is the portable installation route. Follow the CLI's current target
selection prompts, then verify that it placed the `langgraph-xai` folder in
the target agent's supported skills directory. The shorthand
`npx skills add langgraph-xai-skills` is **not** a valid source identifier.

## Install manually

First obtain the canonical skill directory from the
[repository](https://github.com/smuniharish/langgraph-xai/tree/master/langgraph-xai-skills/skills/langgraph-xai).
Copy the complete `langgraph-xai` directory, including `SKILL.md`, into one
of the host-specific locations below.

### Claude Code

Claude Code discovers standalone skills in:

| Scope | Destination |
| --- | --- |
| Current repository | `.claude/skills/langgraph-xai/` |
| All local projects | `~/.claude/skills/langgraph-xai/` |

Start or restart Claude Code after copying the directory. Claude can select
the skill when its description matches the task, or you can invoke it with
`/langgraph-xai`. See [Claude Code Skills](https://code.claude.com/docs/en/skills).

`langgraph-xai` does not currently ship a Claude plugin manifest or marketplace
package. The standalone skill is sufficient today.

### Codex

Codex discovers repository skills by scanning `.agents/skills` from the
working directory to the repository root. Copy the directory to:

| Scope | Destination |
| --- | --- |
| Current repository | `.agents/skills/langgraph-xai/` |
| All local projects | `~/.agents/skills/langgraph-xai/` |

Codex detects changes automatically; restart it if the skill does not appear.
Invoke it explicitly with `$langgraph-xai` or use `/skills` to inspect
available skills. See [ChatGPT and Codex Skills](https://learn.chatgpt.com/docs/build-skills).

### Cursor

Cursor supports the standard `.agents/skills` locations, which makes the Codex
layout above portable. It also supports Cursor-specific locations:

| Scope | Destination |
| --- | --- |
| Current repository | `.agents/skills/langgraph-xai/` or `.cursor/skills/langgraph-xai/` |
| All local projects | `~/.agents/skills/langgraph-xai/` or `~/.cursor/skills/langgraph-xai/` |

Restart Cursor after copying the directory. In Agent chat, type `/` and select
`langgraph-xai` to attach it to a message; Cursor can also activate it from
its description. See [Cursor Agent Skills](https://cursor.com/docs/skills).

### GitHub Copilot

GitHub Copilot supports the standard `.agents/skills` layout, and also the
following project and personal locations:

| Scope | Destination |
| --- | --- |
| Current repository | `.agents/skills/langgraph-xai/`, `.github/skills/langgraph-xai/`, or `.claude/skills/langgraph-xai/` |
| All local projects | `~/.agents/skills/langgraph-xai/` or `~/.copilot/skills/langgraph-xai/` |

For Copilot CLI, start a new session or run `/skills reload`, then verify the
skill with `/skills info langgraph-xai`. You can explicitly request it in a
prompt using `/langgraph-xai`. See [Adding agent skills for GitHub Copilot
CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills).

### Other Agent Skills-compatible hosts

Use the host's documented skill directory and copy the complete
`langgraph-xai` folder there. The canonical skill relies only on the standard
`SKILL.md` frontmatter, so it does not require a host-specific adapter.

If a host needs package metadata, a registry entry, or a plugin manifest,
follow that host's current official documentation and add only a thin adapter
that points to this canonical skill. Do not duplicate the skill instructions.

## Update and verify

To update a manual installation, replace the complete installed
`langgraph-xai` folder with the latest directory from the repository, then
restart or reload the host.

After installation, confirm all of the following:

1. The directory name is `langgraph-xai`, and it contains `SKILL.md`,
   `references/`, `scripts/`, and `assets/`.
2. The host lists `langgraph-xai` as an available skill, if it exposes a
   skill listing command or UI.
3. From your project's Python environment, the setup check passes:

    ```bash
    python <skills directory>/langgraph-xai/scripts/verify_setup.py
    ```

    ```text
    PASS  Python 3.14.7 (3.12 or newer required)
    PASS  langgraph-xai 1.0.0 (1.x expected by this skill)
    PASS  langgraph 1.2.12 (>=1.2.12,<2 required)
    PASS  langchain-core 1.6.6 (>=1.6.6,<2 required)
    INFO  optional integrations: langsmith 0.14.4, langfuse 4.16.0, opentelemetry-sdk 1.45.0, langchain-openai 1.6.7
    PASS  instrumented graph recorded nodes ['score', 'route'], 2 state changes, 1 evidence, 1 decision
    PASS  auditor explanation: The routing decision selected 'REVIEW'.
    PASS  end-user explanation withholds the score and announces it
    PASS  no instrumentation errors (0 recorded)
    PASS  interrupt and resume recorded and linked through the checkpoint
    All checks passed.
    ```

4. A task about LangGraph explainability, provenance, evidence, decisions,
   disclosure policy, or instrumentation activates the skill, or you can
   invoke it explicitly.

See the distribution's
[README](https://github.com/smuniharish/langgraph-xai/blob/master/langgraph-xai-skills/README.md)
and [validation process](https://github.com/smuniharish/langgraph-xai/blob/master/langgraph-xai-skills/validation/README.md)
for maintenance details.
