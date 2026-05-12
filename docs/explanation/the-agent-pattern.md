# The agent pattern

The Librarian is a separate process. It runs in a Docker container, talks to you over Telegram, and reads/writes the same vault the Viewer does. It is not a library inside the Viewer, and it is not a SaaS service.

This page is about why that shape is right for an LLM-powered helper.

## The split: scripts vs agent

Inside the system there are two kinds of code:

- **Deterministic scripts** (`scripts/*.py`) — DOI extraction, citekey minting, BibTeX writing, dedup, embedding indexing. Anything that's a pure function of inputs and that can be tested with `pytest`.
- **The agent** (`agent/CLAUDE.local.md`) — deciding *which* paper a free-text reply refers to, fuzzy CrossRef searches when a PDF has no DOI, composing a TL;DR for a chat reply, picking tag suggestions from neighboring papers.

The scripts don't need an LLM, so they don't have one. The agent doesn't need to reimplement what scripts already do — and per the agent's hard rules, it doesn't. The Librarian's job is the *judgment* layer: choose which deterministic call to make, compose the reply, ask for clarification when the input is ambiguous.

This split keeps the surface area of LLM-shaped errors small. A misidentified citekey is recoverable; a corrupt `index.json` is much worse. By putting all state-changing operations behind scripts, the worst thing the agent can do is pick the wrong script — not corrupt the vault.

## Why a separate process

Two reasons:

**Different runtime, different ergonomics.** The Viewer is a Tauri app on macOS — it needs to feel like a native desktop app, with a low-latency UI thread. The Librarian is a chat backend — it needs a sandboxed container, a queue of incoming Telegram messages, an API key for Anthropic, and tolerance for occasional 30 s response times. Running both inside the Viewer would force one to live with the other's constraints.

**Async by nature.** Phone intake is a fire-and-forget interaction. You send a PDF, the agent files it over the next minute, and it replies when done. You don't sit and wait. The Viewer, by contrast, is a synchronous tool — you click, something happens. Putting the async-y agent inside the sync-y Viewer would either block the UI or require a queue inside the Viewer. Both are worse than just running the agent elsewhere.

## Why nanoclaw specifically

[nanoclaw](https://github.com/henriasv/nanoclaw) is a thin orchestrator for Claude-based agents bound to chat surfaces. It handles:

- The Telegram (or Slack, Discord, iMessage) glue.
- The Docker container lifecycle.
- Mount allowlists and a basic sandbox.
- Loading per-group `CLAUDE.local.md` configurations.

The Librarian is just one nanoclaw "group". The same nanoclaw install can host multiple groups for different chats and different purposes; the Librarian doesn't know or care.

This is the right level of "framework" for the job. If you'd rather use a different framework (langgraph, your own Claude wrapper, plain shell scripts behind a webhook), the only thing it has to do is invoke the scripts in `/workspace/extra/system/scripts/` and obey the same hard rules. The contract is the filesystem.

## What the Librarian buys you over scripts alone

You could file papers from the command line — `uv run scripts/file_paper.py --pdf foo.pdf --doi 10.…`. So why have the agent at all?

- **Phone reach.** You can file a paper from anywhere. You can't run `scripts/file_paper.py` from a phone (well, not comfortably).
- **Disambiguation.** When a PDF has no DOI, picking which CrossRef result matches is a judgment call. A script can return candidates; an agent can decide.
- **Conversational notes.** "Bouchbinder cites this in §4 of his 2014 review as the cleanest evidence for LEFM breakdown" → `append_note.py` puts it in `## Notes`, and `## Cleaned Notes` gets re-synthesized. That whole flow is one chat message on the user's side.
- **Library queries by chat.** "What do I have on detachment fronts?" — embedding search + a reasoned, citekey-keyed reply. Same as you could do at the terminal, but at the speed of a Telegram message.

If you don't want any of that, you can skip the Librarian entirely. The Viewer handles desktop intake on its own — drop a PDF on the window, same pipeline runs, same files appear.

## Related

- [Two surfaces, one vault](two-surfaces-one-vault.md) — why the agent shares state with the Viewer through the filesystem.
- [Reference: agent](../reference/agent.md) — the precise contract.
