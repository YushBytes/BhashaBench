"use client";

/**
 * Configure and launch a run.
 *
 * A stepped form rather than a wizard of separate screens: an operator
 * configuring a run wants to see the whole configuration while changing one
 * part of it, and a five-screen flow hides the thing being reviewed. The
 * steps are headings with a progress rail, and the review step restates
 * every value before anything is created.
 *
 * **It calls the real endpoints and shows the real errors.** Create and
 * start are two API calls; if the second fails the run still exists, and
 * the form says so with a link to it rather than pretending nothing
 * happened.
 */

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { Badge, ModeBadge } from "@/components/ui/status";
import {
  Button,
  EmptyState,
  Panel,
  PanelHeader,
  cx,
} from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api/client";
import { langAttr } from "@/lib/format";
import type {
  BotAdapters,
  ExecutionMode,
  NoiseProfile,
  ScenarioSummary,
} from "@/lib/api/types";

const NOISE_PROFILES: Array<{ value: NoiseProfile; label: string; blurb: string }> = [
  {
    value: "clean",
    label: "Clean",
    blurb: "No degradation. A deliberate choice of condition, not a skipped stage.",
  },
  {
    value: "telephony_bandwidth",
    label: "Telephony bandwidth",
    blurb: "Band-limited to what a phone call carries.",
  },
  {
    value: "light_background_noise",
    label: "Light background noise",
    blurb: "A quiet room with something happening in it.",
  },
  {
    value: "moderate_background_noise",
    label: "Moderate background noise",
    blurb: "A street or a shop. Noise is scaled from the signal's own RMS.",
  },
  {
    value: "heavy_background_noise",
    label: "Heavy background noise",
    blurb: "The hardest condition this engine simulates.",
  },
];

const MODE_BLURB: Record<string, string> = {
  offline_simulation:
    "Decisions only. No audio is synthesised, degraded or transcribed — the fastest way to check a scenario's logic.",
  audio_fixture_test:
    "Every stage runs with the bot stubbed by fixture audio. Establishes that the pipeline works, not that any bot does.",
  external_bot_test:
    "The run pauses at each turn and waits for you to supply the bot's reply. The only mode whose results describe a real bot.",
};

const field =
  "h-10 w-full rounded-md border border-line-strong bg-surface-raised px-2.5 " +
  "text-[13px] text-text transition-colors hover:border-[#3b4756] focus-visible:border-accent";

const legend = "text-[13px] font-semibold text-text";
const hint = "mt-1 text-[12px] leading-relaxed text-text-dim";

function Step({
  index,
  title,
  description,
  children,
  done,
}: {
  index: number;
  title: string;
  description?: string;
  children: React.ReactNode;
  done: boolean;
}) {
  return (
    <section className="relative grid grid-cols-[1.75rem_minmax(0,1fr)] gap-x-3 pb-6 last:pb-0">
      {/* The rail. Step numbers here carry real sequence information - the
          order is the order the decisions depend on each other. */}
      <div className="flex flex-col items-center">
        <span
          aria-hidden="true"
          className={cx(
            "flex size-7 shrink-0 items-center justify-center rounded-full border text-[11px] font-semibold tabular",
            done
              ? "border-accent-line bg-accent-dim text-accent"
              : "border-line-strong bg-surface-raised text-text-muted",
          )}
        >
          {index}
        </span>
        <span className="mt-1 w-px flex-1 bg-line" aria-hidden="true" />
      </div>

      <div className="min-w-0 pb-1">
        <h2 className={legend}>{title}</h2>
        {description ? <p className={hint}>{description}</p> : null}
        <div className="mt-3">{children}</div>
      </div>
    </section>
  );
}

