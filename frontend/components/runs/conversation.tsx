/**
 * The conversation inspector: every turn with the audio that carried it, its
 * transcript, the caller's rule and state change, the script runs in it, and
 * the pipeline stages the backend recorded under the same turn index.
 *
 * Three outcomes the backend keeps apart, and this must never merge:
 *   - `text: ""` - the bot said nothing. A finding about the bot.
 *   - `text: null` + `transcription_error` - we could not transcribe it. Our
 *     failure; the conversation continued.
 *   - the run failing `audio_validation_failed` - neither; shown on the header.
 *
 * Stage events are shown exactly where the backend indexed them, as a strip
 * after the turn with that index, never re-attributed to a guessed turn.
 */

import { Bot, Mic } from "lucide-react";

import { ArtefactPlayer } from "./audio-player";
import { ReferenceEditor } from "./reference-editor";
import { cx } from "@/components/ui/primitives";
import { Badge } from "@/components/ui/status";
import type { Artefact, Run, RunTurn, StageEvent } from "@/lib/api/types";
import { formatMs, humanise, langAttr } from "@/lib/format";
import { describeBargeIn } from "@/lib/streaming";

function Transcript({ turn, language }: { turn: RunTurn; language: string }) {
  if (turn.text === null) {
    return (
      <div className="rounded-md border border-warn/30 bg-warn-soft px-3 py-2.5">
        <p className="text-[13px] font-medium text-warn">Not transcribed</p>
        <p className="mt-0.5 text-[12px] leading-relaxed text-text-2">
          Audio arrived but transcription failed, so what the bot said is unknown. This is our failure, not the bot&rsquo;s, and it is
          not the same as the bot saying nothing.
          {turn.transcription_error ? <span className="mt-1 block break-words font-mono text-[11px]">{turn.transcription_error}</span> : null}
        </p>
      </div>
    );
  }
  if (turn.text.trim() === "") {
    return (
      <div className="rounded-md border border-line-strong bg-bg-soft px-3 py-2.5">
        <p className="text-[13px] font-medium text-text">Silence</p>
        <p className="mt-0.5 text-[12px] leading-relaxed text-text-2">
          Transcription succeeded and recognised no speech. The bot said nothing: a finding about the bot.
        </p>
      </div>
    );
  }
  return (
    <p lang={langAttr(language)} className="whitespace-pre-wrap break-words text-[15px] leading-relaxed text-text">
      {turn.text}
    </p>
  );
}

function StageStrip({ events }: { events: StageEvent[] }) {
  if (events.length === 0) return null;
  return (
    <li aria-label="Pipeline stages for this turn" className="relative pl-12">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-l-2 border-dotted border-line-strong py-1 pl-3">
        {events.map((event, i) => {
          const latency = typeof event.evidence?.bot_latency_ms === "number" ? (event.evidence.bot_latency_ms as number) : null;
          const barge = describeBargeIn(event.evidence ?? null);
          return (
            <span key={`${event.stage}-${i}`} className="contents">
              <span
                className={cx(
                  "inline-flex items-center gap-1.5 font-mono text-[11px]",
                  event.status === "failed" ? "text-bad" : event.status === "skipped" ? "text-text-3" : "text-text-2",
                )}
                title={event.detail ?? undefined}
              >
                <span
                  aria-hidden="true"
                  className={cx(
                    "size-1.5 rounded-full",
                    event.status === "ok" ? "bg-ok" : event.status === "failed" ? "bg-bad" : event.status === "pending" ? "bg-busy" : "bg-idle",
                  )}
                />
                {event.stage}
                <span className="text-text-3">{formatMs(event.duration_ms) ?? event.status}</span>
                <span className="sr-only">{event.status}</span>
              </span>
              {latency !== null ? <span className="font-mono text-[11px] font-medium text-text">bot latency {formatMs(latency)}</span> : null}
              {barge ? <span className="basis-full text-[12px] text-text-2">{barge}</span> : null}
              {event.status === "failed" && event.detail ? <span className="basis-full break-words text-[12px] text-bad">{event.detail}</span> : null}
            </span>
          );
        })}
      </div>
    </li>
  );
}

