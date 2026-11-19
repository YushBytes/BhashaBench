"use client";

/**
 * Save the current page as PDF through the browser's own print dialog.
 * The print stylesheet in globals.css lightens the palette and hides the
 * chrome and controls; the evidence on the page is printed as shown.
 */

import { buttonClass } from "@/components/ui/primitives";

export function PrintButton({ label = "Print / save as PDF" }: { label?: string }) {
  return (
    <button
      type="button"
      data-print-hide
      onClick={() => window.print()}
      className={buttonClass("default", "sm")}
    >
      {label}
    </button>
  );
}
