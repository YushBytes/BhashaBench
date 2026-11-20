/**
 * The hero's product preview: the workspace's scenario and conversation
 * views, drawn as live HTML from the shipped reference scenario
 * `scenarios/demo/tamil_crop_insurance.yaml`.
 *
 * Nothing here is a fabricated result. The scenario values are quoted from
 * that file. The caller's first turn is what the deterministic caller says
 * for it - its opening template "வணக்கம், நான் {identity}. {objective}"
 * filled with the file's own fields - and the script runs under it are
 * computed from that text. The bot's side is shown waiting, because no bot
 * reply exists to quote, and the metrics say why they have no value yet.
 */

import { CircleSlash, Mic, Radio, Waves } from "lucide-react";

import { scriptRuns } from "@/lib/script";

const IDENTITY = "தஞ்சாவூர் பக்கத்துல நெல் விவசாயம் பண்றவன்";
const OBJECTIVE =
  "Samba season-ல மழையால பயிர் சேதமாச்சு, அதுக்கு crop insurance claim போட்டிருக்கேன். " +
  "அந்த claim assess ஆயிடுச்சா, எவ்வளவு amount வரும்னு தெரிஞ்சுக்கணும்.";
const OPENING = `வணக்கம், நான் ${IDENTITY}. ${OBJECTIVE}`;

const OUTCOMES = [
  "Confirm the policy number back to the caller",
  "State the claim status",
  "State the assessed payout amount",
  "State when the payment will arrive",
];

const SCRIPT_TONE: Record<string, string> = {
  Taml: "bg-night-3 text-night-text",
  Latn: "bg-night-accent/20 text-[#c9d8ff]",
};

export function ProductPreview() {
  const runs = scriptRuns(OPENING);
  const switches = runs.length - 1;
  return (
    <div className="on-night overflow-hidden rounded-xl border border-night-line bg-night text-night-text shadow-pop">
      {/* Window chrome */}
      <div className="flex items-center gap-3 border-b border-night-line px-4 py-2.5">
        <span className="flex gap-1.5" aria-hidden="true">
          <span className="size-2.5 rounded-full bg-night-line" />
          <span className="size-2.5 rounded-full bg-night-line" />
          <span className="size-2.5 rounded-full bg-night-line" />
        </span>
        <span className="truncate font-mono text-[11px] text-night-muted">
          scenarios / demo / tamil_crop_insurance
        </span>
        <span className="ml-auto hidden rounded-full border border-night-line px-2 py-0.5 font-mono text-[10px] text-night-muted sm:inline">
          reference library
        </span>
      </div>

      <div className="grid md:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        {/* Scenario */}
        <div className="border-b border-night-line p-4 md:border-b-0 md:border-r sm:p-5">
          <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-night-muted">Scenario</p>
          <p className="mt-2 text-[15px] font-semibold tracking-[-0.01em]">Crop-insurance claim, rural line</p>
          <dl className="mt-4 space-y-3 text-[12px]">
            <Row label="Language">
              <span lang="ta-IN">தமிழ்</span> <span className="font-mono text-night-muted">ta-IN</span>
            </Row>
            <Row label="Caller">Elderly farmer, speaks slowly</Row>
            <Row label="Mixing">
              <span className="font-mono">ta-IN + en-IN · 0.35</span>
            </Row>
            <Row label="Channel">
              <span className="font-mono">rural · 10 dB SNR · 8% loss</span>
            </Row>
          </dl>
          <p className="mt-5 text-[11px] font-medium uppercase tracking-[0.12em] text-night-muted">
            Expected outcomes
          </p>
          <ol className="mt-2 space-y-1.5">
            {OUTCOMES.map((outcome, index) => (
              <li key={outcome} className="flex gap-2 text-[12px] leading-snug text-night-text/90">
                <span className="font-mono text-night-muted">{index + 1}</span>
                {outcome}
              </li>
            ))}
          </ol>
        </div>

        {/* Conversation */}
        <div className="p-4 sm:p-5">
          <div className="flex items-center justify-between gap-2">
            <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-night-muted">Conversation</p>
            <span className="inline-flex items-center gap-1.5 font-mono text-[10px] text-night-muted">
              <Radio aria-hidden="true" className="size-3" /> ws_voice
            </span>
          </div>

          <div className="mt-3 rounded-lg border border-night-line bg-night-2 p-3.5">
            <div className="flex items-center gap-2 text-[12px]">
              <Mic aria-hidden="true" className="size-3.5 text-night-accent" />
              <span className="font-semibold">Caller</span>
              <span className="font-mono text-[10px] text-night-muted">turn 1 · rule engine</span>
            </div>
            <p lang="ta-IN" className="mt-2 text-[13px] leading-[1.7] text-night-text">
              {OPENING}
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-1" aria-label={`${switches} script switches`}>
              {runs.map((run, index) => (
                <span
                  key={index}
                  className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${SCRIPT_TONE[run.script] ?? "bg-night-3 text-night-muted"}`}
                >
                  {run.script} {run.words}
                </span>
              ))}
              <span className="ml-1 font-mono text-[10px] text-night-muted">{switches} switches</span>
            </div>
          </div>

          <div className="mt-2.5 rounded-lg border border-dashed border-night-line p-3.5">
            <div className="flex items-center gap-2 text-[12px]">
              <Waves aria-hidden="true" className="size-3.5 text-night-muted" />
              <span className="font-semibold">Your bot</span>
              <span className="font-mono text-[10px] text-night-muted">turn 2</span>
            </div>
            <p className="mt-2 text-[12px] leading-relaxed text-night-muted">
              Waiting for the reply. It is transcribed and timed, then scored once a reviewer records what
              the bot really said.
            </p>
          </div>

          <dl className="mt-4 grid grid-cols-3 gap-2">
            {["WER", "CER", "Latency p50"].map((metric) => (
              <div key={metric} className="rounded-md border border-night-line px-2.5 py-2">
                <dt className="font-mono text-[10px] text-night-muted">{metric}</dt>
                <dd className="mt-1 inline-flex items-center gap-1 text-[11px] text-night-muted">
                  <CircleSlash aria-hidden="true" className="size-3" /> no run yet
                </dd>
              </div>
            ))}
          </dl>
        </div>
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-2">
      <dt className="text-night-muted">{label}</dt>
      <dd className="min-w-0 text-night-text">{children}</dd>
    </div>
  );
}
