import Link from "next/link";

import { TableScroll, Td, Th, cx } from "@/components/ui/primitives";
import { ModeBadge, OutcomeBadge, RunStatusBadge } from "@/components/ui/status";
import { formatSeconds, formatTimestampShort, langAttr } from "@/lib/format";
import type { RunSummary } from "@/lib/api/types";

/**
 * The run history table.
 *
 * Shared by the overview and the runs page so a run reads the same in both.
 * `compact` drops the columns that only matter when filtering.
 *
 * Two honesty details carried by the row itself:
 *
 * - An absent duration renders as "—" with a title explaining it, never as
 *   0s. The backend returns null until a run has both a start and a finish.
 * - A run labelled `external_bot_test` whose `bot_audio_externally_received`
 *   is false gets a marker here, in the list, rather than only on the detail
 *   page. The mislabelling is the kind of thing a reader should catch while
 *   scanning.
 */
export function RunsTable({
  runs,
  compact = false,
}: {
  runs: RunSummary[];
  compact?: boolean;
}) {
  return (
    <TableScroll>
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="border-b border-line bg-surface-inset">
            <Th>Scenario</Th>
            <Th>Language</Th>
            <Th>Mode</Th>
            <Th>Status</Th>
            <Th>Outcome</Th>
            {!compact ? <Th className="text-right">Turns</Th> : null}
            {!compact ? <Th className="text-right">Duration</Th> : null}
            <Th>Started</Th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => {
            const mislabelled =
              run.mode === "external_bot_test" && !run.bot_audio_externally_received;
            const duration = formatSeconds(run.duration_seconds);
            const created = formatTimestampShort(run.created_at);

            return (
              <tr
                key={run.run_id}
                className="border-b border-line transition-colors last:border-0 hover:bg-surface-raised"
              >
                <Td className="max-w-[22rem]">
                  <Link
                    href={`/app/runs/${run.run_id}`}
                    className="group flex flex-col gap-0.5"
                  >
                    <span className="truncate font-medium text-text group-hover:text-accent">
                      {run.scenario_name || "Unnamed scenario"}
                    </span>
                    <span className="font-mono text-[11px] text-text-muted">
                      {run.run_id.slice(0, 8)}
                    </span>
                  </Link>
                </Td>

                <Td>
                  <span className="font-mono text-[12px]" lang={langAttr(run.language)}>
                    {run.language || "—"}
                  </span>
                </Td>

                <Td>
                  <span className="flex items-center gap-1.5">
                    <ModeBadge mode={run.mode} />
                    {mislabelled ? (
                      <span
                        className="text-[11px] font-medium text-warn"
                        title="Labelled an external bot test, but every reply came from inside this process."
                      >
                        unverified
                      </span>
                    ) : null}
                  </span>
                </Td>

                <Td>
                  <RunStatusBadge status={run.status} />
                </Td>

                <Td>
                  <OutcomeBadge outcome={run.outcome} />
                </Td>

                {!compact ? (
                  <Td className="text-right font-mono text-[12px] tabular">
                    <span title="Caller turns / bot turns">
                      {run.caller_turns}
                      <span className="text-text-muted"> / </span>
                      {run.bot_turns}
                    </span>
                  </Td>
                ) : null}

                {!compact ? (
                  <Td className={cx("text-right font-mono text-[12px] tabular")}>
                    {duration ?? (
                      <span
                        className="text-text-muted"
                        title="A duration needs both a start and a finish. This run has not finished."
                      >
                        —
                      </span>
                    )}
                  </Td>
                ) : null}

                <Td className="whitespace-nowrap font-mono text-[12px] text-text-muted">
                  {created ?? "—"}
                </Td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </TableScroll>
  );
}
