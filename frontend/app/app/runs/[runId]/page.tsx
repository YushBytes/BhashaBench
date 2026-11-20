import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { AlertOctagon, PauseCircle } from "lucide-react";

import { AudioPlayer } from "@/components/runs/audio-player";
import { Conversation } from "@/components/runs/conversation";
import { EvaluationView } from "@/components/runs/evaluation-view";
import { MeasurementNote, RunCautions, RunEvidence } from "@/components/runs/evidence";
import { BotReply, EvaluateButton, RunActions, RunFollower, RunTabs } from "@/components/runs/run-controls";
import { StageTimeline } from "@/components/runs/stage-timeline";
import { PageBody, PageHeader } from "@/components/shell/page";
import {
  DetailSkeleton,
  ErrorState,
  Fact,
  NotReported,
  Panel,
  PanelBody,
  PanelHeader,
  Stat,
  Table,
  TableScroll,
  Td,
  Th,
} from "@/components/ui/primitives";
import { ModeBadge, OutcomeBadge, RunStatusBadge, VerdictBadge } from "@/components/ui/status";
import { ApiError, api, recordingAudioUrl } from "@/lib/api/client";
import { can, loadContext, projectOf } from "@/lib/api/context";
import { signInAgainIfExpired } from "@/lib/api/server";
import type { DegradationRequested, EvaluationList, MetricCatalogue, RecordingManifest, RunReport, RunTurns, SuiteRead } from "@/lib/api/types";
import { metricRows } from "@/lib/evaluation";
import { formatBytes, formatHz, formatSeconds, formatTimestamp, humanise, langAttr } from "@/lib/format";

