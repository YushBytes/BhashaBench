import { currentPhase, navigation, site, totalPhases } from "@/lib/content";

/** Fixed top navigation. Links are in-page anchors; there is only one route. */
export function SiteHeader() {
  return (
    <header className="sticky top-0 z-20 border-b border-border-subtle bg-surface-base/85 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-6 px-6">
        <a
          href="#overview"
          className="flex items-center gap-2.5 text-text-primary"
        >
          <WordmarkGlyph />
          <span className="text-[15px] font-semibold tracking-tight">
            {site.name}
          </span>
        </a>

        <nav aria-label="Sections" className="hidden items-center gap-1 md:flex">
          {navigation.map((item) => (
            <a
              key={item.href}
              href={item.href}
              className="rounded-md px-3 py-1.5 text-sm text-text-secondary transition-colors hover:bg-surface-raised hover:text-text-primary"
            >
              {item.label}
            </a>
          ))}
        </nav>

        <div className="flex items-center gap-3">
          <span className="hidden font-mono text-xs text-text-tertiary sm:inline">
            Phase {currentPhase}/{totalPhases}
          </span>
          <a
            href={site.repository}
            target="_blank"
            rel="noreferrer"
            className="rounded-md border border-border-strong px-3 py-1.5 text-sm font-medium text-text-secondary transition-colors hover:border-accent/50 hover:text-text-primary"
          >
            GitHub
          </a>
        </div>
      </div>
    </header>
  );
}

/** Three bars suggesting a waveform; decorative only. */
function WordmarkGlyph() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 20 20"
      fill="none"
      aria-hidden="true"
      className="text-accent"
    >
      <rect x="2" y="7" width="2.5" height="6" rx="1.25" fill="currentColor" opacity="0.55" />
      <rect x="7" y="3" width="2.5" height="14" rx="1.25" fill="currentColor" />
      <rect x="12" y="5.5" width="2.5" height="9" rx="1.25" fill="currentColor" opacity="0.75" />
      <rect x="17" y="8.5" width="2.5" height="3" rx="1.25" fill="currentColor" opacity="0.4" />
    </svg>
  );
}
