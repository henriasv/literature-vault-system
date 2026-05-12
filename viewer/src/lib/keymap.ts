/**
 * Tiny keybinding dispatcher. A binding is a string like "Mod+T", "Mod+Shift+W",
 * "Mod+Alt+ArrowRight", "Mod+\\", or "/". `Mod` resolves to ⌘ on Mac and Ctrl elsewhere.
 *
 * The dispatcher matches against `KeyboardEvent.code` for letters/digits/arrows so it's
 * keyboard-layout-stable, and against `event.key` for printable chars like `/` and `\`.
 */

export interface KeyBinding {
  /** Stop propagation + prevent default if the handler ran. */
  preventDefault?: boolean;
  /** Skip if focus is inside an input / contenteditable / CodeMirror. */
  allowInEditableTargets?: boolean;
  run: (e: KeyboardEvent) => void;
}

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

interface Parsed {
  mod: boolean;
  shift: boolean;
  alt: boolean;
  ctrl: boolean;
  /** Either a `code` like "KeyT" / "Digit1" / "ArrowRight" or a literal `key` like "/", "\\". */
  key: string;
  isCode: boolean;
}

function parse(spec: string): Parsed {
  const parts = spec.split("+");
  const out: Parsed = {
    mod: false,
    shift: false,
    alt: false,
    ctrl: false,
    key: "",
    isCode: false,
  };
  for (const part of parts) {
    const p = part.trim();
    if (p === "Mod") out.mod = true;
    else if (p === "Shift") out.shift = true;
    else if (p === "Alt") out.alt = true;
    else if (p === "Ctrl") out.ctrl = true;
    else {
      // Letter/digit/arrow → match by code; printable punctuation → match by key.
      if (/^[A-Z]$/i.test(p)) {
        out.key = `Key${p.toUpperCase()}`;
        out.isCode = true;
      } else if (/^[0-9]$/.test(p)) {
        out.key = `Digit${p}`;
        out.isCode = true;
      } else if (p === "ArrowLeft" || p === "ArrowRight" || p === "ArrowUp" || p === "ArrowDown") {
        out.key = p;
        out.isCode = true;
      } else {
        out.key = p;
        out.isCode = false;
      }
    }
  }
  return out;
}

function matches(e: KeyboardEvent, p: Parsed): boolean {
  const modPressed = isMac ? e.metaKey : e.ctrlKey;
  if (p.mod !== modPressed) return false;
  if (p.shift !== e.shiftKey) return false;
  if (p.alt !== e.altKey) return false;
  if (!isMac && p.ctrl !== e.ctrlKey) return false;
  return p.isCode ? e.code === p.key : e.key === p.key;
}

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (target.closest(".cm-editor")) return true;
  return false;
}

export function makeKeymap(map: Record<string, KeyBinding>): (e: KeyboardEvent) => void {
  const compiled: Array<[Parsed, KeyBinding]> = Object.entries(map).map(([spec, binding]) => [
    parse(spec),
    binding,
  ]);
  return (e: KeyboardEvent) => {
    const editable = isEditable(e.target);
    for (const [p, b] of compiled) {
      if (!matches(e, p)) continue;
      if (editable && !b.allowInEditableTargets) continue;
      b.run(e);
      if (b.preventDefault !== false) {
        e.preventDefault();
        e.stopPropagation();
      }
      return;
    }
  };
}
