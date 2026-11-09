import { Panel, PanelHeader, Skeleton } from "./primitives";

/**
 * Loading placeholders shaped like the content they stand in for.
 *
 * Skeletons rather than a spinner, and skeletons that match the real
 * layout: the page must not reflow when the data lands, or every load looks
 * like a glitch. These are the `<Suspense>` fallbacks for the workspace,
 * which is what lets the shell prerender while live data streams in.
 */

export function PanelSkeleton({
  title,
  rows = 4,
}: {
  title: string;
  rows?: number;
}) {
  return (
    <Panel>
      <PanelHeader title={title} />
      <div className="space-y-2 p-4" role="status" aria-label={`Loading ${title}`}>
        {Array.from({ length: rows }).map((_, index) => (
          <Skeleton key={index} className="h-9 w-full" />
        ))}
      </div>
    </Panel>
  );
}

export function TableSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <Panel>
      <div className="space-y-2 p-4" role="status" aria-label="Loading runs">
        <Skeleton className="h-7 w-full" />
        {Array.from({ length: rows }).map((_, index) => (
          <Skeleton key={index} className="h-11 w-full" />
        ))}
      </div>
    </Panel>
  );
}

export function OverviewSkeleton() {
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
      <div className="space-y-5">
        <PanelSkeleton title="System health" rows={4} />
        <PanelSkeleton title="Recent runs" rows={4} />
      </div>
      <div className="space-y-5">
        <PanelSkeleton title="Configured for this server" rows={4} />
        <PanelSkeleton title="Not implemented" rows={2} />
      </div>
    </div>
  );
}

export function DetailSkeleton() {
  return (
    <div className="space-y-5">
      <PanelSkeleton title="Configuration" rows={3} />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <PanelSkeleton title="Conversation" rows={6} />
        <PanelSkeleton title="Pipeline stages" rows={5} />
      </div>
    </div>
  );
}
