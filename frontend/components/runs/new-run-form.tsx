"use client";

/**
 * Configure and start a run.
 *
 * Five steps on one page with the configuration summarised beside them, so
 * the operator sees the whole run while changing one part of it. The review
 * restates every value before anything is created.
 *
 * Create and start are two API calls. If the second fails the run exists,
 * and the form says so with a link to it rather than inviting a duplicate.
 * Starting runs in the background on the server; the run page follows it.
 *
 * The bot's side is either a server adapter or one of the workspace's own
 * connected bots. A connected bot is offered only from the scenario's own
 * project, picks its mode itself (text bot -> text_bot_test, voice bot ->
 * external_bot_test), and can start a run only once a connection check has
 * succeeded - the API refuses anything else, and so does this form.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState, type ReactNode } from "react";
import { AlertTriangle, Check, Loader2, Plug, PlayCircle } from "lucide-react";

import { Field, Input, Select } from "@/components/ui/field";
import { failureMessage } from "@/components/ui/interactive";
import { Button, EmptyState, Panel, cx, linkClass } from "@/components/ui/primitives";
import { Badge, IntegrationStatusBadge, MODE_COPY } from "@/components/ui/status";
import { api } from "@/lib/api/client";
import { CODECS, type ConditionDraft, NUMERIC_CONDITIONS, SAMPLE_RATES_HZ, buildAudioConditions } from "@/lib/conditions";
import type { BotAdapters, BotIntegration, ExecutionMode, NoiseProfile, ScenarioSummary } from "@/lib/api/types";

/** Run-level presets (`NoiseProfile` in the pipeline), distinct from a scenario's environment. */
const NOISE_PROFILES: { value: NoiseProfile; label: string; blurb: string }[] = [
  { value: "clean", label: "Clean", blurb: "No degradation: a deliberate choice of condition, not a skipped stage." },
  { value: "telephony_bandwidth", label: "Telephony bandwidth", blurb: "Band-limited to what a phone call carries." },
  { value: "light_background_noise", label: "Light background noise", blurb: "A quiet room with something happening in it." },
  { value: "moderate_background_noise", label: "Moderate background noise", blurb: "A street or a shop." },
  { value: "heavy_background_noise", label: "Heavy background noise", blurb: "The hardest condition this engine simulates." },
];

const MODE_BLURB: Record<string, string> = {
  offline_simulation: "Decisions only. No audio is synthesised, degraded or transcribed: the fastest way to check a scenario's logic.",
  audio_fixture_test: "Every stage runs with the bot stubbed by fixture audio. Establishes that the pipeline works, not that any bot does.",
  external_bot_test:
    "Talks to an external voice bot: streamed over the voice protocol (ws_voice), or paused each turn for you to supply its reply (manual). The only audio mode whose results describe a real bot.",
  text_bot_test: "Exchanges text with an external bot over the HTTP text protocol. Describes what the bot says, nothing about audio.",
};

/** The adapter each mode can use, best first. The engine refuses a pairing the mode cannot describe. */
const MODE_ADAPTERS: Record<string, string[]> = {
  offline_simulation: ["scripted", "manual"],
  audio_fixture_test: ["scripted"],
  external_bot_test: ["ws_voice", "manual"],
  text_bot_test: ["http"],
};

function preferredAdapter(mode: string, adapters: BotAdapters): string {
  const usable = adapters.adapters.filter((a) => a.available).map((a) => a.name);
  return (MODE_ADAPTERS[mode] ?? []).find((name) => usable.includes(name)) ?? adapters.selected;
}

export interface ScenarioOption extends ScenarioSummary {
  suite_label: string;
  /** The suite's project: a connected bot is offered only from the same one. */
  project_id?: string;
}

