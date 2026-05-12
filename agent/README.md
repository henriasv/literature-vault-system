# Librarian agent template

The bits that install into a nanoclaw group when you run `setup/install-agent.sh`. The script copies these into `~/repos/nanoclaw/groups/<group-name>/` (default `librarian`) and fills in the placeholders.

The agent is optional — the Viewer works fine without it. Install only if you want Telegram-based intake.

- **Installing:** [how-to: install the Librarian agent](../docs/how-to/install-the-librarian-agent.md).
- **Full contract (triggers, hard rules, what it sees):** [reference: agent](../docs/reference/agent.md).

## Files in this directory

| File | What it is |
|---|---|
| `CLAUDE.local.md` | The agent's system prompt. Generic — no per-user content. Add a `## Personal context` section at the bottom after install if you want the agent to know about your projects. |
| `container.json.template` | Mount + group-name template. Placeholders rendered by `setup/install-agent.sh`. |

See the reference doc for the placeholder list and what the agent sees inside the container.
