# literature-vault-system

A self-hosted reading + organising system for academic papers. Two surfaces share one folder on disk:

- **Viewer** — a macOS desktop app (Tauri + Svelte) for reading PDFs and editing Markdown notes side-by-side.
- **Librarian** — an optional Telegram bot (a [nanoclaw](https://github.com/henriasv/nanoclaw) agent) for filing PDFs and asking library questions from your phone.

Both operate on the same on-disk **vault**: PDFs, BibTeX entries, one Markdown note per paper, plus user-curated collections. The contract between surfaces is the filesystem — nothing else.

## Where to go next

- **New here?** → [Tutorial: getting started](docs/tutorial/getting-started.md)
- **Looking up how to do a thing?** → [How-to guides](docs/how-to/)
- **Looking up exact details?** → [Reference](docs/reference/)
- **Curious why it's shaped this way?** → [Explanation](docs/explanation/)

## Status

Pre-1.0. Built as a personal tool; sharing-friendly but not a polished product. macOS-only for now. No signed `.dmg` — you build from source.

See [Known limitations](docs/KNOWN_LIMITATIONS.md) for what isn't built yet.

## License

[MIT](LICENSE).
