/**
 * Highlight color palette for PDF annotations. Single source of truth — used
 * both as the annotation plugin's `colorPresets` config and as the colour
 * swatches our toolbar renders.
 *
 * Chosen for legibility against the cream/white PDF backgrounds:
 *   - Yellow  — generic emphasis (default)
 *   - Green   — agreement / good evidence
 *   - Blue    — supporting reference
 *   - Pink    — disagreement / weak point
 *
 * If we ever want named semantics, swap to an object map; the array form
 * is fine for v1.
 */
export const HIGHLIGHT_COLORS = [
  "#FFEB3B", // yellow
  "#A5D6A7", // green
  "#90CAF9", // blue
  "#F8BBD0", // pink
] as const;

export type HighlightColor = (typeof HIGHLIGHT_COLORS)[number];
