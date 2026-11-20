/**
 * The components that stop the interface overclaiming.
 *
 * The API carries fields that exist so a client cannot misrepresent a run -
 * `bot_audio_externally_received`, `uses_language_model`, `measurement_note`,
 * `settings_not_enforced` - and these render them. Structural rather than
 * copy, so a new page cannot forget to be honest.
 *
 * Every caveat is computed from the run, never from the mode label alone: a
 * run created as `external_bot_test` whose replies were fixtures reports
 * `bot_audio_externally_received: false`, and this says so.
 */

import type { ReactNode } from "react";
import { AlertTriangle, Info } from "lucide-react";

import { cx } from "@/components/ui/primitives";
import type { ExecutionMode, Run, SettingNotEnforced } from "@/lib/api/types";

type Level = "note" | "caution";

export function Caveat({ level = "note", title, children }: { level?: Level; title: string; children?: ReactNode }) {
  const Icon = level === "caution" ? AlertTriangle : Info;
  return (
    <div className={cx("flex gap-3 rounded-md border px-3.5 py-3", level === "caution" ? "border-warn/30 bg-warn-soft" : "border-line bg-bg")}>
      <Icon aria-hidden="true" className={cx("mt-0.5 size-4 shrink-0", level === "caution" ? "text-warn" : "text-text-3")} />
      <div className="min-w-0">
        <p className={cx("text-[13px] font-medium", level === "caution" ? "text-warn" : "text-text")}>{title}</p>
        {children ? <div className="mt-0.5 text-[13px] leading-relaxed text-text-2">{children}</div> : null}
      </div>
    </div>
  );
}

const MODE_EVIDENCE: Partial<Record<ExecutionMode, string>> = {
  offline_simulation: "This run moved no audio at all. It exercised the caller's decisions and nothing else.",
  audio_fixture_test:
    "Every stage ran, with the bot stubbed by fixture audio. It establishes that the pipeline works end to end, not that any bot does.",
};

/** Every caveat a run carries, derived from its fields. One source for the
 *  banner above the run's tabs and the full list in its evidence tab. */
export function caveatsFor(run: Run): { level: Level; title: string; body: string }[] {
  const caveats: { level: Level; title: string; body: string }[] = [];

  if (run.mode === "external_bot_test" && !run.bot_audio_externally_received) {
    caveats.push({
      level: "caution",
      title: "Labelled an external bot test, but no external audio arrived",
      body: "Every bot reply in this run came from inside the process. The run does not establish anything about an external bot, whatever it was created as.",
    });
  } else if (run.mode === "text_bot_test") {
    caveats.push(
      run.bot_text_externally_received
        ? {
            level: "note",
            title: "An external bot answered in text",
            body: `${run.bot_text_replies_received} replies came from the bot over HTTP. This tests what the bot says. No audio moved, so it establishes nothing about speech recognition, synthesis or the line.`,
          }
        : {
            level: "caution",
            title: "Labelled a text bot test, but no reply came from the bot",
            body: "No reply in this run was received from the external bot. It does not establish anything about a bot, whatever it was created as.",
          },
    );
  } else if (run.mode !== "external_bot_test") {
    caveats.push({
      level: "note",
      title: "No external bot was contacted",
      body: MODE_EVIDENCE[run.mode] ?? "Bot audio did not come from outside this process.",
    });
  }

  if (run.caller_phrase_review === "unreviewed") {
    caveats.push({
      level: "caution",
      title: "The caller's phrases in this language are unreviewed",
      body: `No fluent speaker has reviewed the caller's ${run.language || "phrase table"} phrases; they were machine-written. A bot that misunderstands one may be failing the caller rather than the language, so read a failed turn with that in mind.`,
    });
  }

  if (!run.uses_language_model) {
    caveats.push({
      level: "note",
      title: "The caller is a rule engine, not a language model",
      body: "Utterances come from fixed per-language phrase tables and a state machine. Gnani Evon is not integrated. An utterance no rule anticipates produces a clarification request: that is the ceiling of a rule engine, and it bounds what this run can show.",
    });
  }

  if (run.stt_provider === "fake" || run.tts_provider === "fake") {
    caveats.push({
      level: "caution",
      title: "Offline speech providers",
      body: "Speech in this run was synthesised or transcribed by the offline fake, so transcripts are scripted, not recognised. No accuracy figure from this run describes Gnani or any other speech engine.",
    });
  }

  return caveats;
}

export function RunEvidence({ run }: { run: Run }) {
  const caveats = caveatsFor(run);
  return (
    <div className="space-y-2">
      {caveats.map((c) => (
        <Caveat key={c.title} level={c.level} title={c.title}>
          {c.body}
        </Caveat>
      ))}
      <SettingsNotEnforced settings={run.settings_not_enforced} />
    </div>
  );
}

/**
 * The cautions only: where the run's label and its evidence disagree, or its
 * speech was scripted. Shown above the tabs so no reader can miss them.
 */
export function RunCautions({ run }: { run: Run }) {
  const cautions = caveatsFor(run).filter((c) => c.level === "caution");
  if (cautions.length === 0) return null;
  return (
    <div className="space-y-2">
      {cautions.map((c) => (
        <Caveat key={c.title} level="caution" title={c.title}>
          {c.body}
        </Caveat>
      ))}
    </div>
  );
}

/**
 * Scenario settings the run declared and nothing enforced, rendered from
 * `settings_not_enforced`, never a hard-coded list. A missing field means the
 * run predates the record: unknown, said as such, never "all enforced".
 */
export function SettingsNotEnforced({ settings }: { settings: SettingNotEnforced[] | null | undefined }) {
  if (settings == null) {
    return (
      <Caveat title="Declared-but-not-enforced settings were not recorded for this run">
        This run predates that record, so which of its scenario settings were enforced is unknown. It does not mean they all were.
      </Caveat>
    );
  }
  if (settings.length === 0) return null;
  return (
    <Caveat title="Declared by the scenario, not enforced by this run">
      <ul className="mt-1 space-y-1">
        {settings.map((entry) => (
          <li key={entry.setting}>
            <code className="font-mono text-[12px] text-text">{entry.setting}</code>
            {" = "}
            <code className="break-all font-mono text-[12px]">{JSON.stringify(entry.declared)}</code>
            {" — "}
            {entry.reason}
          </li>
        ))}
      </ul>
    </Caveat>
  );
}

/** The API's own sentence about what its counts mean, verbatim. */
export function MeasurementNote({ note }: { note: string }) {
  if (!note) return null;
  return <p className="text-[12px] leading-relaxed text-text-3">{note}</p>;
}
