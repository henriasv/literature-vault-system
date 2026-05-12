import { GlobalWorkerOptions, getDocument } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { convertFileSrc } from "@tauri-apps/api/core";
import { pdfPathFor } from "./vault";

GlobalWorkerOptions.workerSrc = workerUrl;

/** Resolve a citekey → an absolute file:// URL that pdfjs can fetch via Tauri's asset protocol. */
export async function pdfUrlFor(citekey: string): Promise<string> {
  const path = await pdfPathFor(citekey);
  return convertFileSrc(path);
}

/** Same but for a known absolute filesystem path — used for previews of
 *  PDFs that aren't yet filed (e.g. Inbox items in the CrossRef find modal). */
export function pdfUrlForPath(path: string): string {
  return convertFileSrc(path);
}

export type { PDFDocumentProxy, PDFPageProxy } from "pdfjs-dist";

export async function loadPdf(url: string) {
  return await getDocument({
    url,
    isEvalSupported: false,
    cMapUrl: undefined,
  }).promise;
}
