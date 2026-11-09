import { AudioArtefactPlayer } from "./audio-player";
import { Badge } from "@/components/ui/status";
import { cx } from "@/components/ui/primitives";
import { humanise, langAttr } from "@/lib/format";
import type { Artefact, Run, RunTurn } from "@/lib/api/types";

/**
 * The conversation, turn by turn, with the audio that carried it.
 *
 * Three outcomes the backend deliberately keeps apart, and which this
 * component must never merge:
 *
 * - `text: ""` — the bot said nothing. A finding about the bot.
 * - `text: null` + `transcription_error` — we could not transcribe it. Our
 *   problem, not the bot's, and the conversation continued.
 * - the run failing `audio_validation_failed` — the audio was not decodable,
 *   which is neither of the above and is shown on the run header.
 *
 * Rendering the first two the same way would attribute our failure to the
 * system under test, which is the most consequential lie this page could
 * tell.
 */

function speakerOf(turn: RunTurn): "caller" | "bot" {
  return turn.speaker === "caller" ? "caller" : "bot";
}

function Transcript({ turn, language }: { turn: RunTurn; language: string }) {
  if (turn.text === null) {
    return (
      <div className="rounded-md border border-warn/30 bg-warn-dim px-3 py-2">
        <p className="text-[13px] font-medium text-warn">Not transcribed</p>
        <p className="mt-0.5 text-[12px] leading-relaxed text-text-dim">
          Audio arrived but transcription failed, so what the bot said is
          unknown. This is our failure, not the bot&rsquo;s — and it is not
          the same as the bot saying nothing.
          {turn.transcription_error ? (
            <>
              {" "}
              <span className="font-mono text-[11px]">{turn.transcription_error}</span>
            </>
          ) : null}
        </p>
      </div>
    );
  }

  if (turn.text.trim() === "") {
    return (
      <div className="rounded-md border border-line bg-surface-inset px-3 py-2">
        <p className="text-[13px] font-medium text-text">Silence</p>
        <p className="mt-0.5 text-[12px] leading-relaxed text-text-dim">
          Transcription succeeded and recognised no speech. The bot said
          nothing — a finding about the bot.
        </p>
      </div>
    );
  }

  return (
    <p
      lang={langAttr(language)}
      className="text-[14px] leading-relaxed text-text"
    >
      {turn.text}
    </p>
  );
}

function TurnCard({
  turn,
  run,
  artefacts,
}: {
  turn: RunTurn;
  run: Run;
  artefacts: Artefact[];
}) {
  const side = speakerOf(turn);
  const isCaller = side === "caller";
  const mine = artefacts.filter((a) => a.turn_index === turn.index && a.speaker === turn.speaker);

  return (
    <li className="relative pl-7">
      {/* The rail dot. The line itself is drawn by the list. */}
      <span
        aria-hidden="true"
        className={cx(
          "absolute left-[7px] top-2 size-[9px] rounded-full border-2 border-bg",
          isCaller ? "bg-accent" : "bg-accent-alt",
        )}
      />

      <div className="flex flex-wrap items-center gap-2">
        <span
          className={cx(
            "text-[13px] font-semibold",
            isCaller ? "text-accent" : "text-accent-alt",
          )}
        >
          {isCaller ? "Caller" : "Bot"}
        </span>
        <span className="font-mono text-[11px] text-text-muted">
          turn {turn.index}
        </span>
        {turn.intent ? (
          <Badge tone="idle" title="The caller rule that chose this utterance.">
            {humanise(turn.intent)}
          </Badge>
        ) : null}
        {isCaller ? (
          <Badge
            tone="idle"
            title="Synthesised by the configured text-to-speech provider for this run."
          >
            {run.tts_provider ? `Synthesised · ${run.tts_provider}` : "Synthesised"}
          </Badge>
        ) : (
          <Badge
            tone={run.bot_audio_externally_received ? "accent" : "idle"}
            title={
              run.bot_audio_externally_received
                ? "Supplied from outside this process."
                : "Produced inside this process by the configured bot adapter. Not a real bot."
            }
          >
            {run.bot_audio_externally_received
              ? "External audio"
              : `Adapter · ${run.bot_adapter || "unknown"}`}
          </Badge>
        )}
      </div>

      {turn.state_before && turn.state_after ? (
        <p className="mt-1 font-mono text-[11px] text-text-muted">
          {turn.state_before} → {turn.state_after}
          {turn.rule_ids.length > 0 ? (
            <span className="text-text-muted"> · {turn.rule_ids.join(", ")}</span>
          ) : null}
        </p>
      ) : null}

      <div className="mt-2">
        <Transcript turn={turn} language={run.language} />
      </div>

      {turn.synthesis_error ? (
        <p className="mt-2 rounded-md border border-bad/30 bg-bad-dim px-3 py-2 text-[12px] text-bad">
          Synthesis failed: <span className="font-mono">{turn.synthesis_error}</span>
        </p>
      ) : null}

      {mine.length > 0 ? (
        <div className="mt-2 space-y-2">
          {mine.map((artefact) => (
            <AudioArtefactPlayer
              key={`${artefact.turn_index}-${artefact.variant ?? "none"}`}
              runId={run.run_id}
              artefact={artefact}
              tone={side}
            />
          ))}
        </div>
      ) : null}
    </li>
  );
}

export function Conversation({
  run,
  turns,
  artefacts,
}: {
  run: Run;
  turns: RunTurn[];
  artefacts: Artefact[];
}) {
  if (turns.length === 0) {
    return (
      <p className="px-4 py-6 text-[13px] text-text-dim">
        No turns were recorded. This run was created but never started.
      </p>
    );
  }

  return (
    <ol className="relative space-y-6 border-l border-line px-4 py-4 pl-4">
      {turns.map((turn) => (
        <TurnCard
          key={turn.index}
          turn={turn}
          run={run}
          artefacts={artefacts}
        />
      ))}
    </ol>
  );
}
