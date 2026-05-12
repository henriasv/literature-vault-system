# Known limitations

Things that don't work yet, or work in a rough way. Listed here so the rest of the docs can be honest about scope.

## Platform

- **Apple Silicon Mac only.** Intel Macs aren't supported (Homebrew prefix is wrong; some install paths assume `/opt/homebrew/`). Linux and Windows are conceivable later but not started.
- **No signed `.dmg`.** You build the Viewer from source.

## Viewer

- **Per-tab scroll/zoom/page state isn't persisted across launches.** It used to be wired for the legacy pdfjs reader; nothing is wired for EmbedPDF yet.
- **PDFium memory leak.** `PDFiumEngine.MemoryManager` logs an unfreed ~50 MB allocation on every document close. Hasn't caused user-visible problems, but flipping through many tabs in a long session will eventually eat RAM. Likely an EmbedPDF-side issue.
- **No PDF rotation support.** `EmbedPageAnnotations` hardcodes `rotation={0}`. Hit a rotated PDF and overlays drift.
- **No annotation export pipeline.** `scripts/export_paper.py` is planned (flatten the sidecar JSON into XFDF, splat it into the PDF via PDFium, then append the rendered Markdown note). Not started.

## Vault tooling

- **No bulk-rebuild helper for the dedup index in adopt mode.** [How-to: adopt existing papers](how-to/adopt-existing-papers.md) currently asks you to re-file each PDF through `file_paper.py --in-place`. A bulk script would be nice.
- **SI surfacing isn't wired into the Viewer.** The convention is `SI/{citekey}-SI.pdf` (one supplementary-information PDF per paper) and the Librarian already moves files there. How the Viewer surfaces them (sidebar badge? toggle in the PDF pane? separate tab?) is undecided.

## Operational

- **`embeddings.db` is SQLite.** It must stay on local storage — cloud-synced SQLite corrupts. The default `.gitignore` excludes it; don't move it under Dropbox/Drive/iCloud.
- **No multi-machine sync.** The vault works fine on a single machine. Sharing it across machines is something you do yourself (git, rsync, Syncthing — your call).
- **Agent doesn't push.** The Librarian auto-commits to the vault's git repo when one exists, but it never pushes. You push.
