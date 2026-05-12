/**
 * State for the "Re-identify with CrossRef" modal. Carries the citekey of the
 * filed paper being re-identified; ReidentifyModal mounted at the App root
 * reads this and renders when set.
 */

interface ReidentifyState {
  citekey: string | null;
}

export const reidentifyState = $state<ReidentifyState>({ citekey: null });

export function openReidentify(citekey: string): void {
  reidentifyState.citekey = citekey;
}

export function closeReidentify(): void {
  reidentifyState.citekey = null;
}
