"use client";

/**
 * Interactive primitives.
 *
 * `Dialog` is the native `<dialog>` opened with `showModal()`: the browser
 * supplies the focus trap, the inert background, Escape to close and focus
 * return, which no hand-rolled modal gets right everywhere. Destructive
 * actions confirm in the page - `window.confirm()` blocks the tab and the
 * browser automation that tests it.
 */

import { useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { Printer, X } from "lucide-react";

import { ApiError } from "@/lib/api/client";
import { Button, type ButtonSize, type ButtonTone, cx } from "./primitives";

/** The message an API failure should show, worded by the server when it can be. */
export function failureMessage(cause: unknown, fallback: string): string {
  return cause instanceof ApiError ? cause.message : fallback;
}

/**
 * Run an API action, then refresh the server-rendered page. Nothing is
 * updated optimistically: the screen never shows a change the server has not
 * accepted.
 */
export function useAction() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const run = useCallback(
    async <T,>(action: () => Promise<T>, fallback = "The request failed."): Promise<T | undefined> => {
      setPending(true);
      setError(null);
      try {
        const result = await action();
        router.refresh();
        return result;
      } catch (cause) {
        setError(failureMessage(cause, fallback));
        return undefined;
      } finally {
        setPending(false);
      }
    },
    [router],
  );
  return { error, pending, run, setError };
}

// -- Dialog ------------------------------------------------------------------

export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = "md",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  size?: "md" | "lg";
}) {
  const ref = useRef<HTMLDialogElement | null>(null);
  const titleId = useId();

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (open && !node.open) node.showModal();
    if (!open && node.open) node.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        // A click on the backdrop lands on the dialog element itself.
        if (event.target === ref.current) onClose();
      }}
      className={cx(
        "m-auto w-[calc(100%-1.5rem)] rounded-xl border border-line bg-bg p-0 text-text shadow-pop",
        "backdrop:bg-black/40 backdrop:backdrop-blur-[2px]",
        size === "lg" ? "max-w-2xl" : "max-w-lg",
      )}
    >
      {open ? (
        <div className="flex max-h-[85dvh] flex-col">
          <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
            <div className="min-w-0">
              <h2 id={titleId} className="text-[16px] font-semibold tracking-[-0.01em]">
                {title}
              </h2>
              {description ? <p className="mt-1 text-[13px] leading-relaxed text-text-3">{description}</p> : null}
            </div>
            <button
              type="button"
              onClick={onClose}
              className="-mr-1.5 flex size-9 shrink-0 items-center justify-center rounded-md text-text-3 hover:bg-bg-sunk hover:text-text"
            >
              <X aria-hidden="true" className="size-4" />
              <span className="sr-only">Close</span>
            </button>
          </header>
          <div className="min-h-0 overflow-y-auto px-5 py-4">{children}</div>
          {footer ? (
            <footer className="flex flex-wrap justify-end gap-2 border-t border-line bg-bg-soft px-5 py-3">{footer}</footer>
          ) : null}
        </div>
      ) : null}
    </dialog>
  );
}

// -- Confirm in place --------------------------------------------------------

/**
 * A destructive action that asks once in the page before it sends anything.
 * `consequence` says exactly what will be lost.
 */
export function ConfirmAction({
  label,
  confirmLabel,
  consequence,
  onConfirm,
  tone = "danger",
  size = "sm",
  disabled,
}: {
  label: string;
  confirmLabel: string;
  consequence: string;
  onConfirm: () => Promise<unknown> | void;
  tone?: ButtonTone;
  size?: ButtonSize;
  disabled?: boolean;
}) {
  const [asking, setAsking] = useState(false);
  const [pending, setPending] = useState(false);
  if (!asking) {
    return (
      <Button size={size} tone="secondary" disabled={disabled} onClick={() => setAsking(true)}>
        {label}
      </Button>
    );
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <span className="text-[12px] text-text-3">{consequence}</span>
      <Button
        size={size}
        tone={tone}
        disabled={pending}
        onClick={async () => {
          setPending(true);
          try {
            await onConfirm();
          } finally {
            setPending(false);
            setAsking(false);
          }
        }}
      >
        {pending ? "Working…" : confirmLabel}
      </Button>
      <Button size={size} tone="ghost" disabled={pending} onClick={() => setAsking(false)}>
        Keep it
      </Button>
    </span>
  );
}

// -- Tabs --------------------------------------------------------------------

/**
 * Client tabs with the ARIA tabs pattern: arrow keys move between tabs,
 * Home/End jump, only the selected tab is in the tab order.
 */
export function Tabs({
  label,
  tabs,
  value,
  onChange,
}: {
  label: string;
  tabs: { id: string; label: ReactNode; badge?: ReactNode }[];
  value: string;
  onChange: (id: string) => void;
}) {
  const idBase = useId();
  const refs = useRef<Array<HTMLButtonElement | null>>([]);
  function onKey(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = tabs.length - 1;
    else return;
    event.preventDefault();
    onChange(tabs[next].id);
    refs.current[next]?.focus();
  }
  return (
    <div role="tablist" aria-label={label} className="flex gap-1 overflow-x-auto border-b border-line">
      {tabs.map((tab, index) => {
        const selected = tab.id === value;
        return (
          <button
            key={tab.id}
            ref={(node) => {
              refs.current[index] = node;
            }}
            type="button"
            role="tab"
            id={`${idBase}-${tab.id}`}
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(tab.id)}
            onKeyDown={(event) => onKey(event, index)}
            className={cx(
              "-mb-px inline-flex h-10 shrink-0 items-center gap-2 border-b-2 px-3 text-[13px] font-medium transition-colors",
              selected ? "border-accent text-text" : "border-transparent text-text-3 hover:text-text",
            )}
          >
            {tab.label}
            {tab.badge}
          </button>
        );
      })}
    </div>
  );
}

// -- Print -------------------------------------------------------------------

/** Save the page as PDF through the browser's print dialog and the print stylesheet. */
export function PrintButton({ label = "Save as PDF" }: { label?: string }) {
  return (
    <Button size="sm" tone="secondary" onClick={() => window.print()} className="no-print">
      <Printer aria-hidden="true" className="size-3.5" />
      {label}
    </Button>
  );
}
