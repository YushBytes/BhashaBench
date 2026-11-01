import { currentPhase, site, totalPhases } from "@/lib/content";

export function SiteFooter() {
  return (
    <footer className="mt-auto border-t border-border-subtle">
      <div className="mx-auto flex max-w-6xl flex-col gap-3 px-6 py-8 text-sm text-text-tertiary sm:flex-row sm:items-center sm:justify-between">
        <p>
          {site.name} — {site.tagline}
        </p>
        <p className="font-mono text-xs">
          Phase {currentPhase} of {totalPhases} · v0.1.0
        </p>
      </div>
    </footer>
  );
}
