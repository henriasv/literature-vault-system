/**
 * State for the post-drop metadata sheet in Reviewing mode. After
 * `dropToReviewProject` files PDFs with filename-derived metadata, this
 * holds the just-filed papers so the user can immediately fix title /
 * authors before moving on. Dismiss → keep filename-derived defaults.
 */

export interface ReviewMetaDraft {
  /** `review:<project>:<stem>` — the synthetic citekey we'll write back to. */
  citekey: string;
  /** Filename stem before any user edit. Used in the modal subtitle so the
   *  user can correlate the row with what they just dropped. */
  sourceName: string;
  /** Editable title field. Pre-filled from filename, humanised. */
  title: string;
  /** Editable comma-separated authors. Pre-filled empty. */
  authors: string;
}

interface ReviewMetaState {
  drafts: ReviewMetaDraft[];
}

export const reviewMetaEditState = $state<ReviewMetaState>({ drafts: [] });

export function openReviewMetaSheet(drafts: ReviewMetaDraft[]): void {
  reviewMetaEditState.drafts = drafts;
}

export function closeReviewMetaSheet(): void {
  reviewMetaEditState.drafts = [];
}
