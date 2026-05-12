interface Toast {
  id: number;
  message: string;
  kind: "info" | "error";
}

interface ToastState {
  items: Toast[];
}

export const toastState = $state<ToastState>({ items: [] });

let nextId = 1;

export function toast(message: string, kind: "info" | "error" = "info", durationMs = 4000): void {
  const id = nextId++;
  toastState.items = [...toastState.items, { id, message, kind }];
  window.setTimeout(() => {
    toastState.items = toastState.items.filter((t) => t.id !== id);
  }, durationMs);
}