export async function generateMetadata({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  return { title: `Run ${runId.slice(0, 8)}` };
}

export default function RunPage({ params }: { params: Promise<{ runId: string }> }) {
  return (
    <Suspense
      fallback={
        <>
          <PageHeader title="Run" crumbs={[{ href: "/app/runs", label: "Test runs" }]} />
          <PageBody>
            <DetailSkeleton />
          </PageBody>
        </>
      }
    >
      <RunDetail params={params} />
    </Suspense>
  );
}

/** Requested, not achieved: each degraded artefact records the measured values. */
function describeRequested(requested: DegradationRequested | null | undefined): string | null {
  if (!requested) return null;
  return [
    requested.snr_db === null ? "No added noise" : `${requested.snr_db} dB SNR`,
    requested.packet_loss_percent > 0 ? `${requested.packet_loss_percent}% packet loss` : "no packet loss",
  ].join(" · ");
}

async function RunDetail({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  let report: RunReport, turns: RunTurns, evaluations: EvaluationList | null, recording: RecordingManifest | null;
  let catalogue: MetricCatalogue | null, suite: SuiteRead | null;
  let context;
  try {
    context = await loadContext();
    const o = { cache: "no-store" as const, headers: context.auth };
    [report, turns, evaluations, recording, catalogue] = await Promise.all([
      api.runReport(runId, o),
      api.runTurns(runId, o),
      api.runEvaluations(runId, o).catch(() => null),
      // 404 until the run finishes: no recording yet is not an error.
      api.runRecording(runId, o).catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }),
      api.metricCatalogue({ revalidate: 3600 }).catch(() => null),
    ]);
    suite = await api.suite(report.run.suite_id, o).catch(() => null);
  } catch (error) {
    signInAgainIfExpired(error);
    if (error instanceof ApiError && error.status === 404) notFound();
    return (
      <>
        <PageHeader title="Run" crumbs={[{ href: "/app/runs", label: "Test runs" }]} />
        <PageBody>
          <Panel>
            <ErrorState title="This run could not be loaded" detail={error instanceof ApiError ? error.message : "The report endpoint did not answer."} />
          </Panel>
        </PageBody>
      </>
    );
  }

  const run = report.run;
  const project = suite ? projectOf(context, suite.project_id) : null;
  const role = project?.role ?? null;
  const finished = ["completed", "failed", "cancelled", "timed_out"].includes(run.status);
  const waiting = run.awaiting_bot_audio_for_turn !== null || typeof run.awaiting_bot_text_for_turn === "number";
  const inFlight = (run.status === "initializing" || run.status === "running") && !waiting;
  const references = !finished ? "hidden" : can(role, "edit") ? "edit" : "view";
  const list = evaluations?.evaluations ?? [];
  const latest = list[0] ?? null;
  const latencyRow = latest ? metricRows(latest.metrics).find((r) => r.key === "latency") : undefined;
  const werRow = latest ? metricRows(latest.metrics).find((r) => r.key === "wer") : undefined;

  return (
    <>
      <PageHeader
        crumbs={[
          { href: "/app/runs", label: "Test runs" },
          ...(suite ? [{ href: `/app/suites/${suite.id}`, label: suite.name }] : []),
          { label: run.run_id.slice(0, 8) },
        ]}
        title={run.scenario_name || "Unnamed scenario"}
        description={
          <span className="font-mono text-[12px]">
            {run.run_id} · started {formatTimestamp(run.started_at) ?? "not yet"}
            {run.finished_at ? ` · finished ${formatTimestamp(run.finished_at)}` : ""}
          </span>
        }
        meta={
          <>
            <ModeBadge mode={run.mode} />
            <RunStatusBadge status={run.status} />
            <OutcomeBadge outcome={run.outcome} />
            {finished ? <VerdictBadge verdict={latest?.verdict ?? null} /> : null}
          </>
        }
        actions={<RunActions runId={run.run_id} finished={finished} inFlight={inFlight} canEdit={can(role, "edit")} canDelete={can(role, "manage")} />}
      />
      <PageBody>
        <h1 className="print-only text-[20px] font-semibold">
          BhashaBench run report · {run.scenario_name} · {run.run_id}
        </h1>
        <RunFollower active={inFlight} />
        <RunCautions run={run} />

        {run.error ? (
          <Panel className="border-bad/30">
            <ErrorState title={run.outcome === "audio_validation_failed" ? "The audio could not be decoded" : "This run failed"} detail={run.error} />
          </Panel>
        ) : null}

        {waiting ? (
          <Panel className="border-busy/30">
            <PanelHeader
              icon={<PauseCircle aria-hidden="true" className="size-4 text-busy" />}
              title={`Waiting for the bot's reply to turn ${run.awaiting_bot_audio_for_turn ?? run.awaiting_bot_text_for_turn}`}
              description="The caller has spoken and the run is paused. It is healthy, not failed."
            />
            <PanelBody>
              {can(role, "edit") ? (
                <BotReply
                  runId={run.run_id}
                  turn={(run.awaiting_bot_audio_for_turn ?? run.awaiting_bot_text_for_turn) as number}
                  kind={run.awaiting_bot_audio_for_turn !== null ? "audio" : "text"}
                />
              ) : (
                <p className="text-[13px] text-text-3">A member of this workspace supplies the reply.</p>
              )}
            </PanelBody>
          </Panel>
        ) : null}

        <section aria-label="Run figures" className="grid grid-cols-2 gap-3 sm:grid-cols-[repeat(auto-fit,minmax(11rem,1fr))]">
          <Stat label="Turns" value={`${run.caller_turns + run.bot_turns}`} unit={`of ${run.turn_budget}`} detail={`${run.caller_turns} caller · ${run.bot_turns} bot`} />
          <Stat label="Bot replies transcribed" value={run.bot_exchange === "audio" ? `${run.bot_transcripts_succeeded}` : null} missing={run.bot_exchange === "audio" ? undefined : "No audio replies in this mode"} detail={run.bot_exchange === "audio" ? `${run.bot_transcripts_failed} not transcribed (our side)` : undefined} />
          <Stat label="Audio measured" value={run.total_audio_seconds > 0 ? formatSeconds(run.total_audio_seconds) : null} missing="No audio was stored" />
          <Stat label="Bot latency" value={latencyRow?.value ?? null} missing={latest ? (latencyRow?.detail ?? "Not measured") : "Evaluate the run to read it"} />
          <Stat label="Word error rate" value={werRow?.value ?? null} missing={latest ? "Needs a reference transcript" : "Evaluate the run to read it"} />
        </section>

        <RunTabs
          tabs={[
            {
              id: "conversation",
              label: "Conversation",
              badge: <span className="rounded-full bg-bg-sunk px-1.5 font-mono text-[11px] text-text-3">{turns.turns.length}</span>,
              panel: (
                <Panel>
                  <PanelHeader title="Conversation" description="Each turn with the audio that carried it. Play a turn to hear exactly what the other side received." />
                  <Conversation run={run} turns={turns.turns} artefacts={report.artefacts} events={report.events} references={references} />
                </Panel>
              ),
            },
            {
              id: "evaluation",
              label: "Evaluation",
              panel: (
                <div className="space-y-3">
                  {finished ? (
                    <div className="flex justify-end">
                      <EvaluateButton runId={run.run_id} again={latest !== null} />
                    </div>
                  ) : null}
                  <EvaluationView evaluations={list} catalogue={catalogue} finished={finished} />
                </div>
              ),
            },
            {
              id: "evidence",
              label: "Evidence and setup",
              panel: (
                <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
                  <div className="min-w-0 space-y-3">
                    <h3 className="text-[14px] font-semibold text-text">What this run establishes</h3>
                    <RunEvidence run={run} />
                  </div>
                  <div className="min-w-0 space-y-6">
                    <Panel>
                      <PanelHeader title="Configuration" description="The reproducibility record: a run nobody can reproduce is not evidence." />
                      <PanelBody>
                        <dl className="grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-3">
                          <Fact label="Project">{project?.name ?? "Not visible"}</Fact>
                          <Fact label="Suite">{suite ? <Link href={`/app/suites/${suite.id}`} className="text-accent hover:underline">{suite.name}</Link> : "Not visible"}</Fact>
                          <Fact label="Language" mono>
                            <span lang={langAttr(run.language)}>{run.language}</span>
                          </Fact>
                          <Fact label="Caller" mono hint={run.uses_language_model ? "Language model, per turn evidence." : "Rule engine."}>
                            {run.caller_provider}
                          </Fact>
                          <Fact label="Speech to text" mono>{run.stt_provider ?? "none (no audio)"}</Fact>
                          <Fact label="Text to speech" mono>{run.tts_provider ?? "none (no audio)"}</Fact>
                          <Fact label="Bot adapter" mono>{run.bot_adapter}</Fact>
                          {run.bot_integration ? (
                            <Fact label="Connected bot" hint={`Recorded when the run was created. ${run.bot_integration.protocol} at ${run.bot_integration.host}.`}>
                              <Link href={`/app/bots/${run.bot_integration.id}`} className="text-accent hover:underline">
                                {run.bot_integration.name}
                              </Link>
                            </Fact>
                          ) : null}
                          <Fact label="Seed" mono hint="Fixed so the degradation reproduces exactly.">{run.degradation_seed ?? "none"}</Fact>
                          <Fact label="Noise applied" hint={run.degradation_requested ? (run.degradation_requested.source === "scenario" ? "From the scenario's declared SNR and packet loss." : "A profile chosen for this run.") : undefined}>
                            {describeRequested(run.degradation_requested) ?? humanise(run.noise_profile)}
                          </Fact>
                          <Fact label="Scenario declared">{humanise(run.scenario_noise_profile) ?? "nothing"}</Fact>
                          <Fact label="Accent" hint={run.accent?.reason ?? (run.accent ? undefined : "The scenario names no accent.")}>
                            {run.accent ? (run.accent.applied ? `${run.accent.requested_name} · applied` : `${run.accent.requested_name} · requested, not applied`) : "none requested"}
                          </Fact>
                          <Fact label="Ended because">{humanise(run.termination_reason) ?? "not ended"}</Fact>
                        </dl>
                        <div className="mt-5 border-t border-line pt-4">
                          <p className="text-[12px] font-medium text-text-3">Line conditions, with who set each</p>
                          {run.degradation_requested?.conditions ? (
                            <ul className="mt-2 flex flex-wrap gap-1.5">
                              {Object.entries(run.degradation_requested.conditions).map(([key, value]) => (
                                <li key={key} className="rounded-md border border-line bg-bg-soft px-2 py-1 font-mono text-[12px] text-text-2">
                                  {key}={String(value)} <span className="text-text-3">· {run.degradation_requested?.condition_sources?.[key] ?? "?"}</span>
                                </li>
                              ))}
                            </ul>
                          ) : (
                            <p className="mt-1 text-[13px] text-text-2">None declared.</p>
                          )}
                        </div>
                      </PanelBody>
                    </Panel>
                    <Panel>
                      <PanelHeader title="What was counted" />
                      <PanelBody>
                        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3">
                          <Fact label="Caller turns" mono>{run.caller_turns}</Fact>
                          <Fact label="Bot turns" mono>{run.bot_turns}</Fact>
                          <Fact label="Turn budget" mono>{run.turn_budget}</Fact>
                          <Fact label="Caller state" mono>{run.caller_state}</Fact>
                          <Fact label="Text replies from the bot" mono>{run.bot_text_replies_received}</Fact>
                          <Fact label="Goal achieved">{run.goal_achieved ? "Yes" : "No"}</Fact>
                        </dl>
                        <div className="mt-4 border-t border-line pt-3">
                          <MeasurementNote note={report.measurement_note} />
                        </div>
                      </PanelBody>
                    </Panel>
                  </div>
                </div>
              ),
            },
            {
              id: "audio",
              label: "Recording and audio",
              badge: <span className="rounded-full bg-bg-sunk px-1.5 font-mono text-[11px] text-text-3">{report.artefacts.length}</span>,
              panel: (
                <div className="space-y-6">
                  <Panel>
                    <PanelHeader title="Full recording" description="Assembled from the turns after the run, in order. Gaps between turns are not reproduced, so it is not a timing measurement." />
                    <PanelBody>
                      {recording === null ? (
                        <p className="text-[13px] text-text-3">No recording until the run finishes.</p>
                      ) : recording.status === "stored" ? (
                        <div className="space-y-2">
                          <AudioPlayer
                            src={recordingAudioUrl(run.run_id)}
                            label="the full recording"
                            meta={[`${recording.duration_seconds?.toFixed(1) ?? "?"} s`, `${recording.segments?.length ?? 0} segments`, recording.assembly ?? ""].filter(Boolean)}
                          />
                          {recording.excluded?.map((e) => (
                            <p key={`${e.turn_index}-${e.speaker}`} className="text-[12px] text-warn">
                              Turn {e.turn_index} ({e.speaker}) not included: {e.reason}
                            </p>
                          ))}
                        </div>
                      ) : (
                        <p className="text-[13px] text-text-2">
                          {recording.status === "not_applicable" ? "No audio moved in this run" : "The recording could not be assembled"}
                          {recording.reason ? `: ${recording.reason}` : "."}
                        </p>
                      )}
                    </PanelBody>
                  </Panel>
                  <Panel>
                    <PanelHeader title="Stored audio" description="A degraded file names the original it came from, so the pair stays comparable." />
                    {report.artefacts.length === 0 ? (
                      <p className="px-4 py-6 text-[13px] text-text-3 sm:px-5">No audio was stored. This run moved no audio.</p>
                    ) : (
                      <TableScroll label="Stored audio">
                        <Table className="min-w-[44rem]">
                          <thead>
                            <tr>
                              <Th>Turn</Th>
                              <Th>Speaker</Th>
                              <Th>Variant</Th>
                              <Th>Transformations</Th>
                              <Th className="text-right">Duration</Th>
                              <Th className="text-right">Rate</Th>
                              <Th className="text-right">Size</Th>
                            </tr>
                          </thead>
                          <tbody>
                            {report.artefacts.map((a) => (
                              <tr key={`${a.turn_index}-${a.speaker}-${a.variant ?? "none"}`}>
                                <Td className="font-mono tabular">{a.turn_index}</Td>
                                <Td>{a.speaker}</Td>
                                <Td className="font-mono text-[12px]">{a.variant ?? "stored"}</Td>
                                <Td className="text-[12px]">{a.transformations.length > 0 ? a.transformations.join(", ") : "none"}</Td>
                                <Td className="text-right font-mono tabular">{formatSeconds(a.duration_seconds) ?? <NotReported what="needs a decoder" />}</Td>
                                <Td className="text-right font-mono tabular">{formatHz(a.sample_rate_hz) ?? "not read"}</Td>
                                <Td className="text-right font-mono tabular">{formatBytes(a.size_bytes)}</Td>
                              </tr>
                            ))}
                          </tbody>
                        </Table>
                      </TableScroll>
                    )}
                  </Panel>
                </div>
              ),
            },
            {
              id: "stages",
              label: "Pipeline stages",
              panel: (
                <Panel>
                  <PanelHeader title="Pipeline stages" description="Measured, not estimated." />
                  <StageTimeline events={report.events} />
                </Panel>
              ),
            },
          ]}
        />

        <div className="flex items-center gap-2 text-[12px] text-text-3">
          <AlertOctagon aria-hidden="true" className="size-3.5" />
          Every figure on this page is read from what the run stored. Missing values are shown as missing.
        </div>
      </PageBody>
    </>
  );
}
