import Link from "next/link";
import { ChevronRight } from "lucide-react";

import { ModeBadge, OutcomeBadge, RunStatusBadge } from "@/components/ui/status";
import { Table, TableScroll, Td, Th, cx } from "@/components/ui/primitives";
import { formatSeconds, formatTimestampShort, langAttr, shortId } from "@/lib/format";
import type { RunSummary } from "@/lib/api/types";

/**
 * Runs as a table on wide screens and a list on narrow ones. Each row says
 * whether an external system really answered - counted from the replies, not
 * the mode - because that is what decides whether the run describes a bot.
 */
export function RunsTable({
  runs,
  suiteNames,
  compact = false,
}: {
  runs: RunSummary[];
  /** suite id -> "Project / Suite", when the caller has it. */
  suiteNames?: Map<string, string>;
  compact?: boolean;
}) {
  return (
    <>
      <div className="hidden md:block">
        <TableScroll label="Test runs">
          <Table className="min-w-[56rem]">
            <thead>
              <tr>
                <Th>Scenario</Th>
                <Th>Status</Th>
                <Th>Outcome</Th>
                <Th>Mode</Th>
                {compact ? null : <Th>Language</Th>}
                {compact ? null : <Th className="text-right">Turns</Th>}
                {compact ? null : <Th className="text-right">Duration</Th>}
                <Th>Created</Th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.run_id} className="group transition-colors hover:bg-bg-soft">
                  <Td className="max-w-[22rem]">
                    <Link
                      href={`/app/runs/${run.run_id}`}
                      className="block truncate font-medium text-text hover:text-accent hover:underline underline-offset-4"
                    >
                      {run.scenario_name || "Unnamed scenario"}
                    </Link>
                    <span className="mt-0.5 block truncate font-mono text-[11px] text-text-3">
                      {shortId(run.run_id)}
                      {suiteNames?.get(run.suite_id) ? ` · ${suiteNames.get(run.suite_id)}` : ""}
                    </span>
                  </Td>
                  <Td>
                    <RunStatusBadge status={run.status} />
                  </Td>
                  <Td>
                    <OutcomeBadge outcome={run.outcome} />
                  </Td>
                  <Td>
                    <div className="flex flex-col items-start gap-1">
                      <ModeBadge mode={run.mode} />
                      <ExternalNote run={run} />
                    </div>
                  </Td>
                  {compact ? null : (
                    <Td className="font-mono text-[12px]">
                      <span lang={langAttr(run.language)}>{run.language}</span>
                    </Td>
                  )}
                  {compact ? null : (
                    <Td className="text-right font-mono text-[12px] tabular">
                      {run.caller_turns}/{run.bot_turns}
                    </Td>
                  )}
                  {compact ? null : (
                    <Td className="text-right font-mono text-[12px] tabular">{formatSeconds(run.duration_seconds) ?? "—"}</Td>
                  )}
                  <Td className="whitespace-nowrap font-mono text-[12px] text-text-3">{formatTimestampShort(run.created_at)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </TableScroll>
      </div>

      <ul className="divide-y divide-line md:hidden">
        {runs.map((run) => (
          <li key={run.run_id}>
            <Link href={`/app/runs/${run.run_id}`} className="flex items-start gap-3 px-4 py-3.5 active:bg-bg-soft">
              <div className="min-w-0 flex-1">
                <p className="truncate text-[14px] font-medium text-text">{run.scenario_name || "Unnamed scenario"}</p>
                <p className="mt-0.5 font-mono text-[11px] text-text-3">
                  {shortId(run.run_id)} · {run.language} · {formatTimestampShort(run.created_at)}
                </p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  <RunStatusBadge status={run.status} />
                  <OutcomeBadge outcome={run.outcome} />
                  <ModeBadge mode={run.mode} />
                </div>
              </div>
              <ChevronRight aria-hidden="true" className="mt-1 size-4 shrink-0 text-text-3" />
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}

function ExternalNote({ run }: { run: RunSummary }) {
  const claimsExternal = run.mode === "external_bot_test" || run.mode === "text_bot_test";
  if (!claimsExternal) return null;
  const received = run.mode === "external_bot_test" ? run.bot_audio_externally_received : run.bot_text_externally_received;
  return (
    <span className={cx("text-[11px]", received ? "text-text-3" : "font-medium text-warn")}>
      {received ? "bot answered" : "no reply from a bot"}
    </span>
  );
}
