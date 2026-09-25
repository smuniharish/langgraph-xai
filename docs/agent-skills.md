# Agent Skills

`langgraph-xai` publishes one portable Agent Skill that teaches coding agents
how to integrate, configure, debug, test, and operate the existing
`langgraph-xai` runtime. The skill is documentation and procedural guidance;
it is not a Python runtime component and does not change how
`langgraph-xai` is installed.

| Component | Location |
| --- | --- |
| langgraph-xai Python runtime | [`src/langgraph_xai/`](https://github.com/smuniharish/langgraph-xai/tree/main/src/langgraph_xai) |
| Canonical Agent Skill | [`langgraph-xai-skills/skills/langgraph-xai/`](https://github.com/smuniharish/langgraph-xai/tree/main/langgraph-xai-skills/skills/langgraph-xai) |
| Canonical instructions | [`SKILL.md`](https://github.com/smuniharish/langgraph-xai/blob/main/langgraph-xai-skills/skills/langgraph-xai/SKILL.md) |

The skill follows the [Agent Skills specification](https://agentskills.io/specification)
and contains the required `name` and `description` frontmatter. There is no
separate Claude, Codex, Cursor, or Copilot copy of the skill.

## Install from skills.sh

The [skills CLI](https://www.skills.sh/docs/cli) installs skills from a GitHub
source. Install the `langgraph-xai` skill directory directly:

```bash
npx skills add https://github.com/smuniharish/langgraph-xai/tree/main/langgraph-xai-skills/skills/langgraph-xai
```

This is the portable installation route. Follow the CLI's current target
selection prompts, then verify that it placed the `langgraph-xai` folder in
the target agent's supported skills directory. The shorthand
`npx skills add langgraph-xai-skills` is **not** a valid source identifier.

## Install manually

First obtain the canonical skill directory from the
[repository](https://github.com/smuniharish/langgraph-xai/tree/main/langgraph-xai-skills/skills/langgraph-xai).
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

1. The directory name is `langgraph-xai`.
2. `SKILL.md` is present in that directory.
3. The host lists `langgraph-xai` as an available skill, if it exposes a
   skill listing command or UI.
4. A task about LangGraph explainability, provenance, evidence, decisions,
   disclosure policy, or instrumentation activates or can explicitly invoke
   the skill.

See the distribution's
[README](https://github.com/smuniharish/langgraph-xai/blob/main/langgraph-xai-skills/README.md)
and [validation process](https://github.com/smuniharish/langgraph-xai/blob/main/langgraph-xai-skills/validation/README.md)
for maintenance details.
