import Link from "next/link";
import { Suspense } from "react";

import { RunsTable } from "@/components/domain/runs-table";
import { OverviewSkeleton } from "@/components/ui/loading";
import { PageBody, PageHeader } from "@/components/shell/page-header";
import {
  EmptyState,
  ErrorState,
  Fact,
  LinkButton,
  Panel,
  PanelHeader,
  cx,
} from "@/components/ui/primitives";
import { Badge, HealthBadge } from "@/components/ui/status";
import { ApiError, api } from "@/lib/api/client";
import type {
  ApiHealth,
  BotAdapters,
  CallerProviders,
  Page as PageEnvelope,
  RunSummary,
  SpeechProviders,
  TranscriptionProviders,
} from "@/lib/api/types";

export const metadata = { title: "Overview" };

interface Loaded {
  health: ApiHealth | null;
  stt: TranscriptionProviders | null;
  tts: SpeechProviders | null;
  caller: CallerProviders | null;
  adapters: BotAdapters | null;
  runs: PageEnvelope<RunSummary> | null;
  /** The reason the API could not be reached at all, if that is what
   *  happened. One failure, reported once, rather than six empty panels. */
  outage: string | null;
}

async function load(): Promise<Loaded> {
  const settled = await Promise.allSettled([
    api.health({ cache: "no-store" }),
    api.transcriptionProviders({ cache: "no-store" }),
    api.speechProviders({ cache: "no-store" }),
    api.callerProviders({ cache: "no-store" }),
    api.botAdapters({ cache: "no-store" }),
    api.runs({ cache: "no-store", query: { limit: 8 } }),
  ]);

  const value = <T,>(index: number): T | null =>
    settled[index].status === "fulfilled"
      ? ((settled[index] as PromiseFulfilledResult<T>).value)
      : null;

  // If every call failed the same way, the backend is down — say that once
  // instead of repeating it in every panel.
  const reasons = settled
    .filter((entry): entry is PromiseRejectedResult => entry.status === "rejected")
    .map((entry) => entry.reason);
  const allDown =
    reasons.length === settled.length &&
    reasons.every((reason) => reason instanceof ApiError && reason.kind !== "http");

  return {
    health: value<ApiHealth>(0),
    stt: value<TranscriptionProviders>(1),
    tts: value<SpeechProviders>(2),
    caller: value<CallerProviders>(3),
    adapters: value<BotAdapters>(4),
    runs: value<PageEnvelope<RunSummary>>(5),
    outage: allDown ? (reasons[0] as ApiError).message : null,
  };
}

export default function OverviewPage() {
  return (
    <>
      <PageHeader
        title="Overview"
        description="What this server is configured to do, and what it has actually done. Nothing on this page is an estimate."
        actions={
          <LinkButton href="/app/new-test" tone="primary" size="sm">
            New test
          </LinkButton>
        }
      />

      <PageBody>
        <Suspense fallback={<OverviewSkeleton />}>
          <OverviewPanels />
        </Suspense>
      </PageBody>
    </>
  );
}

/**
 * Everything on this page that reads the server.
 *
 * Split out and suspended so the shell prerenders instantly and the live
 * state streams in behind a skeleton, rather than the whole route blocking
 * on six API calls.
 */
async function OverviewPanels() {
  const { health, stt, tts, caller, adapters, runs, outage } = await load();

  return (
    <>
        {outage ? (
          <Panel>
            <ErrorState
              title="The API is not reachable"
              detail={
                <>
                  {outage} Nothing on this page could be loaded. This is the
                  real state of the system, not a rendering problem — no
                  placeholder figures are shown in its place.
                </>
              }
            />
          </Panel>
        ) : null}

        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <div className="min-w-0 space-y-5">
            <SystemHealth health={health} />
            <RecentRuns runs={runs} />
          </div>

          <div className="min-w-0 space-y-5">
            <Configured
              stt={stt}
              tts={tts}
              caller={caller}
              adapters={adapters}
            />
            <NotImplemented caller={caller} adapters={adapters} />
          </div>
        </div>
    </>
  );
}

// ---------------------------------------------------------------------------

function SystemHealth({ health }: { health: ApiHealth | null }) {
  return (
    <Panel>
      <PanelHeader
        title="System health"
        description="Reported by the API itself, per subsystem."
        actions={health ? <HealthBadge status={health.status} /> : null}
      />
      {health === null ? (
        <ErrorState
          title="Health could not be read"
          detail="The health endpoint did not answer, so this server's state is unknown. An unknown state is not a healthy one."
        />
      ) : (
        <>
          <ul className="divide-y divide-line">
            {health.components.map((component) => (
              <li
                key={component.name}
                className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1 px-4 py-3"
              >
                <div className="min-w-0">
                  <p className="font-mono text-[13px] text-text">{component.name}</p>
                  <p className="mt-0.5 text-[12px] leading-relaxed text-text-dim">
                    {component.detail}
                  </p>
                </div>
                <HealthBadge status={component.status} />
              </li>
            ))}
          </ul>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 border-t border-line px-4 py-3 sm:grid-cols-4">
            <Fact label="Service">{health.service}</Fact>
            <Fact label="Version" mono>
              {health.version}
            </Fact>
            <Fact label="Environment" mono>
              {health.environment}
            </Fact>
            <Fact label="Uptime" mono>
              {formatUptime(health.uptime_seconds)}
            </Fact>
          </dl>
        </>
      )}
    </Panel>
  );
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
}