function TurnRow({
  turn,
  run,
  artefacts,
  references,
}: {
  turn: RunTurn;
  run: Run;
  artefacts: Artefact[];
  references: "edit" | "view" | "hidden";
}) {
  const caller = turn.speaker === "caller";
  const mine = artefacts.filter((a) => a.turn_index === turn.index && a.speaker === turn.speaker);
  const segments = turn.script_segments ?? [];
  return (
    <li className="relative pl-12">
      <span
        aria-hidden="true"
        className={cx(
          "absolute left-0 top-0 flex size-9 items-center justify-center rounded-full",
          caller ? "bg-text text-bg" : "border border-line-strong bg-bg text-text",
        )}
      >
        {caller ? <Mic className="size-4" /> : <Bot className="size-4" />}
      </span>
      <div className={cx("rounded-lg border p-4", caller ? "border-line bg-bg-soft" : "border-line bg-bg shadow-1")}>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[14px] font-semibold text-text">{caller ? "Caller" : "Bot"}</span>
          <span className="font-mono text-[11px] text-text-3">turn {turn.index}</span>
          {turn.intent ? (
            <Badge tone="idle" title="The caller rule that chose this utterance.">
              {humanise(turn.intent)}
            </Badge>
          ) : null}
          {caller ? (
            <Badge tone="idle" title="Synthesised by the configured text-to-speech provider for this run.">
              {run.tts_provider ? `Synthesised · ${run.tts_provider}` : "Text only"}
            </Badge>
          ) : (
            <Badge
              tone={run.bot_audio_externally_received || run.bot_text_externally_received ? "ink" : "idle"}
              title={
                run.bot_audio_externally_received || run.bot_text_externally_received
                  ? "Supplied from outside this process."
                  : "Produced inside this process by the configured bot adapter. Not a real bot."
              }
            >
              {run.bot_audio_externally_received || run.bot_text_externally_received ? "From the external bot" : `Adapter · ${run.bot_adapter || "unknown"}`}
            </Badge>
          )}
        </div>
        {turn.state_before && turn.state_after ? (
          <p className="mt-1 font-mono text-[11px] text-text-3">
            {turn.state_before} → {turn.state_after}
            {turn.rule_ids.length > 0 ? ` · ${turn.rule_ids.join(", ")}` : ""}
          </p>
        ) : null}

        <div className="mt-3">
          <Transcript turn={turn} language={run.language} />
        </div>

        {segments.length > 1 ? (
          <div
            className="mt-2.5 flex flex-wrap items-center gap-1"
            title="Writing systems in this turn, in order. Script, not language: romanised Hindi is Latn; Hindi and Marathi share Deva."
          >
            {segments.map((s, i) => (
              <span key={i} className="rounded bg-bg-sunk px-1.5 py-0.5 font-mono text-[10.5px] text-text-2">
                {s.script} {s.words}
              </span>
            ))}
            <span className="ml-1 font-mono text-[10.5px] text-text-3">
              {segments.length - 1} script switch{segments.length === 2 ? "" : "es"}
            </span>
          </div>
        ) : null}

        {turn.synthesis_error ? (
          <p className="mt-3 break-words rounded-md border border-bad/25 bg-bad-soft px-3 py-2 text-[12px] text-bad">
            Synthesis failed: <span className="font-mono">{turn.synthesis_error}</span>
          </p>
        ) : null}

        {mine.length > 0 ? (
          <div className="mt-3 space-y-2">
            {mine.map((a) => (
              <ArtefactPlayer key={`${a.turn_index}-${a.variant ?? "none"}`} runId={run.run_id} artefact={a} />
            ))}
          </div>
        ) : null}

        {!caller && references !== "hidden" ? (
          <ReferenceEditor runId={run.run_id} turnIndex={turn.index} transcript={turn.text} canEdit={references === "edit"} />
        ) : null}
      </div>
    </li>
  );
}

export function Conversation({
  run,
  turns,
  artefacts,
  events,
  references = "hidden",
}: {
  run: Run;
  turns: RunTurn[];
  artefacts: Artefact[];
  events: StageEvent[];
  references?: "edit" | "view" | "hidden";
}) {
  if (turns.length === 0) {
    return <p className="px-4 py-8 text-center text-[13px] text-text-3 sm:px-5">No turns were recorded. The run was created but never started, or failed before the first turn.</p>;
  }
  const byIndex = new Map<number, StageEvent[]>();
  for (const e of events) if (e.turn_index !== null) byIndex.set(e.turn_index, [...(byIndex.get(e.turn_index) ?? []), e]);
  const lastOfIndex = new Map<number, number>();
  turns.forEach((t, i) => lastOfIndex.set(t.index, i));

  return (
    <ol className="space-y-4 px-4 py-5 sm:px-5">
      {turns.map((turn, i) => (
        <TurnRowWithStages key={`${turn.index}-${turn.speaker}`} showStages={lastOfIndex.get(turn.index) === i} events={byIndex.get(turn.index) ?? []}>
          <TurnRow turn={turn} run={run} artefacts={artefacts} references={references} />
        </TurnRowWithStages>
      ))}
    </ol>
  );
}

function TurnRowWithStages({ children, showStages, events }: { children: React.ReactNode; showStages: boolean; events: StageEvent[] }) {
  return (
    <>
      {children}
      {showStages ? <StageStrip events={events} /> : null}
    </>
  );
}
