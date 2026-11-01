import { StatusPill } from "@/components/status-pill";
import type { Capability } from "@/lib/content";

/**
 * Describes one planned test-suite capability. The status pill carries the
 * originating phase so the card cannot be mistaken for working functionality.
 */
export function CapabilityCard({ capability }: { readonly capability: Capability }) {
  const label =
    capability.status === "planned"
      ? `Planned · Phase ${capability.phase}`
      : undefined;

  return (
    <article className="flex h-full flex-col rounded-xl border border-border-subtle bg-surface-raised p-5 transition-colors hover:border-border-strong">
      <div className="mb-3 flex items-start justify-between gap-3">
        <h3 className="text-[15px] font-semibold text-text-primary">
          {capability.title}
        </h3>
        <StatusPill status={capability.status} label={label} />
      </div>
      <p className="text-sm leading-relaxed text-text-secondary">
        {capability.summary}
      </p>
    </article>
  );
}
