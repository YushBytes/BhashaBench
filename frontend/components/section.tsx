import type { ReactNode } from "react";

interface SectionProps {
  readonly id: string;
  readonly eyebrow: string;
  readonly title: string;
  readonly intro?: string;
  readonly children: ReactNode;
}

/** A titled page section, so spacing and heading hierarchy stay consistent. */
export function Section({ id, eyebrow, title, intro, children }: SectionProps) {
  return (
    <section
      id={id}
      aria-labelledby={`${id}-heading`}
      className="scroll-mt-20 border-t border-border-subtle py-14 sm:py-20"
    >
      <p className="mb-3 font-mono text-xs uppercase tracking-[0.18em] text-accent">
        {eyebrow}
      </p>
      <h2
        id={`${id}-heading`}
        className="text-2xl font-semibold tracking-tight text-text-primary sm:text-3xl"
      >
        {title}
      </h2>
      {intro ? (
        <p className="mt-3 max-w-2xl text-[15px] leading-relaxed text-text-secondary">
          {intro}
        </p>
      ) : null}
      <div className="mt-8">{children}</div>
    </section>
  );
}
