import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { Conversation } from "@/components/domain/conversation";
import { RunEvidence, MeasurementNote } from "@/components/domain/evidence";
import { StageTimeline } from "@/components/domain/stage-timeline";
import { PageBody, PageHeader } from "@/components/shell/page-header";
import { DetailSkeleton } from "@/components/ui/loading";
import {
  ErrorState,
  Fact,
  Panel,
  PanelHeader,
  TableScroll,
  Td,
  Th,
} from "@/components/ui/primitives";
import { RunActions } from "@/components/domain/run-actions";
import { ModeBadge, OutcomeBadge, RunStatusBadge } from "@/components/ui/status";
import { ApiError, api, recordingAudioUrl } from "@/lib/api/client";
import { EvaluateButton, RunAutoRefresh } from "@/components/domain/run-live";
import { sessionHeaders, signInAgainIfExpired } from "@/lib/api/server";
import {
  formatBytes,
  formatHz,
  formatSeconds,
  formatTimestamp,
  humanise,
  langAttr,
} from "@/lib/format";
import type {
  DegradationRequested,
  EvaluationList,
  RecordingManifest,
  RunReport,
  RunTurns,
} from "@/lib/api/types";


export async function generateMetadata({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const { runId } = await params;
  return { title: `Run ${runId.slice(0, 8)}` };
}

/**
 * The requested channel conditions in words, or null when not recorded (a run
 * that moves no audio, or one created before requests were recorded).
 * Requested, not achieved: the artefacts carry the measured values.
 */
function describeRequested(requested: DegradationRequested | null | undefined): string | null {
  if (!requested) return null;
  const parts: string[] = [];
  parts.push(requested.snr_db === null ? "No added noise" : `${requested.snr_db} dB SNR`);
  parts.push(
    requested.packet_loss_percent > 0
      ? `${requested.packet_loss_percent}% packet loss`
      : "no packet loss",
  );
  return parts.join(" · ");
}

export default function RunDetailPage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  return (
    <Suspense fallback={<DetailLoading />}>
      <RunDetail params={params} />
    </Suspense>
  );
}

function DetailLoading() {
  return (
    <>
      <PageHeader title="Run" />
      <PageBody>
        <DetailSkeleton />
      </PageBody>
    </>
  );
}

