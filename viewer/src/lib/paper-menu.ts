/**
 * Build the right-click menu for a paper row. Used in both Reading view
 * (Library.svelte) and Organizing view (CollectionsPanel.svelte), so the
 * affordance is consistent across the app.
 */

import { writeText as clipboardWriteText } from "@tauri-apps/plugin-clipboard-manager";
import { readBibtex, paperMeta, type PaperMeta } from "./vault";
import { toast } from "../state/toast.svelte";
import { openReidentify } from "../state/reidentify.svelte";
import type { MenuItem } from "../state/ctxmenu.svelte";

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
      label: "Re-identify…",
      kind: "primary",
      onclick: () => openReidentify(citekey),
    },
  ];
}