export function NewRunForm({
  scenarios,
  adapters,
  integrations = [],
  initialScenarioId,
  initialIntegrationId,
}: {
  scenarios: ScenarioOption[];
  adapters: BotAdapters;
  integrations?: BotIntegration[];
  initialScenarioId?: string;
  initialIntegrationId?: string;
}) {
  const router = useRouter();
  const modes = adapters.execution_modes as ExecutionMode[];
  const [scenarioId, setScenarioId] = useState(scenarios.some((s) => s.id === initialScenarioId) ? (initialScenarioId ?? "") : "");
  const [mode, setMode] = useState<ExecutionMode>(
    modes.includes("audio_fixture_test") ? "audio_fixture_test" : (modes[0] ?? "offline_simulation"),
  );
  const [adapter, setAdapter] = useState(() => preferredAdapter(mode, adapters));
  const [integrationId, setIntegrationId] = useState<string | null>(null);
  const [noise, setNoise] = useState<NoiseProfile | "">("");
  const [degrade, setDegrade] = useState(true);
  const [seed, setSeed] = useState("");
  const [maxTurns, setMaxTurns] = useState("");
  const [bargeIn, setBargeIn] = useState("");
  const [conditions, setConditions] = useState<ConditionDraft>({ codec: "", sample_rate_hz: "", numbers: {} });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [orphan, setOrphan] = useState<string | null>(null);

  const scenario = useMemo(() => scenarios.find((s) => s.id === scenarioId) ?? null, [scenarioId, scenarios]);
  const built = buildAudioConditions(conditions);
  const declared = built.body ? Object.keys(built.body).length : 0;
  const adapterInfo = adapters.adapters.find((a) => a.name === adapter);
  const ownBots = useMemo(
    () => integrations.filter((i) => !scenario?.project_id || i.project_id === scenario.project_id),
    [integrations, scenario],
  );
  const integration = ownBots.find((i) => i.id === integrationId) ?? null;
  const botReady = integration ? integration.check_status === "connected" : Boolean(adapterInfo?.available);
  const canBargeIn = integration ? integration.declared.supports_caller_barge_in : adapterInfo?.supports_caller_barge_in === true;

  function chooseIntegration(chosen: BotIntegration) {
    setIntegrationId(chosen.id);
    const fits = chosen.declared.execution_mode;
    if (modes.includes(fits)) setMode(fits);
  }

  // Preselect a bot named in the URL (from "Test this bot" on its page) once,
  // when it exists and is usable; anything else is left for the user to pick.
  const [preselected, setPreselected] = useState(false);
  if (!preselected && initialIntegrationId) {
    setPreselected(true);
    const named = integrations.find((i) => i.id === initialIntegrationId);
    if (named && named.check_status === "connected") chooseIntegration(named);
  }
  const movesAudio = mode !== "offline_simulation" && mode !== "text_bot_test";
  const suites = useMemo(() => [...new Set(scenarios.map((s) => s.suite_label))], [scenarios]);
  const bargeInProblem =
    canBargeIn && bargeIn.trim() !== "" && (!Number.isFinite(Number(bargeIn)) || Number(bargeIn) < 100 || Number(bargeIn) > 10000)
      ? "Between 100 and 10000 ms."
      : null;
  const turnsProblem = maxTurns.trim() !== "" && !(Number.isInteger(Number(maxTurns)) && Number(maxTurns) >= 1 && Number(maxTurns) <= 100) ? "A whole number from 1 to 100." : null;

  if (scenarios.length === 0) {
    return (
      <Panel>
        <EmptyState title="There are no scenarios to run">
          A run executes a scenario. On{" "}
          <Link href="/app/scenarios" className={linkClass}>
            Scenarios
          </Link>{" "}
          build one or start from the reference library.
        </EmptyState>
      </Panel>
    );
  }

  async function launch() {
    if (!scenario) return;
    if (built.problem || bargeInProblem || turnsProblem) {
      setError(built.problem ?? bargeInProblem ?? turnsProblem);
      return;
    }
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
        audio_conditions: built.body,
        caller_barge_in_after_ms: canBargeIn && bargeIn.trim() !== "" ? Number(bargeIn) : null,
        bot_adapter: integration ? null : adapter || null,
        bot_integration_id: integration?.id ?? null,
      });
      runId = created.run_id;
    } catch (cause) {
      setError(failureMessage(cause, "The run could not be created."));
      setBusy(false);
      return;
    }
    try {
      await api.startRunInBackground(runId);
    } catch (cause) {
      setOrphan(runId);
      setError(failureMessage(cause, "The run was created but did not start."));
      setBusy(false);
      return;
    }
    router.push(`/app/runs/${runId}`);
  }

  return (
    <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
      <ol className="min-w-0 space-y-4">
        <Step n={1} title="Scenario" done={Boolean(scenario)} description="The language comes with it: a run cannot change what the scenario defines.">
          <Field id="run-scenario" label="Scenario">
            <Select value={scenarioId} onChange={(e) => setScenarioId(e.target.value)}>
              <option value="">Choose a scenario…</option>
              {suites.map((suite) => (
                <optgroup key={suite} label={suite}>
                  {scenarios
                    .filter((s) => s.suite_label === suite)
                    .map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name} · {s.language}
                      </option>
                    ))}
                </optgroup>
              ))}
            </Select>
          </Field>
          {scenario ? (
            <p className="mt-2 text-[13px] leading-relaxed text-text-3">
              {scenario.description ?? "No description."}{" "}
              <Link href={`/app/scenarios/${scenario.id}`} className={linkClass}>
                Open scenario
              </Link>
            </p>
          ) : null}
        </Step>

        <Step n={2} title="Execution mode" done description="How much of the system the run exercises, and so what its result can be said to establish.">
          <div className="grid gap-2">
            {modes.map((value) => (
              <label
                key={value}
                className={cx(
                  "flex cursor-pointer gap-3 rounded-md border p-3 transition-colors",
                  mode === value ? "border-accent bg-accent-soft/50" : "border-line hover:border-line-strong",
                )}
              >
                <input
                  type="radio"
                  name="mode"
                  checked={mode === value}
                  onChange={() => {
                    setMode(value);
                    setAdapter(preferredAdapter(value, adapters));
                    if (integration && integration.declared.execution_mode !== value) setIntegrationId(null);
                  }}
                  className="mt-0.5 size-4 shrink-0"
                />
                <span className="min-w-0">
                  <span className="text-[14px] font-medium text-text">{MODE_COPY[value]?.label ?? value}</span>
                  <span className="mt-0.5 block text-[12px] leading-relaxed text-text-3">{MODE_BLURB[value] ?? ""}</span>
                </span>
              </label>
            ))}
          </div>
          <p className="mt-3 flex gap-2 text-[12px] leading-relaxed text-text-3">
            <AlertTriangle aria-hidden="true" className="mt-0.5 size-3.5 shrink-0 text-warn" />
            {adapters.telephony_status}
          </p>
        </Step>

        <Step n={3} title="Bot" done={botReady} description="Where the bot's side of the conversation comes from: one of your connected bots, or an adapter this server provides.">
          <fieldset className="mb-4 space-y-2">
            <legend className="mb-2 flex w-full flex-wrap items-center justify-between gap-2 text-[13px] font-medium text-text">
              <span>Your connected bots</span>
              <Link href="/app/bots/connect" className={cx(linkClass, "text-[12px] font-normal")}>
                Connect your chatbot
              </Link>
            </legend>
            {ownBots.length === 0 ? (
              <p className="rounded-md border border-dashed border-line px-3 py-3 text-[12px] leading-relaxed text-text-3">
                {scenario?.project_id && integrations.length > 0
                  ? "None in this scenario's project. A run can use a connected bot only from its own project."
                  : "None yet. Connect the chatbot you already run, check the connection, and it appears here."}
              </p>
            ) : (
              ownBots.map((item) => {
                const ready = item.check_status === "connected";
                return (
                  <label
                    key={item.id}
                    className={cx(
                      "flex gap-3 rounded-md border p-3 transition-colors",
                      integrationId === item.id ? "border-accent bg-accent-soft/50" : "border-line",
                      ready ? "cursor-pointer hover:border-line-strong" : "cursor-not-allowed opacity-60",
                    )}
                  >
                    <input
                      type="radio"
                      name="adapter"
                      checked={integrationId === item.id}
                      disabled={!ready}
                      onChange={() => chooseIntegration(item)}
                      className="mt-0.5 size-4 shrink-0"
                    />
                    <span className="min-w-0">
                      <span className="flex flex-wrap items-center gap-2">
                        <Plug aria-hidden="true" className="size-3.5 text-text-3" />
                        <span className="text-[14px] font-medium text-text">{item.name}</span>
                        <IntegrationStatusBadge status={item.check_status} />
                        <Badge tone="idle">{item.protocol === "http" ? "Text bot" : "Voice bot"}</Badge>
                      </span>
                      <span className="mt-1 block truncate font-mono text-[12px] text-text-3">{item.url}</span>
                      {!ready ? (
                        <span className="mt-1 block text-[12px] text-warn">
                          Check its connection first.{" "}
                          <Link href={`/app/bots/${item.id}`} className={linkClass}>
                            Open
                          </Link>
                        </span>
                      ) : (
                        <span className="mt-1 block text-[12px] text-text-3">
                          Runs as {MODE_COPY[item.declared.execution_mode]?.label ?? item.declared.execution_mode}.
                        </span>
                      )}
                    </span>
                  </label>
                );
              })
            )}
          </fieldset>
          <p className="mb-2 text-[13px] font-medium text-text">Server adapters</p>
          <div className="grid gap-2">
            {adapters.adapters.map((item) => {
              const fits = (MODE_ADAPTERS[mode] ?? []).includes(item.name);
              return (
                <label
                  key={item.name}
                  className={cx(
                    "flex gap-3 rounded-md border p-3 transition-colors",
                    !integration && adapter === item.name ? "border-accent bg-accent-soft/50" : "border-line",
                    item.available && fits ? "cursor-pointer hover:border-line-strong" : "cursor-not-allowed opacity-60",
                  )}
                >
                  <input
                    type="radio"
                    name="adapter"
                    checked={!integration && adapter === item.name}
                    disabled={!item.available || !fits}
                    onChange={() => {
                      setIntegrationId(null);
                      setAdapter(item.name);
                    }}
                    className="mt-0.5 size-4 shrink-0"
                  />
                  <span className="min-w-0">
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="text-[14px] font-medium text-text">{item.display_name}</span>
                      <Badge tone={item.contacts_external_system ? "ink" : "idle"}>
                        {item.contacts_external_system ? "Contacts an external bot" : "Sends nowhere"}
                      </Badge>
                    </span>
                    {!item.available ? (
                      <span className="mt-1 block text-[12px] text-warn">Not configured: {item.unavailable_reason}</span>
                    ) : !fits ? (
                      <span className="mt-1 block text-[12px] text-text-3">Not used by this mode.</span>
                    ) : item.notes[0] ? (
                      <span className="mt-1 block text-[12px] leading-relaxed text-text-3">{item.notes[0]}</span>
                    ) : null}
                  </span>
                </label>
              );
            })}
          </div>
          <div className="mt-4 rounded-md border border-line p-3">
            <Field
              id="run-barge-in"
              label="Caller interrupts the bot after (ms)"
              optional
              error={bargeInProblem}
              hint={
                canBargeIn
                  ? "Once the bot has spoken this long in each reply, the caller talks over it, and the run records whether and how fast the bot stopped. It re-sends the start of the caller's own turn: it tests yielding, not understanding."
                  : "Only an adapter with a live audio stream (ws_voice) can talk over the bot. Sequential turns cannot, so it is not offered rather than simulated."
              }
            >
              <Input
                type="number"
                inputMode="numeric"
                min={100}
                max={10000}
                step={50}
                disabled={!canBargeIn}
                value={canBargeIn ? bargeIn : ""}
                onChange={(e) => setBargeIn(e.target.value)}
                placeholder={canBargeIn ? "Off" : "Not supported by this adapter"}
                className="sm:w-60"
              />
            </Field>
          </div>
        </Step>

        <Step
          n={4}
          title="Audio conditions"
          done
          description={
            movesAudio
              ? "Simulated, not field recordings. Leave fields empty to keep what the scenario declares."
              : "This mode moves no audio, so conditions are recorded as not enforced. You can still set them."
          }
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              id="run-noise"
              label="Noise profile"
              hint={noise === "" ? "Keeps the scenario's declared environment." : NOISE_PROFILES.find((p) => p.value === noise)?.blurb}
            >
              <Select value={noise} onChange={(e) => setNoise(e.target.value as NoiseProfile | "")}>
                <option value="">The scenario&rsquo;s own environment</option>
                {NOISE_PROFILES.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </Select>
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field id="run-seed" label="Seed" optional hint="Fixed so noise reproduces exactly.">
                <Input type="number" inputMode="numeric" value={seed} onChange={(e) => setSeed(e.target.value)} placeholder="Server's" />
              </Field>
              <Field id="run-turns" label="Turn ceiling" optional error={turnsProblem} hint="The lower of this and the scenario's wins.">
                <Input type="number" inputMode="numeric" min={1} max={100} value={maxTurns} onChange={(e) => setMaxTurns(e.target.value)} placeholder="Scenario's" />
              </Field>
            </div>
          </div>
          <label className="mt-4 flex cursor-pointer items-start gap-2.5">
            <input type="checkbox" checked={degrade} onChange={(e) => setDegrade(e.target.checked)} className="mt-0.5 size-4" />
            <span>
              <span className="block text-[14px] text-text">Degrade the caller&rsquo;s audio before sending it</span>
              <span className="mt-0.5 block text-[12px] leading-relaxed text-text-3">
                Off sends the original, which is different from a clean profile: that is a deliberate condition, not a stage that did not run.
              </span>
            </span>
          </label>
          <details className="mt-4 rounded-md border border-line" open={declared > 0}>
            <summary className="flex cursor-pointer flex-wrap items-center justify-between gap-2 px-3 py-2.5 text-[14px] font-medium text-text">
              <span>Line conditions{declared > 0 ? ` · ${declared} set` : ""}</span>
              <span className="text-[12px] font-normal text-text-3">override the scenario for this run only</span>
            </summary>
            <div className="grid gap-4 border-t border-line p-3 sm:grid-cols-2">
              <Field id="run-codec" label="Codec" optional>
                <Select value={conditions.codec} onChange={(e) => setConditions({ ...conditions, codec: e.target.value })}>
                  <option value="">The scenario&rsquo;s (none if undeclared)</option>
                  {CODECS.map(([value, text]) => (
                    <option key={value} value={value}>
                      {text}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field id="run-rate" label="Sample rate" optional>
                <Select value={conditions.sample_rate_hz} onChange={(e) => setConditions({ ...conditions, sample_rate_hz: e.target.value })}>
                  <option value="">The scenario&rsquo;s</option>
                  {SAMPLE_RATES_HZ.map((rate) => (
                    <option key={rate} value={String(rate)}>
                      {rate.toLocaleString("en-IN")} Hz
                    </option>
                  ))}
                </Select>
              </Field>
              {NUMERIC_CONDITIONS.map((c) => (
                <Field key={c.key} id={`run-${c.key}`} label={`${c.label} (${c.unit})`} optional hint={c.hint}>
                  <Input
                    type="number"
                    inputMode="decimal"
                    min={c.min}
                    max={c.max}
                    step={c.integer ? 1 : "any"}
                    placeholder={`${c.min} to ${c.max}`}
                    value={conditions.numbers[c.key] ?? ""}
                    onChange={(e) => setConditions({ ...conditions, numbers: { ...conditions.numbers, [c.key]: e.target.value } })}
                  />
                </Field>
              ))}
              {built.problem ? (
                <p role="alert" className="text-[12px] font-medium text-bad sm:col-span-2">
                  {built.problem}
                </p>
              ) : null}
            </div>
          </details>
        </Step>
      </ol>

      <aside className="min-w-0 xl:sticky xl:top-6 xl:self-start">
        <div className="rounded-lg border border-line bg-bg shadow-1">
          <div className="border-b border-line px-4 py-3">
            <h2 className="text-[14px] font-semibold text-text">5 · Review and start</h2>
            <p className="mt-0.5 text-[12px] text-text-3">Exactly what will be sent.</p>
          </div>
          <dl className="divide-y divide-line text-[13px]">
            <Row label="Scenario">{scenario?.name ?? "Not chosen"}</Row>
            <Row label="Language" mono>
              {scenario?.language ?? "—"}
            </Row>
            <Row label="Mode">{MODE_COPY[mode]?.label ?? mode}</Row>
            <Row label="Bot" mono={!integration}>
              {integration ? `${integration.name} (connected bot)` : adapter}
            </Row>
            <Row label="Barge-in" mono>
              {canBargeIn && bargeIn ? `${bargeIn} ms` : "off"}
            </Row>
            <Row label="Noise">{noise === "" ? "scenario's" : NOISE_PROFILES.find((p) => p.value === noise)?.label}</Row>
            <Row label="Line conditions">{declared === 0 ? "scenario's" : `${declared} set`}</Row>
            <Row label="Degrade caller audio">{degrade ? "yes" : "no"}</Row>
            <Row label="Seed" mono>
              {seed || "server's"}
            </Row>
            <Row label="Turn ceiling" mono>
              {maxTurns || "scenario's"}
            </Row>
          </dl>
          <div className="space-y-3 border-t border-line p-4">
            {error ? (
              <div role="alert" className="rounded-md border border-bad/25 bg-bad-soft px-3 py-2.5">
                <p className="text-[13px] font-medium text-bad">{orphan ? "The run was created but did not start" : "The run was not created"}</p>
                <p className="mt-1 break-words text-[12px] leading-relaxed text-text-2">{error}</p>
                {orphan ? (
                  <Link href={`/app/runs/${orphan}`} className={cx(linkClass, "mt-2 inline-block text-[12px]")}>
                    Open run {orphan.slice(0, 8)}
                  </Link>
                ) : null}
              </div>
            ) : null}
            <Button tone="primary" size="lg" className="w-full" onClick={() => void launch()} disabled={!scenario || busy || !botReady} aria-busy={busy}>
              {busy ? <Loader2 aria-hidden="true" className="size-4 animate-spin" /> : <PlayCircle aria-hidden="true" className="size-4" />}
              {busy ? "Starting…" : "Start test run"}
            </Button>
            <p className="text-[12px] leading-relaxed text-text-3">
              {!scenario
                ? "Choose a scenario to enable this."
                : integration
                  ? `The run talks to ${integration.name} at ${hostOf(integration.url)}; its replies are recorded as received from it.`
                  : adapter === "manual"
                  ? "The manual adapter pauses at each bot turn; you supply the reply on the run page."
                  : "The run executes on the server; its page follows it live."}
            </p>
          </div>
        </div>
      </aside>
    </div>
  );
}

function Step({ n, title, description, done, children }: { n: number; title: string; description?: string; done: boolean; children: ReactNode }) {
  return (
    <li className="rounded-lg border border-line bg-bg shadow-1">
      <div className="flex items-start gap-3 border-b border-line px-4 py-3.5 sm:px-5">
        <span
          aria-hidden="true"
          className={cx(
            "flex size-6 shrink-0 items-center justify-center rounded-full font-mono text-[11px] font-medium",
            done ? "bg-text text-bg" : "border border-line-strong text-text-3",
          )}
        >
          {done ? <Check className="size-3.5" /> : n}
        </span>
        <div className="min-w-0">
          <h2 className="text-[15px] font-semibold text-text">
            <span className="sr-only">Step {n}: </span>
            {title}
          </h2>
          {description ? <p className="mt-0.5 text-[13px] leading-relaxed text-text-3">{description}</p> : null}
        </div>
      </div>
      <div className="px-4 py-4 sm:px-5">{children}</div>
    </li>
  );
}

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

function Row({ label, children, mono = false }: { label: string; children: ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 px-4 py-2">
      <dt className="shrink-0 text-[12px] text-text-3">{label}</dt>
      <dd className={cx("min-w-0 truncate text-right text-text", mono && "font-mono text-[12px]")}>{children}</dd>
    </div>
  );
}
