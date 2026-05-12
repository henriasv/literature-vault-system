# Two surfaces, one vault

The system has two surfaces — the macOS Viewer and the Telegram-based Librarian — over a single shared piece of state: a folder on disk.

This page is about the **why** of that shape. The shape itself is in [vault layout](../reference/vault-layout.md).

## The shape

```
┌──────────────────────────┐         ┌──────────────────────────┐
│  Viewer (macOS, Tauri)   │         │  Librarian (nanoclaw)    │
│  · deep reading          │         │  · phone intake          │
│  · note-writing          │         │  · chat queries          │
│  · semantic search       │         │  · async follow-up       │
└─────────────┬────────────┘         └────────────┬─────────────┘
              │                                   │
              ▼                                   ▼
              ┌──────────────────────────────────────┐
              │   Vault — a folder on disk           │
              │   PaperNotes/  Bibfiles/  PDFs/      │
              │   index.json   library.bib  …        │
              └──────────────────────────────────────┘
```

Both surfaces read and write the **same files**. There is no shared database, no shared cache, no shared service.

## Why two surfaces

Reading and noting and intake-and-async-follow-up are different tasks and want different ergonomics:

- **At the desk**, you want a big screen with PDF + notes side-by-side, keyboard shortcuts, real annotations on the PDF, multi-tab, search across the whole library. A desktop app is the right shape.
- **Away from the desk** (your colleague hands you a PDF, you read something on your phone, you remember a question on the train), you want to be able to push something into the library and follow up later. A chat bot is the right shape.

The two ergonomics don't share much UI. Building one shape and pretending it does both ends up bad at both.

## Why one vault

The thing you keep is the vault. Surfaces come and go.

- The Viewer is one possible reader. If you'd rather use Obsidian, the same folder opens cleanly there — it's just Markdown with YAML frontmatter.
- The Librarian is one possible bot. If you swap nanoclaw for some other agent framework, any framework that can read/write files in the layout works.
- If both surfaces vanish, you still have the papers, the notes, the BibTeX, and a deterministic index. You can open the folder in any text editor and it makes sense.

This is the opposite of a system where the "real" data lives in a SaaS database and the local view is a cache. Here the disk is the source of truth.

## Why the contract is a filesystem, not an API

A filesystem is the smallest possible coordination protocol. It gives you:

- **Atomic file writes** — both surfaces can mutate in parallel without locking, as long as each writer obeys "tempfile + rename" on a per-file basis.
- **Section ownership without versioning** — the Librarian only writes `## Why` / `## Notes` / `## Cleaned Notes`; the Viewer only writes the frontmatter you edit and the body you type. They never write the same bytes, so they never conflict.
- **No schema migrations** — adding a new section or frontmatter field is a one-line code change. Old notes still parse; tools that don't care about the new field just don't read it.
- **Boring, well-understood failure modes** — file not found, permission denied, disk full. No "cache stale", no "API breaking change", no "rate limited".

The cost is that operations are eventually consistent across surfaces. A new paper filed by the Librarian only shows up in the Viewer once its filesystem watcher fires. In practice, this latency is sub-second and invisible.

## Related

- [Files, not a database](files-not-database.md) — the corresponding decision about not introducing a DB.
- [The agent pattern](the-agent-pattern.md) — why the Librarian is a separate process you can swap out, not a library inside the Viewer.