// ---------------------------------------------------------------------------

function RecentRuns({ runs }: { runs: PageEnvelope<RunSummary> | null }) {
  return (
    <Panel>
      <PanelHeader
        title="Recent runs"
        description={
          runs && runs.total > 0
            ? `${runs.total} run${runs.total === 1 ? "" : "s"} recorded.`
            : undefined
        }
        actions={
          runs && runs.total > 0 ? (
            <Link
              href="/app/runs"
              className="rounded-md px-2 py-1 text-[13px] text-accent hover:underline"
            >
              All runs
            </Link>
          ) : null
        }
      />
      {runs === null ? (
        <ErrorState
          title="Runs could not be loaded"
          detail="The run history endpoint did not answer."
        />
      ) : runs.items.length === 0 ? (
        <EmptyState
          title="No runs yet"
          action={
            <LinkButton href="/app/new-test" tone="primary" size="sm">
              Configure the first run
            </LinkButton>
          }
        >
          A run pairs a scenario with an execution mode and an acoustic
          profile, then drives the conversation turn by turn. Nothing is
          shown here until one exists — this space holds results, not
          examples.
        </EmptyState>
      ) : (
        <RunsTable runs={runs.items} compact />
      )}
    </Panel>
  );
}

// ---------------------------------------------------------------------------

function Configured({
  stt,
  tts,
  caller,
  adapters,
}: {
  stt: TranscriptionProviders | null;
  tts: SpeechProviders | null;
  caller: CallerProviders | null;
  adapters: BotAdapters | null;
}) {
  const rows = [
    { role: "Speech to text", selected: stt?.selected ?? null },
    { role: "Text to speech", selected: tts?.selected ?? null },
    { role: "Caller engine", selected: caller?.selected ?? null },
    { role: "Bot adapter", selected: adapters?.selected ?? null },
  ];

  const usingFake = rows.some((row) => row.selected === "fake");

  return (
    <Panel>
      <PanelHeader
        title="Configured for this server"
        description="What a run started right now would actually use."
        actions={
          <Link
            href="/app/providers"
            className="rounded-md px-2 py-1 text-[13px] text-accent hover:underline"
          >
            Details
          </Link>
        }
      />
      <ul className="divide-y divide-line">
        {rows.map((row) => (
          <li
            key={row.role}
            className="flex items-center justify-between gap-3 px-4 py-2.5"
          >
            <span className="text-[13px] text-text-dim">{row.role}</span>
            {row.selected === null ? (
              <span className="text-[13px] text-text-muted">unknown</span>
            ) : (
              <span className="flex items-center gap-2">
                <span className="font-mono text-[13px] text-text">{row.selected}</span>
                {row.selected === "fake" ? (
                  <Badge tone="warn" title="Scripted output, not recognised or synthesised speech.">
                    test double
                  </Badge>
                ) : null}
              </span>
            )}
          </li>
        ))}
      </ul>
      {usingFake ? (
        <p className="border-t border-line px-4 py-3 text-[12px] leading-relaxed text-warn">
          At least one provider is the offline test double. Runs executed in
          this configuration exercise the pipeline, and establish nothing
          about Prisma, Timbre or any bot.
        </p>
      ) : null}
    </Panel>
  );
}

// ---------------------------------------------------------------------------

/**
 * What this product does not do, stated on the first screen.
 *
 * Both strings come from the API verbatim rather than being written here:
 * the backend publishes `evon_status` and `telephony_status` precisely so a
 * client cannot soften them.
 */
function NotImplemented({
  caller,
  adapters,
}: {
  caller: CallerProviders | null;
  adapters: BotAdapters | null;
}) {
  const entries = [
    { name: "Gnani Evon", status: caller?.evon_status ?? null },
    { name: "Telephony", status: adapters?.telephony_status ?? null },
  ].filter((entry) => entry.status !== null);

  if (entries.length === 0) return null;

  return (
    <Panel>
      <PanelHeader
        title="Not implemented"
        description="Reported by the API, not written into this page."
      />
      <ul className="divide-y divide-line">
        {entries.map((entry) => (
          <li key={entry.name} className="px-4 py-3">
            <div className="flex items-center gap-2">
              <span className="text-[13px] font-medium text-text">{entry.name}</span>
              <Badge tone="bad">Not implemented</Badge>
            </div>
            <p className={cx("mt-1 text-[12px] leading-relaxed text-text-dim")}>
              {entry.status}
            </p>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