async function RunDetail({ params }: { params: Promise<{ runId: string }> }) {
  const auth = await sessionHeaders();
  const { runId } = await params;

  let report: RunReport;
  let turns: RunTurns;
  let evaluations: EvaluationList | null;
  let recording: RecordingManifest | null;
  try {
    [report, turns, evaluations, recording] = await Promise.all([
      api.runReport(runId, { cache: "no-store", headers: auth }),
      api.runTurns(runId, { cache: "no-store", headers: auth }),
      api.runEvaluations(runId, { cache: "no-store", headers: auth }).catch(() => null),
      // 404 until the run finishes: no recording yet is not an error.
      api.runRecording(runId, { cache: "no-store", headers: auth }).catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }),
    ]);
  } catch (error) {
    signInAgainIfExpired(error);
    if (error instanceof ApiError && error.status === 404) notFound();
    return (
      <>
        <PageHeader title="Run" />
        <PageBody>
          <Panel>
            <ErrorState
              title="This run could not be loaded"
              detail={
                error instanceof ApiError
                  ? error.message
                  : "The report endpoint did not answer."
              }
            />
          </Panel>
        </PageBody>
      </>
    );
  }

  const run = report.run;
  const degraded = report.artefacts.filter((a) => a.variant === "degraded");
  const inFlight =
    (run.status === "initializing" || run.status === "running") &&
    run.awaiting_bot_audio_for_turn === null &&
    typeof run.awaiting_bot_text_for_turn !== "number";
  const finished = ["completed", "failed", "cancelled", "timed_out"].includes(run.status);
  const latest = evaluations?.evaluations[0] ?? null;
  const canDelete = finished ? await mayDelete(run.suite_id, auth) : false;

  return (
    <>
      <PageHeader
        breadcrumb={
          <Link
            href="/app/runs"
            className="font-mono text-[12px] text-text-muted hover:text-accent"
          >
            ← Test runs
          </Link>
        }
        title={run.scenario_name || "Unnamed scenario"}
        description={
          <span className="font-mono text-[12px] text-text-muted">{run.run_id}</span>
        }
        actions={
          <div className="flex flex-col items-start gap-2 sm:items-end">
            <div className="flex flex-wrap items-center gap-2">
              <ModeBadge mode={run.mode} />
              <RunStatusBadge status={run.status} />
              <OutcomeBadge outcome={run.outcome} />
            </div>
            <RunActions runId={run.run_id} finished={finished} canDelete={canDelete} />
          </div>
        }
      />

      <PageBody>
        <RunAutoRefresh active={inFlight} />

        <div className="grid min-w-0 gap-5 lg:grid-cols-2">
          <Panel>
            <PanelHeader
              title="Evaluation"
              description="Read from what this run stored, under the current evaluator. Re-evaluating appends; history is kept."
              actions={finished ? <EvaluateButton runId={run.run_id} again={latest !== null} /> : null}
            />
            {latest === null ? (
              <p className="p-4 text-[13px] text-text-muted sm:p-5">
                {finished ? "Not evaluated yet." : "The run has not finished, so there is nothing to evaluate."}
              </p>
            ) : (
              <div className="p-4 sm:p-5">
                <p className="text-[15px] font-semibold text-text">
                  Verdict: {latest.verdict}{" "}
                  <span className="font-mono text-[12px] font-normal text-text-dim">{latest.evaluator_version}</span>
                </p>
                <ul className="mt-3 space-y-1.5">
                  {latest.criteria.map((criterion) => (
                    <li key={criterion.name} className="text-[13px]">
                      <span className="font-mono text-text">{criterion.name}</span>{" "}
                      <span className="text-text-muted">{criterion.status} - {criterion.reason}</span>
                    </li>
                  ))}
                </ul>
                {!latest.measures_audio ? (
                  <p className="mt-3 text-[12px] text-text-dim">This mode moved no audio; nothing here describes audio.</p>
                ) : null}
              </div>
            )}
          </Panel>

          <Panel>
            <PanelHeader
              title="Full recording"
              description="Assembled from the turns after the run, in order. Gaps between turns are not reproduced, so it is not a timing measurement."
            />
            <div className="p-4 sm:p-5">
              {recording === null ? (
                <p className="text-[13px] text-text-muted">No recording until the run finishes.</p>
              ) : recording.status === "stored" ? (
                <>
                  <audio controls preload="none" src={recordingAudioUrl(run.run_id)} className="w-full">
                    Your browser cannot play this recording.
                  </audio>
                  <p className="mt-2 font-mono text-[12px] text-text-dim">
                    {recording.duration_seconds?.toFixed(1)} s · {recording.segments?.length ?? 0} segments
                    {recording.excluded && recording.excluded.length > 0
                      ? ` · ${recording.excluded.length} turn(s) excluded`
                      : ""}
                  </p>
                  {recording.excluded?.map((e) => (
                    <p key={`${e.turn_index}-${e.speaker}`} className="mt-1 text-[12px] text-warn">
                      Turn {e.turn_index} ({e.speaker}) not included: {e.reason}
                    </p>
                  ))}
                </>
              ) : (
                <p className="text-[13px] text-text-muted">
                  {recording.status === "not_applicable" ? "No audio moved in this run." : "The recording could not be assembled"}
                  {recording.reason ? `: ${recording.reason}` : "."}
                </p>
              )}
            </div>
          </Panel>
        </div>

        {run.error ? (
          <Panel className="border-bad/40">
            <ErrorState title="This run failed" detail={run.error} />
          </Panel>
        ) : null}

        {run.awaiting_bot_audio_for_turn !== null ? (
          <Panel className="border-busy/40">
            <div className="px-4 py-3">
              <p className="text-[13px] font-medium text-busy">
                Waiting for bot audio for turn {run.awaiting_bot_audio_for_turn}
              </p>
              <p className="mt-1 text-[12px] leading-relaxed text-text-dim">
                The caller&rsquo;s audio for this turn is stored and the run is
                paused. It is healthy, not failed. Post the bot&rsquo;s reply to{" "}
                <code className="font-mono text-[11px] text-text-dim">
                  POST /api/v1/test-runs/{run.run_id}/bot-audio
                </code>{" "}
                to continue.
              </p>
            </div>
          </Panel>
        ) : null}

        {typeof run.awaiting_bot_text_for_turn === "number" ? (
          <Panel className="border-busy/40">
            <div className="px-4 py-3">
              <p className="text-[13px] font-medium text-busy">
                Waiting for the bot&rsquo;s text reply for turn{" "}
                {run.awaiting_bot_text_for_turn}
              </p>
              <p className="mt-1 text-[12px] leading-relaxed text-text-dim">
                An offline simulation moves no audio. The caller has spoken and
                the run is paused &mdash; healthy, not failed. Post what the bot
                said to{" "}
                <code className="font-mono text-[11px] text-text-dim">
                  POST /api/v1/test-runs/{run.run_id}/bot-text
                </code>{" "}
                to continue.
              </p>
            </div>
          </Panel>
        ) : null}

        <RunEvidence run={run} />

        {/* Configuration. The reproducibility record: a run nobody can
            reproduce is not evidence, so the seed and profile sit beside the
            result rather than behind a tab. */}
        <Panel>
          <PanelHeader title="Configuration" />
          <dl className="grid grid-cols-2 gap-x-4 gap-y-4 px-4 py-4 sm:grid-cols-3 lg:grid-cols-6">
            <Fact label="Language" mono>
              <span lang={langAttr(run.language)}>{run.language || "—"}</span>
            </Fact>
            <Fact label="Caller" mono>
              {run.caller_provider || "—"}
            </Fact>
            <Fact label="Speech to text" mono>
              {run.stt_provider ?? "—"}
            </Fact>
            <Fact label="Text to speech" mono>
              {run.tts_provider ?? "—"}
            </Fact>
            <Fact label="Bot adapter" mono>
              {run.bot_adapter || "—"}
            </Fact>
            <Fact label="Seed" mono hint="Fixed so the degradation reproduces exactly.">
              {run.degradation_seed ?? "—"}
            </Fact>
            <Fact
              label="Noise applied"
              hint={
                run.degradation_requested
                  ? run.degradation_requested.source === "scenario"
                    ? "Requested from the scenario's declared SNR and packet loss. Each degraded artefact records the measured values."
                    : "An explicit profile chosen for this run, applied as its reviewed preset."
                  : undefined
              }
            >
              {describeRequested(run.degradation_requested) ?? humanise(run.noise_profile)}
            </Fact>
            <Fact
              label="Scenario declared"
              hint="The acoustic environment the scenario asked for, kept beside what was applied."
            >
              {humanise(run.scenario_noise_profile) ?? "—"}
            </Fact>
            <Fact label="Caller state" mono>
              {run.caller_state}
            </Fact>
            <Fact label="Ended because">
              {humanise(run.termination_reason) ?? "—"}
            </Fact>
            <Fact label="Started">{formatTimestamp(run.started_at) ?? "—"}</Fact>
            <Fact label="Finished">{formatTimestamp(run.finished_at) ?? "—"}</Fact>
          </dl>
        </Panel>

        {/* Counts. Captioned with the API's own note so they are not read as
            a score. */}
        <Panel>
          <PanelHeader title="What was counted" />
          <dl className="grid grid-cols-2 gap-x-4 gap-y-4 px-4 py-4 sm:grid-cols-3 lg:grid-cols-6">
            <Fact label="Caller turns" mono>
              {run.caller_turns}
            </Fact>
            <Fact label="Bot turns" mono>
              {run.bot_turns}
            </Fact>
            <Fact label="Turn budget" mono>
              {run.turn_budget}
            </Fact>
            <Fact label="Transcribed" mono>
              {run.bot_transcripts_succeeded}
            </Fact>
            <Fact
              label="Not transcribed"
              mono
              hint="Bot replies whose audio arrived but could not be transcribed."
            >
              {run.bot_transcripts_failed}
            </Fact>
            <Fact
              label="Audio measured"
              mono
              hint="Summed from artefacts whose length could be read from the bytes."
            >
              {formatSeconds(run.total_audio_seconds) ?? "—"}
            </Fact>
          </dl>
          <div className="border-t border-line px-4 py-3">
            <MeasurementNote note={report.measurement_note} />
          </div>
        </Panel>

        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-5 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <Panel>
            <PanelHeader
              title="Conversation"
              description="Each turn with the audio that carried it. Play a turn to hear exactly what the other side received."
            />
            <Conversation run={run} turns={turns.turns} artefacts={report.artefacts} />
          </Panel>

          <div className="min-w-0 space-y-5">
            <Panel>
              <PanelHeader
                title="Pipeline stages"
                description="Measured, not estimated. Bars are relative to the slowest stage in this run."
              />
              <StageTimeline events={report.events} />
            </Panel>

            <Panel>
              <PanelHeader
                title="Audio artefacts"
                description={
                  degraded.length > 0
                    ? "A degraded file names the original it came from, so the pair stays comparable."
                    : undefined
                }
              />
              {report.artefacts.length === 0 ? (
                <p className="px-4 py-6 text-[13px] text-text-dim">
                  No audio was stored. This run moved no audio.
                </p>
              ) : (
                <TableScroll>
                  <table className="w-full border-collapse text-left">
                    <thead>
                      <tr className="border-b border-line bg-surface-inset">
                        <Th>Turn</Th>
                        <Th>Speaker</Th>
                        <Th>Variant</Th>
                        <Th className="text-right">Duration</Th>
                        <Th className="text-right">Rate</Th>
                        <Th className="text-right">Size</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.artefacts.map((artefact) => (
                        <tr
                          key={`${artefact.turn_index}-${artefact.variant ?? "none"}`}
                          className="border-b border-line last:border-0"
                        >
                          <Td className="font-mono tabular">{artefact.turn_index}</Td>
                          <Td>{artefact.speaker}</Td>
                          <Td>
                            <span className="font-mono text-[12px]">
                              {artefact.variant ?? "—"}
                            </span>
                            {artefact.transformations.length > 0 ? (
                              <span
                                className="ml-1.5 text-[11px] text-text-muted"
                                title={artefact.transformations.join(", ")}
                              >
                                {artefact.transformations.length} transform
                                {artefact.transformations.length === 1 ? "" : "s"}
                              </span>
                            ) : null}
                          </Td>
                          <Td className="text-right font-mono tabular">
                            {formatSeconds(artefact.duration_seconds) ?? (
                              <span
                                className="text-text-muted"
                                title="This container cannot be measured without a decoder."
                              >
                                —
                              </span>
                            )}
                          </Td>
                          <Td className="text-right font-mono tabular">
                            {formatHz(artefact.sample_rate_hz) ?? "—"}
                          </Td>
                          <Td className="text-right font-mono tabular">
                            {formatBytes(artefact.size_bytes) ?? "—"}
                          </Td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableScroll>
              )}
            </Panel>
          </div>
        </div>
      </PageBody>
    </>
  );
}

/**
 * Whether the caller is admin or owner of the workspace holding this run's
 * suite - the role DELETE /test-runs/{id} requires. Only decides whether
 * the control is shown; the server checks again. Any failure hides it.
 */
async function mayDelete(suiteId: string, headers: Record<string, string>): Promise<boolean> {
  try {
    const [suites, workspaces] = await Promise.all([
      api.suites({ cache: "no-store", headers }),
      api.workspaces({ cache: "no-store", headers }),
    ]);
    const suite = suites.items.find((item) => item.id === suiteId);
    if (!suite) return false;
    for (const workspace of workspaces.filter((w) => w.role === "owner" || w.role === "admin")) {
      const projects = await api.projects(workspace.id, { cache: "no-store", headers });
      if (projects.some((project) => project.id === suite.project_id)) return true;
    }
  } catch {
    return false;
  }
  return false;
}