export function NewTestForm({
  scenarios,
  adapters,
}: {
  scenarios: ScenarioSummary[];
  adapters: BotAdapters;
}) {
  const router = useRouter();

  const [scenarioId, setScenarioId] = useState<string>("");
  const [mode, setMode] = useState<ExecutionMode>(
    (adapters.execution_modes.includes("audio_fixture_test")
      ? "audio_fixture_test"
      : (adapters.execution_modes[0] as ExecutionMode)) ?? "offline_simulation",
  );
  const [noise, setNoise] = useState<NoiseProfile | "">("");
  const [degrade, setDegrade] = useState(true);
  const [seed, setSeed] = useState<string>("");
  const [maxTurns, setMaxTurns] = useState<string>("");
  const [adapter, setAdapter] = useState<string>(adapters.selected);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [orphan, setOrphan] = useState<string | null>(null);

  const scenario = useMemo(
    () => scenarios.find((item) => item.id === scenarioId) ?? null,
    [scenarioId, scenarios],
  );

  const modes = adapters.execution_modes as ExecutionMode[];

  if (scenarios.length === 0) {
    return (
      <Panel>
        <EmptyState title="There are no scenarios to run">
          A run executes a scenario, so the library has to hold at least one.
          Scenarios are authored as YAML and loaded through{" "}
          <code className="font-mono text-[12px]">
            POST /api/v1/suites/&#123;id&#125;/scenarios
          </code>{" "}
          or the <code className="font-mono text-[12px]">bhashabench</code> CLI.
          The repository ships six reference scenarios under{" "}
          <code className="font-mono text-[12px]">scenarios/</code>.
        </EmptyState>
      </Panel>
    );
  }

  async function launch() {
    if (!scenario) return;
    setBusy(true);
    setError(null);
    setOrphan(null);

    let runId: string;
    try {
      const created = await api.createRun({
        suite_id: scenario.suite_id,
        scenario_id: scenario.id,
        mode,
        noise_profile: noise === "" ? null : noise,
        seed: seed.trim() === "" ? null : Number(seed),
        max_turns: maxTurns.trim() === "" ? null : Number(maxTurns),
        degrade_caller_audio: degrade,
        bot_adapter: adapter || null,
      });
      runId = created.run_id;
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "The run could not be created.",
      );
      setBusy(false);
      return;
    }

    try {
      await api.startRun(runId);
    } catch (cause) {
      // The run exists. Saying "failed" without saying that would send the
      // operator to create a second one.
      setOrphan(runId);
      setError(
        cause instanceof ApiError
          ? cause.message
          : "The run was created but did not start.",
      );
      setBusy(false);
      return;
    }

    router.push(`/app/runs/${runId}`);
  }

  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-5 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <Panel className="p-4 sm:p-6">
        <Step index={1} title="Scenario" done={Boolean(scenario)}>
          <label className="sr-only" htmlFor="scenario">
            Scenario
          </label>
          <select
            id="scenario"
            className={field}
            value={scenarioId}
            onChange={(event) => setScenarioId(event.target.value)}
          >
            <option value="">Choose a scenario…</option>
            {scenarios.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} · {item.language}
              </option>
            ))}
          </select>
          {scenario?.description ? (
            <p className={hint}>{scenario.description}</p>
          ) : null}
        </Step>

        <Step
          index={2}
          title="Language"
          description="Taken from the scenario, not chosen here. The language is part of the test's definition; changing it would make the run a different test."
          done={Boolean(scenario)}
        >
          {scenario ? (
            <span
              className="inline-flex items-center gap-2 rounded-md border border-line-strong bg-surface-raised px-2.5 py-1.5 font-mono text-[13px] text-text"
              lang={langAttr(scenario.language)}
            >
              {scenario.language}
            </span>
          ) : (
            <p className="text-[13px] text-text-muted">Select a scenario first.</p>
          )}
        </Step>

        <Step
          index={3}
          title="Execution mode"
          description="How much of the system this run exercises — and therefore what its result can be said to establish."
          done
        >
          <div className="space-y-2">
            {modes.map((value) => (
              <label
                key={value}
                className={cx(
                  "flex cursor-pointer gap-3 rounded-md border p-3 transition-colors",
                  mode === value
                    ? "border-accent-line bg-accent-dim"
                    : "border-line bg-surface-raised hover:border-line-strong",
                )}
              >
                <input
                  type="radio"
                  name="mode"
                  value={value}
                  checked={mode === value}
                  onChange={() => setMode(value)}
                  className="mt-0.5 size-4 shrink-0 accent-[var(--accent)]"
                />
                <span className="min-w-0">
                  <span className="flex items-center gap-2">
                    <ModeBadge mode={value} />
                  </span>
                  <span className="mt-1 block text-[12px] leading-relaxed text-text-dim">
                    {MODE_BLURB[value] ?? ""}
                  </span>
                </span>
              </label>
            ))}
          </div>
          <p className="mt-2 text-[12px] leading-relaxed text-warn">
            {adapters.telephony_status}
          </p>
        </Step>

        <Step
          index={4}
          title="Acoustic conditions"
          description="Simulated conditions, not field recordings. Noise is scaled from the utterance's own RMS so the stated ratio holds, and the achieved ratio is asserted rather than assumed."
          done
        >
          <label className="sr-only" htmlFor="noise">
            Noise profile
          </label>
          <select
            id="noise"
            className={field}
            value={noise}
            onChange={(event) => setNoise(event.target.value as NoiseProfile | "")}
          >
            <option value="">Use the scenario&rsquo;s declared environment</option>
            {NOISE_PROFILES.map((profile) => (
              <option key={profile.value} value={profile.value}>
                {profile.label}
              </option>
            ))}
          </select>
          <p className={hint}>
            {noise === ""
              ? "The scenario declares its own acoustic environment. Leaving this alone keeps the test as authored."
              : NOISE_PROFILES.find((p) => p.value === noise)?.blurb}
          </p>

          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div>
              <label
                className="block text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted"
                htmlFor="seed"
              >
                Seed
              </label>
              <input
                id="seed"
                type="number"
                inputMode="numeric"
                className={cx(field, "mt-1")}
                value={seed}
                onChange={(event) => setSeed(event.target.value)}
                placeholder="Server default"
              />
              <p className={hint}>Fixed so the degradation reproduces exactly.</p>
            </div>
            <div>
              <label
                className="block text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted"
                htmlFor="max-turns"
              >
                Turn ceiling
              </label>
              <input
                id="max-turns"
                type="number"
                min={1}
                max={100}
                inputMode="numeric"
                className={cx(field, "mt-1")}
                value={maxTurns}
                onChange={(event) => setMaxTurns(event.target.value)}
                placeholder="Scenario default"
              />
              <p className={hint}>Applied on top of the scenario&rsquo;s own limit. The lowest wins.</p>
            </div>
          </div>

          <label className="mt-3 flex cursor-pointer items-start gap-2.5">
            <input
              type="checkbox"
              checked={degrade}
              onChange={(event) => setDegrade(event.target.checked)}
              className="mt-0.5 size-4 shrink-0 accent-[var(--accent)]"
            />
            <span className="text-[13px] text-text-dim">
              Degrade the caller&rsquo;s audio before sending it
              <span className="mt-0.5 block text-[12px] text-text-muted">
                Off sends the original. That is different from a clean profile,
                which is a deliberate choice of condition rather than a stage
                that did not run.
              </span>
            </span>
          </label>
        </Step>

        <Step
          index={5}
          title="Bot adapter"
          description="Where the bot's side of the conversation comes from."
          done
        >
          <div className="space-y-2">
            {adapters.adapters.map((item) => (
              <label
                key={item.name}
                className={cx(
                  "flex cursor-pointer gap-3 rounded-md border p-3 transition-colors",
                  adapter === item.name
                    ? "border-accent-line bg-accent-dim"
                    : "border-line bg-surface-raised hover:border-line-strong",
                )}
              >
                <input
                  type="radio"
                  name="adapter"
                  value={item.name}
                  checked={adapter === item.name}
                  onChange={() => setAdapter(item.name)}
                  className="mt-0.5 size-4 shrink-0 accent-[var(--accent)]"
                />
                <span className="min-w-0">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="text-[13px] font-medium text-text">
                      {item.display_name}
                    </span>
                    <Badge
                      tone={item.contacts_external_system ? "accent" : "idle"}
                      title={
                        item.contacts_external_system
                          ? "Using this adapter sends a request out of this process."
                          : "This adapter sends no request anywhere."
                      }
                    >
                      {item.contacts_external_system ? "Contacts external system" : "Sends nowhere"}
                    </Badge>
                  </span>
                  <ul className="mt-1 space-y-0.5">
                    {item.notes.map((note) => (
                      <li key={note} className="text-[12px] leading-relaxed text-text-dim">
                        {note}
                      </li>
                    ))}
                  </ul>
                </span>
              </label>
            ))}
          </div>
        </Step>

        <Step index={6} title="Review and start" done={Boolean(scenario)}>
          {error ? (
            <div className="mb-3 rounded-md border border-bad/40 bg-bad-dim px-3 py-2.5" role="alert">
              <p className="text-[13px] font-medium text-bad">
                {orphan ? "The run was created but did not start" : "The run was not created"}
              </p>
              <p className="mt-1 text-[12px] leading-relaxed text-text-dim">{error}</p>
              {orphan ? (
                <a
                  href={`/app/runs/${orphan}`}
                  className="mt-2 inline-block font-mono text-[12px] text-accent hover:underline"
                >
                  Open run {orphan.slice(0, 8)} →
                </a>
              ) : null}
            </div>
          ) : null}

          <Button
            tone="primary"
            onClick={launch}
            disabled={!scenario || busy}
            aria-busy={busy}
          >
            {busy ? "Starting…" : "Start test"}
          </Button>
          {!scenario ? (
            <p className={hint}>Choose a scenario to enable this.</p>
          ) : null}
        </Step>
      </Panel>

      {/* The review panel. Sticky on a wide screen so the configuration
          stays visible while the steps above it are changed. */}
      <div className="xl:sticky xl:top-20 xl:self-start">
        <Panel>
          <PanelHeader title="Configuration" description="What will be sent to the API." />
          <dl className="divide-y divide-line">
            <Row label="Scenario">{scenario?.name ?? "—"}</Row>
            <Row label="Language" mono>
              {scenario?.language ?? "—"}
            </Row>
            <Row label="Mode" mono>
              {mode}
            </Row>
            <Row label="Noise profile" mono>
              {noise === "" ? "scenario default" : noise}
            </Row>
            <Row label="Degrade caller audio" mono>
              {String(degrade)}
            </Row>
            <Row label="Seed" mono>
              {seed.trim() === "" ? "server default" : seed}
            </Row>
            <Row label="Turn ceiling" mono>
              {maxTurns.trim() === "" ? "scenario default" : maxTurns}
            </Row>
            <Row label="Bot adapter" mono>
              {adapter}
            </Row>
          </dl>
          <p className="border-t border-line px-4 py-3 text-[12px] leading-relaxed text-text-muted">
            Starting creates the run and executes it. A run in{" "}
            <span className="font-mono">external_bot_test</span> pauses at the
            first turn and waits for you to supply the bot&rsquo;s reply.
          </p>
        </Panel>
      </div>
    </div>
  );
}

function Row({
  label,
  children,
  mono = false,
}: {
  label: string;
  children: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 px-4 py-2">
      <dt className="shrink-0 text-[12px] text-text-muted">{label}</dt>
      <dd
        className={cx(
          "min-w-0 truncate text-right text-[13px] text-text",
          mono && "font-mono",
        )}
      >
        {children}
      </dd>
    </div>
  );
}
