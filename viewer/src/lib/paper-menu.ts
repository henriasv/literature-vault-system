/**
 * Build the right-click menu for a paper row. Used in both Reading view
 * (Library.svelte) and Organizing view (CollectionsPanel.svelte), so the
 * affordance is consistent across the app.
 */

import { invoke } from "@tauri-apps/api/core";
import { writeText as clipboardWriteText } from "@tauri-apps/plugin-clipboard-manager";
import { readBibtex, pdfPathFor, paperMeta, type PaperMeta } from "./vault";
import { toast } from "../state/toast.svelte";
import { openReidentify } from "../state/reidentify.svelte";
import type { MenuItem } from "../state/ctxmenu.svelte";

/* Persisted across sessions in localStorage by NoteEditor's Export PDF
 * button. We honour the same value here so the user only has to pick
 * margin-vs-appendix once and it follows them between Export and Print. */
type ExportMode = "appendix" | "margin";
const EXPORT_MODE_KEY = "lv.exportMode";
function currentExportMode(): ExportMode {
  if (typeof localStorage === "undefined") return "margin";
  const v = localStorage.getItem(EXPORT_MODE_KEY) as ExportMode | null;
  return v === "appendix" ? "appendix" : "margin";
}

/* APA-ish: "Last, F., Last, F., & Last, F. (year). Title. Journal."
 * Authors arrive as "Last, First" (BibTeX convention) — we map them to
 * "Last, F." and join with comma + ampersand-before-last. Missing fields
 * are skipped silently so a sparse entry still produces something usable. */
function formatAuthorAPA(raw: string): string {
  const parts = raw.split(",").map((s) => s.trim());
  if (parts.length >= 2) {
    const last = parts[0];
    const initials = parts
      .slice(1)
      .join(" ")
      .split(/\s+/)
      .filter(Boolean)
      .map((n) => `${n[0].toUpperCase()}.`)
      .join(" ");
    return initials ? `${last}, ${initials}` : last;
  }
  /* "First Last" fallback for non-BibTeX inputs. */
  const tokens = raw.trim().split(/\s+/);
  if (tokens.length < 2) return raw.trim();
  const last = tokens[tokens.length - 1];
  const initials = tokens
    .slice(0, -1)
    .map((n) => `${n[0].toUpperCase()}.`)
    .join(" ");
  return `${last}, ${initials}`;
}

function formatCitationAPA(p: PaperMeta): string {
  const names = p.authors.map(formatAuthorAPA);
  let authors = "";
  if (names.length === 1) authors = names[0];
  else if (names.length > 1) authors = `${names.slice(0, -1).join(", ")}, & ${names[names.length - 1]}`;
  const etAl = p.authorCount !== undefined && p.authorCount > p.authors.length;
  if (etAl) authors = `${authors} et al.`;

  const title = (p.title || "").trim().replace(/\.$/, "");
  const venue = (p.journal || "").trim().replace(/\.$/, "");

  const head = authors ? `${authors} (${p.year}).` : `(${p.year}).`;
  const parts = [head];
  if (title) parts.push(`${title}.`);
  if (venue) parts.push(`${venue}.`);
  return parts.join(" ");
}

export function paperRowMenu(citekey: string): MenuItem[] {
  return [
    {
      label: "Copy BibTeX",
      onclick: () => {
        void (async () => {
          try {
            const bib = await readBibtex([citekey]);
            await clipboardWriteText(bib);
            toast(`Copied BibTeX for ${citekey}`);
          } catch (e) {
            toast(`Copy BibTeX failed: ${e}`, "error");
          }
        })();
      },
    },
    {
      label: "Copy formatted citation",
      onclick: () => {
        void (async () => {
          try {
            const meta = await paperMeta(citekey);
            const cite = formatCitationAPA(meta);
            await clipboardWriteText(cite);
            toast(`Copied citation for ${citekey}`);
          } catch (e) {
            toast(`Copy citation failed: ${e}`, "error");
          }
        })();
      },
    },
    {
      label: "Copy citekey",
      onclick: () => {
        void (async () => {
          try {
            await clipboardWriteText(citekey);
            toast(`Copied ${citekey}`);
          } catch (e) {
            toast(`Copy failed: ${e}`, "error");
          }
        })();
      },
    },
    {
      label: "Print PDF…",
      onclick: () => {
        void (async () => {
          try {
            const path = await pdfPathFor(citekey);
            await invoke("open_path_external", { path });
          } catch (e) {
            toast(`Print failed: ${e}`, "error");
          }
        })();
      },
    },
    {
      label: `Print with annotations… (${currentExportMode()})`,
      onclick: () => {
        void (async () => {
          try {
            const mode = currentExportMode();
            toast(`Preparing annotated PDF (${mode})…`);
            const res = await invoke<{ output: string }>("export_annotated_pdf", {
              citekey,
              mode,
            });
            await invoke("open_path_external", { path: res.output });
          } catch (e) {
            toast(`Print with annotations failed: ${e}`, "error");
          }
        })();
      },
    },
    {
      label: "Re-identify…",
      kind: "primary",
      onclick: () => openReidentify(citekey),
    },
  ];
}
