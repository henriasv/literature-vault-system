/**
 * Build the right-click menu for a paper row. Used in both Reading view
 * (Library.svelte) and Organizing view (CollectionsPanel.svelte), so the
 * affordance is consistent across the app.
 */

import { writeText as clipboardWriteText } from "@tauri-apps/plugin-clipboard-manager";
import { readBibtex } from "./vault";
import { toast } from "../state/toast.svelte";
import { openReidentify } from "../state/reidentify.svelte";
import type { MenuItem } from "../state/ctxmenu.svelte";

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
