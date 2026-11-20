/**
 * Form controls. A `Field` owns the label, the hint and the error, and wires
 * them to the control with `aria-describedby` and `aria-invalid`, so an error
 * is announced with the field it belongs to rather than somewhere on the page.
 *
 * Native elements throughout: a native `<select>` is keyboard- and
 * screen-reader-correct on every platform, and on a phone it opens the
 * system picker, which no custom listbox matches.
 */

import { Children, cloneElement, isValidElement, type ComponentProps, type ReactElement, type ReactNode } from "react";

import { cx } from "./primitives";

export const controlClass =
  "block w-full min-w-0 rounded-md border border-line-strong bg-bg px-3 text-[14px] text-text shadow-1 " +
  "transition-[border-color,box-shadow] placeholder:text-text-3 hover:border-text-3 " +
  "focus-visible:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/25 " +
  "disabled:cursor-not-allowed disabled:bg-bg-sunk disabled:text-text-3 " +
  "aria-[invalid=true]:border-bad aria-[invalid=true]:ring-bad/20";

export function Input({ className, ...rest }: ComponentProps<"input">) {
  return <input className={cx(controlClass, "h-9", className)} {...rest} />;
}

export function Select({ className, children, ...rest }: ComponentProps<"select">) {
  return (
    <select className={cx(controlClass, "h-9 pr-8", className)} {...rest}>
      {children}
    </select>
  );
}

export function Textarea({ className, ...rest }: ComponentProps<"textarea">) {
  return <textarea className={cx(controlClass, "py-2 leading-relaxed", className)} {...rest} />;
}

/**
 * A labelled control. Pass exactly one control as the child; it receives the
 * id, `aria-describedby` and `aria-invalid`.
 */
export function Field({
  id,
  label,
  hint,
  error,
  optional = false,
  children,
  className,
}: {
  id: string;
  label: ReactNode;
  hint?: ReactNode;
  error?: string | null;
  optional?: boolean;
  children: ReactElement;
  className?: string;
}) {
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  const control = Children.only(children);
  return (
    <div className={cx("min-w-0", className)}>
      <label htmlFor={id} className="flex items-baseline justify-between gap-2 text-[13px] font-medium text-text">
        <span>{label}</span>
        {optional ? <span className="text-[12px] font-normal text-text-3">Optional</span> : null}
      </label>
      <div className="mt-1.5">
        {isValidElement(control)
          ? cloneElement(control as ReactElement<Record<string, unknown>>, {
              id,
              "aria-describedby": describedBy,
              "aria-invalid": error ? true : undefined,
            })
          : control}
      </div>
      {hint ? (
        <p id={hintId} className="mt-1.5 text-[12px] leading-relaxed text-text-3">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className="mt-1.5 text-[12px] font-medium leading-relaxed text-bad">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** A checkbox or radio with its label and an optional description. */
export function Choice({
  type = "checkbox",
  label,
  description,
  className,
  ...rest
}: Omit<ComponentProps<"input">, "type"> & {
  type?: "checkbox" | "radio";
  label: ReactNode;
  description?: ReactNode;
}) {
  return (
    <label className={cx("flex cursor-pointer items-start gap-2.5", rest.disabled && "cursor-not-allowed opacity-60", className)}>
      <input type={type} className="mt-0.5 size-4 shrink-0" {...rest} />
      <span className="min-w-0">
        <span className="block text-[14px] text-text">{label}</span>
        {description ? <span className="mt-0.5 block text-[12px] leading-relaxed text-text-3">{description}</span> : null}
      </span>
    </label>
  );
}
