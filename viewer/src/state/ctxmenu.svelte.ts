/**
 * Global context-menu state. One menu can be open at a time; the
 * <ContextMenu /> component mounted at the App root reads this and renders.
 * Any view that wants a right-click menu calls `openCtxMenu(x, y, items)`.
 */

export interface MenuItem {
  label: string;
  /** Click handler. The menu closes automatically before calling. */
  onclick: () => void;
  /** Stylistic accent — keep accent for primary, danger for destructive. */
  kind?: "primary" | "default" | "danger";
  /** Disable rendering as a clickable row (useful for greyed-out items). */
  disabled?: boolean;
}

interface CtxMenuState {
  open: boolean;
  x: number;
  y: number;
  items: MenuItem[];
}

export const ctxMenuState = $state<CtxMenuState>({
  open: false,
  x: 0,
  y: 0,
  items: [],
});

export function openCtxMenu(x: number, y: number, items: MenuItem[]): void {
  ctxMenuState.x = x;
  ctxMenuState.y = y;
  ctxMenuState.items = items;
  ctxMenuState.open = true;
}

export function closeCtxMenu(): void {
  ctxMenuState.open = false;
  ctxMenuState.items = [];
}
