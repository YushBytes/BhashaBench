"use client";

/**
 * The scenario builder: a guided editor over the scenario specification,
 * with the YAML source one tab away.
 *
 * Six sections, one visible at a time, so a long specification never shows
 * every field at once. The server's validator is the only judge: Save
 * validates first, and each field-addressed error is shown under its field
 * and counted on its section's tab. Only a document the server accepted is
 * stored, and the server validates it again on save.
 *
 * Starting templates are the shipped reference scenarios
 * (`GET /scenario-library`), parsed with the `yaml` package - which builds
 * plain data and never constructs code from the document.
 */

import { useRouter } from "next/navigation";
import { useMemo, useState, type ReactNode } from "react";
import { parse as parseYaml } from "yaml";
import {
  AlertCircle,
  AudioLines,
  CheckCircle2,
  FileCode2,
  Languages,
  ListChecks,
  Loader2,
  Plus,
  ShieldCheck,
  Trash2,
  UserRound,
  Wand2,
} from "lucide-react";

import { Field, Input, Select, Textarea, controlClass } from "@/components/ui/field";
import { failureMessage } from "@/components/ui/interactive";
import { Button, Notice, cx } from "@/components/ui/primitives";
import { api } from "@/lib/api/client";
import type { Language, LibraryScenario, ScenarioValidation } from "@/lib/api/types";
import { CODECS, NUMERIC_CONDITIONS, SAMPLE_RATES_HZ } from "@/lib/conditions";
import { toServerYaml } from "@/lib/server-yaml";
import {
  NAME_PATTERN,
  SCENARIO_NOISE_PROFILES,
  SPEAKING_STYLES,
  SWITCH_TRIGGERS,
  draftFromSpec,
  emptyDraft,
  sectionOf,
  slugify,
  specFromDraft,
  type Draft,
  type SectionId,
} from "@/lib/scenario-draft";

const SECTIONS: { id: SectionId; label: string; hint: string; icon: typeof ListChecks }[] = [
  { id: "basics", label: "Basics", hint: "Name, language, tags", icon: FileCode2 },
  { id: "caller", label: "Caller", hint: "Who is calling", icon: UserRound },
  { id: "goal", label: "Goal and outcomes", hint: "What must happen", icon: ListChecks },
  { id: "language", label: "Language and accent", hint: "Accent, code-mixing", icon: Languages },
  { id: "audio", label: "Audio conditions", hint: "Noise, codec, line", icon: AudioLines },
  { id: "rules", label: "Conversation rules", hint: "Interruptions, phrases", icon: ShieldCheck },
];

export interface BuilderProps {
  mode: "create" | "edit";
  scenarioId?: string;
  /** Suites the caller can add to (create mode). */
  suites: { id: string; label: string }[];
  initialSuiteId?: string;
  languages: Language[];
  library: LibraryScenario[] | null;
  initialSpec?: unknown;
  /** A reference-library key to start from (create mode). */
  initialTemplate?: string;
}

function fromTemplate(library: LibraryScenario[] | null, key: string | undefined): Draft | null {
  const entry = key ? library?.find((item) => item.key === key) : undefined;
  if (!entry) return null;
  try {
    return draftFromSpec(parseYaml(entry.yaml));
  } catch {
    return null;
  }
}

export function ScenarioBuilder({ mode, scenarioId, suites, initialSuiteId, languages, library, initialSpec, initialTemplate }: BuilderProps) {
  const router = useRouter();
  const [draft, setDraftState] = useState<Draft>(
    () =>
      (initialSpec ? draftFromSpec(initialSpec) : null) ??
      fromTemplate(library, initialTemplate) ??
      emptyDraft(languages[0]?.code ?? "hi-IN"),
  );
  const [suiteId, setSuiteId] = useState(initialSuiteId && suites.some((s) => s.id === initialSuiteId) ? initialSuiteId : (suites[0]?.id ?? ""));
  const [section, setSection] = useState<SectionId>("basics");
  const [tab, setTab] = useState<"guided" | "source">("guided");
  const [source, setSource] = useState("");
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [validation, setValidation] = useState<ScenarioValidation | null>(null);
  const [busy, setBusy] = useState<"validating" | "saving" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [template, setTemplate] = useState(fromTemplate(library, initialTemplate) ? (initialTemplate ?? "") : "");

  function setDraft(update: (d: Draft) => Draft) {
    setDraftState((d) => update(structuredClone(d)));
    setValidation(null);
  }

  const yaml = useMemo(() => (tab === "source" ? source : toServerYaml(specFromDraft(draft))), [tab, source, draft]);

  const errors = useMemo(() => {
    const map = new Map<string, string>();
    for (const e of validation?.valid === false ? validation.errors : []) map.set(e.field, e.message);
    return map;
  }, [validation]);
  const errorCount = (id: SectionId) => [...errors.keys()].filter((f) => sectionOf(f) === id).length;
  /** The first error on this path or under it. */
  const err = (path: string): string | null => {
    for (const [field, message] of errors) if (field === path || field.startsWith(`${path}.`)) return message;
    return null;
  };

  const language = languages.find((l) => l.code === draft.language) ?? null;

  function toSource() {
    setSource(toServerYaml(specFromDraft(draft)));
    setSourceError(null);
    setTab("source");
  }

  function toGuided() {
    try {
      setDraftState(draftFromSpec(parseYaml(source)));
      setSourceError(null);
      setTab("guided");
    } catch (cause) {
      setSourceError(`The YAML could not be read: ${cause instanceof Error ? cause.message : "parse error"}`);
    }
  }

  function applyTemplate(key: string) {
    setTemplate(key);
    const entry = library?.find((item) => item.key === key);
    if (!entry) return;
    try {
      const parsed = parseYaml(entry.yaml);
      setDraftState(draftFromSpec(parsed));
      setSource(entry.yaml);
      setValidation(null);
      setError(null);
      setSection("basics");
    } catch {
      setError("That reference scenario could not be read.");
    }
  }

  async function validate(): Promise<ScenarioValidation | null> {
    setBusy("validating");
    setError(null);
    try {
      const result = await api.validateScenario(yaml);
      setValidation(result);
      if (!result.valid && result.errors[0] && tab === "guided") setSection(sectionOf(result.errors[0].field));
      return result;
    } catch (cause) {
      setError(failureMessage(cause, "Validation failed."));
      return null;
    } finally {
      setBusy(null);
    }
  }

  async function save() {
    const result = await validate();
    if (!result?.valid) return;
    setBusy("saving");
    try {
      if (mode === "edit" && scenarioId) {
        const saved = await api.updateScenario(scenarioId, yaml);
        router.push(`/app/scenarios/${saved.id}?saved=1`);
      } else {
        const created = await api.createScenario(suiteId, yaml);
        router.push(`/app/scenarios/${created.id}?created=1`);
      }
      router.refresh();
    } catch (cause) {
      setError(failureMessage(cause, "The scenario was not saved."));
      setBusy(null);
    }
  }

  const ready = mode === "edit" || suiteId !== "";

  return (
    <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="min-w-0 space-y-4">
        {mode === "create" ? (
          <div className="grid gap-3 rounded-lg border border-line bg-bg p-4 shadow-1 sm:grid-cols-2">
            <Field id="builder-suite" label="Add to suite" hint={suites.length === 0 ? "Create a suite first; every scenario belongs to one." : undefined}>
              <Select value={suiteId} onChange={(e) => setSuiteId(e.target.value)} disabled={suites.length === 0}>
                {suites.length === 0 ? <option value="">No suite you can edit</option> : null}
                {suites.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field
              id="builder-template"
              label="Start from"
              hint={library === null ? "The reference library could not be loaded; start blank." : "A shipped reference scenario, ready to edit."}
            >
              <Select value={template} onChange={(e) => applyTemplate(e.target.value)} disabled={!library || library.length === 0}>
                <option value="">Blank scenario</option>
                {(library ?? []).map((item) => (
                  <option key={item.key} value={item.key}>
                    {item.name} · {item.language}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
        ) : null}

        <div className="flex items-center justify-between gap-3">
          <div role="tablist" aria-label="Editor" className="inline-flex rounded-md border border-line bg-bg p-0.5 shadow-1">
            {(
              [
                ["guided", "Guided", Wand2],
                ["source", "YAML source", FileCode2],
              ] as const
            ).map(([id, label, Icon]) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={tab === id}
                onClick={() => (id === "source" ? (tab === "guided" ? toSource() : null) : tab === "source" ? toGuided() : null)}
                className={cx(
                  "inline-flex h-8 items-center gap-1.5 rounded px-3 text-[13px] font-medium",
                  tab === id ? "bg-text text-bg" : "text-text-2 hover:text-text",
                )}
              >
                <Icon aria-hidden="true" className="size-3.5" />
                {label}
              </button>
            ))}
          </div>
          <a
            href="https://github.com/YushBytes/BhashaBench/blob/main/docs/SCENARIO_FORMAT.md"
            target="_blank"
            rel="noreferrer"
            className="text-[13px] font-medium text-accent hover:underline"
          >
            Format reference
          </a>
        </div>

        {tab === "source" ? (
          <div className="rounded-lg border border-line bg-bg shadow-1">
            <label htmlFor="builder-source" className="sr-only">
              Scenario YAML
            </label>
            <textarea
              id="builder-source"
              value={source}
              spellCheck={false}
              onChange={(e) => {
                setSource(e.target.value);
                setValidation(null);
              }}
              rows={28}
              className="block w-full resize-y rounded-lg bg-bg-soft p-4 font-mono text-[12.5px] leading-relaxed text-text focus-visible:outline-none"
            />
            {sourceError ? (
              <div className="border-t border-line p-3">
                <Notice tone="bad">{sourceError}</Notice>
              </div>
            ) : null}
            {validation?.valid === false ? (
              <ul role="alert" className="space-y-1 border-t border-line p-4 text-[12px] text-bad">
                {validation.errors.map((e, i) => (
                  <li key={`${e.field}-${i}`}>
                    <span className="font-mono">{e.field}</span>: {e.message}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : (
          <div className="grid min-w-0 gap-4 lg:grid-cols-[13rem_minmax(0,1fr)]">
            <nav aria-label="Scenario sections" className="flex gap-1 overflow-x-auto lg:flex-col">
              {SECTIONS.map((s) => {
                const count = errorCount(s.id);
                return (
                  <button
                    key={s.id}
                    type="button"
                    aria-current={section === s.id ? "step" : undefined}
                    onClick={() => setSection(s.id)}
                    className={cx(
                      "flex shrink-0 items-center gap-2.5 rounded-md border px-3 py-2 text-left transition-colors",
                      section === s.id ? "border-line-strong bg-bg shadow-1" : "border-transparent hover:bg-bg",
                    )}
                  >
                    <s.icon aria-hidden="true" className={cx("size-4 shrink-0", section === s.id ? "text-accent" : "text-text-3")} />
                    <span className="min-w-0">
                      <span className="block text-[13px] font-medium text-text">{s.label}</span>
                      <span className="hidden text-[11px] text-text-3 lg:block">{s.hint}</span>
                    </span>
                    {count > 0 ? (
                      <span className="ml-auto rounded-full bg-bad-soft px-1.5 font-mono text-[11px] font-medium text-bad">
                        {count}
                        <span className="sr-only"> errors</span>
                      </span>
                    ) : null}
                  </button>
                );
              })}
            </nav>

            <div className="min-w-0 rounded-lg border border-line bg-bg p-4 shadow-1 sm:p-6">
              {section === "basics" ? (
                <SectionFrame title="Basics" description="How this scenario is identified and found.">
                  <Field
                    id="sc-name"
                    label="Name"
                    error={err("name") ?? (draft.name && !NAME_PATTERN.test(draft.name) ? "Lowercase letters, digits, - and _ only, starting with a letter or digit." : null)}
                    hint="Machine-friendly and unique in its suite, e.g. hindi_appointment_booking."
                  >
                    <Input value={draft.name} maxLength={200} onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} className="font-mono" />
                  </Field>
                  <Field id="sc-description" label="Description" optional error={err("description")}>
                    <Textarea
                      rows={3}
                      maxLength={2000}
                      value={draft.description}
                      onChange={(e) => {
                        const value = e.target.value;
                        setDraft((d) => ({ ...d, description: value }));
                      }}
                    />
                  </Field>
                  {!draft.name && draft.description ? (
                    <button
                      type="button"
                      className="-mt-2 text-left text-[12px] font-medium text-accent hover:underline"
                      onClick={() => setDraft((d) => ({ ...d, name: slugify(d.description.split(/[.!?]/)[0]) }))}
                    >
                      Suggest a name from the description
                    </button>
                  ) : null}
                  <Field id="sc-language" label="Language" error={err("language")} hint="The caller speaks this. It is part of the test's definition; a run cannot change it.">
                    <Select
                      value={draft.language}
                      onChange={(e) => {
                        const code = e.target.value;
                        setDraft((d) => ({
                          ...d,
                          language: code,
                          persona: { ...d.persona, accent: "" },
                          code_mixing: { ...d.code_mixing, secondary: d.code_mixing.secondary.filter((s) => s !== code) },
                        }));
                      }}
                    >
                      {languages.map((l) => (
                        <option key={l.code} value={l.code}>
                          {l.name} · {l.endonym} ({l.code})
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <ListEditor
                    id="sc-tags"
                    label="Tags"
                    hint="Lowercase labels for filtering, e.g. healthcare, smoke."
                    items={draft.tags}
                    error={err("tags")}
                    placeholder="healthcare"
                    onChange={(tags) => setDraft((d) => ({ ...d, tags }))}
                  />
                </SectionFrame>
              ) : null}

              {section === "caller" ? (
                <SectionFrame
                  title="Caller"
                  description="Who the simulated caller is. The rule-engine caller speaks the identity and the objective in its opening line, so write both as the caller would say them, in the scenario's language."
                >
                  <Field id="sc-identity" label="Identity" error={err("persona.identity")} hint="e.g. a farmer near Thanjavur, a working professional.">
                    <Input value={draft.persona.identity} maxLength={500} lang={draft.language} onChange={(e) => setDraft((d) => ({ ...d, persona: { ...d.persona, identity: e.target.value } }))} />
                  </Field>
                  <Field id="sc-style" label="Speaking style" error={err("persona.speaking_style")}>
                    <Select value={draft.persona.speaking_style} onChange={(e) => setDraft((d) => ({ ...d, persona: { ...d.persona, speaking_style: e.target.value } }))}>
                      {SPEAKING_STYLES.map((s) => (
                        <option key={s} value={s}>
                          {s[0].toUpperCase() + s.slice(1)}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <ListEditor
                    id="sc-traits"
                    label="Traits"
                    hint="Up to ten, e.g. impatient, repeats the policy number."
                    items={draft.persona.traits}
                    max={10}
                    error={err("persona.traits")}
                    placeholder="impatient"
                    onChange={(traits) => setDraft((d) => ({ ...d, persona: { ...d.persona, traits } }))}
                  />
                </SectionFrame>
              ) : null}

              {section === "goal" ? (
                <SectionFrame title="Goal and outcomes" description="What the caller wants, what it may say when asked, and what the bot must achieve.">
                  <Field id="sc-objective" label="Objective" error={err("goal.objective")} hint="One or two sentences, in the caller's words.">
                    <Textarea rows={3} maxLength={2000} lang={draft.language} value={draft.goal.objective} onChange={(e) => setDraft((d) => ({ ...d, goal: { ...d.goal, objective: e.target.value } }))} />
                  </Field>
                  <Field id="sc-max-turns" label="Turn limit" error={err("goal.max_turns")} hint="1 to 100. A run may lower it, never raise it.">
                    <Input type="number" min={1} max={100} inputMode="numeric" value={draft.goal.max_turns} onChange={(e) => setDraft((d) => ({ ...d, goal: { ...d.goal, max_turns: e.target.value } }))} className="w-32" />
                  </Field>
                  <ListEditor
                    id="sc-outcomes"
                    label="Expected outcomes"
                    hint="At least one. The evaluator checks these as keywords heard in the bot's turns - an indicator, not a judgement."
                    items={draft.expected_outcomes}
                    min={1}
                    max={20}
                    error={err("expected_outcomes")}
                    placeholder="Confirm the appointment time"
                    onChange={(expected_outcomes) => setDraft((d) => ({ ...d, expected_outcomes }))}
                  />
                  <FactsEditor
                    facts={draft.known_facts}
                    error={err("known_facts")}
                    onChange={(known_facts) => setDraft((d) => ({ ...d, known_facts }))}
                  />
                </SectionFrame>
              ) : null}

              {section === "language" ? (
                <SectionFrame title="Language and accent" description="How the caller sounds, and whether it mixes languages.">
                  <Field
                    id="sc-accent"
                    label="Accent profile"
                    optional
                    error={err("persona.accent")}
                    hint="Requested, not guaranteed: each run records whether the speech provider applied it. No provider documents an accented voice yet, so runs record it as not applied."
                  >
                    <Select value={draft.persona.accent} onChange={(e) => setDraft((d) => ({ ...d, persona: { ...d.persona, accent: e.target.value } }))}>
                      <option value="">No accent requested</option>
                      {(language?.accents ?? []).map((a) => (
                        <option key={a.key} value={a.key}>
                          {a.name}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  {language && language.accents.length === 0 ? (
                    <p className="-mt-2 text-[12px] text-text-3">The catalogue lists no accent profiles for {language.name}.</p>
                  ) : null}

                  <div className="rounded-md border border-line p-4">
                    <label className="flex cursor-pointer items-start gap-2.5">
                      <input
                        type="checkbox"
                        className="mt-0.5 size-4"
                        checked={draft.code_mixing.enabled}
                        onChange={(e) => setDraft((d) => ({ ...d, code_mixing: { ...d.code_mixing, enabled: e.target.checked } }))}
                      />
                      <span>
                        <span className="block text-[14px] font-medium text-text">Declare code-mixing</span>
                        <span className="mt-0.5 block text-[12px] leading-relaxed text-text-3">
                          Records which languages a real caller would mix in and when. Runs measure script switching in every turn; the
                          rule-engine caller itself still speaks one language.
                        </span>
                      </span>
                    </label>
                    {draft.code_mixing.enabled ? (
                      <div className="mt-4 space-y-4 border-t border-line pt-4">
                        <fieldset>
                          <legend className="text-[13px] font-medium text-text">Mixed-in languages</legend>
                          <p className="mt-0.5 text-[12px] text-text-3">One to three, most prominent first.</p>
                          <div className="mt-2 flex flex-wrap gap-1.5">
                            {languages
                              .filter((l) => l.code !== draft.language)
                              .map((l) => (
                                <Toggle
                                  key={l.code}
                                  pressed={draft.code_mixing.secondary.includes(l.code)}
                                  onClick={() =>
                                    setDraft((d) => {
                                      const has = d.code_mixing.secondary.includes(l.code);
                                      const secondary = has ? d.code_mixing.secondary.filter((c) => c !== l.code) : [...d.code_mixing.secondary, l.code];
                                      return { ...d, code_mixing: { ...d.code_mixing, secondary } };
                                    })
                                  }
                                >
                                  {l.name}
                                </Toggle>
                              ))}
                          </div>
                          {err("code_mixing.secondary") ? <p className="mt-1.5 text-[12px] font-medium text-bad">{err("code_mixing.secondary")}</p> : null}
                        </fieldset>
                        <fieldset>
                          <legend className="text-[13px] font-medium text-text">What prompts a switch</legend>
                          <div className="mt-2 flex flex-wrap gap-1.5">
                            {SWITCH_TRIGGERS.map(([value, label]) => (
                              <Toggle
                                key={value}
                                pressed={draft.code_mixing.switch_triggers.includes(value)}
                                onClick={() =>
                                  setDraft((d) => {
                                    const has = d.code_mixing.switch_triggers.includes(value);
                                    return {
                                      ...d,
                                      code_mixing: {
                                        ...d.code_mixing,
                                        switch_triggers: has ? d.code_mixing.switch_triggers.filter((t) => t !== value) : [...d.code_mixing.switch_triggers, value],
                                      },
                                    };
                                  })
                                }
                              >
                                {label}
                              </Toggle>
                            ))}
                          </div>
                        </fieldset>
                        <div className="grid gap-4 sm:grid-cols-2">
                          <Field id="sc-ratio" label="Share of mixed-in words" optional error={err("code_mixing.secondary_ratio")} hint="0 to 0.9, e.g. 0.35.">
                            <Input type="number" min={0} max={0.9} step={0.05} inputMode="decimal" value={draft.code_mixing.secondary_ratio} onChange={(e) => setDraft((d) => ({ ...d, code_mixing: { ...d.code_mixing, secondary_ratio: e.target.value } }))} />
                          </Field>
                          <label className="flex items-start gap-2.5 pt-7">
                            <input
                              type="checkbox"
                              className="mt-0.5 size-4"
                              checked={!draft.code_mixing.expected}
                              onChange={(e) => setDraft((d) => ({ ...d, code_mixing: { ...d.code_mixing, expected: !e.target.checked } }))}
                            />
                            <span className="text-[13px] text-text-2">Assert the caller stays monolingual instead</span>
                          </label>
                        </div>
                        <ListEditor
                          id="sc-samples"
                          label="Example mixed utterances"
                          hint="Illustrative for authors; not checked."
                          items={draft.code_mixing.sample_utterances}
                          max={10}
                          placeholder="Mujhe kal ka appointment chahiye at 10 AM"
                          onChange={(sample_utterances) => setDraft((d) => ({ ...d, code_mixing: { ...d.code_mixing, sample_utterances } }))}
                        />
                      </div>
                    ) : null}
                  </div>
                </SectionFrame>
              ) : null}

              {section === "audio" ? (
                <SectionFrame
                  title="Audio conditions"
                  description="Simulated conditions, applied to the caller's audio from a fixed seed. Noise is scaled from each utterance's own level so the stated ratio holds. Ignored, and reported as not enforced, in modes that move no audio."
                >
                  <div className="grid gap-4 sm:grid-cols-3">
                    <Field id="sc-noise" label="Environment" error={err("audio.noise_profile")}>
                      <Select value={draft.audio.noise_profile} onChange={(e) => setDraft((d) => ({ ...d, audio: { ...d.audio, noise_profile: e.target.value } }))}>
                        {SCENARIO_NOISE_PROFILES.map(([value, label]) => (
                          <option key={value} value={value}>
                            {label}
                          </option>
                        ))}
                      </Select>
                    </Field>
                    <Field id="sc-snr" label="Signal-to-noise (dB)" error={err("audio.snr_db")} hint="0 to 40. Higher is cleaner.">
                      <Input type="number" min={0} max={40} step={1} inputMode="decimal" value={draft.audio.snr_db} onChange={(e) => setDraft((d) => ({ ...d, audio: { ...d.audio, snr_db: e.target.value } }))} />
                    </Field>
                    <Field id="sc-loss" label="Packet loss (%)" error={err("audio.packet_loss_percent")} hint="0 to 30.">
                      <Input type="number" min={0} max={30} step={0.5} inputMode="decimal" value={draft.audio.packet_loss_percent} onChange={(e) => setDraft((d) => ({ ...d, audio: { ...d.audio, packet_loss_percent: e.target.value } }))} />
                    </Field>
                  </div>
                  <details className="group rounded-md border border-line" open={Boolean(draft.audio.codec || draft.audio.sample_rate_hz || Object.values(draft.audio.conditions).some(Boolean))}>
                    <summary className="flex cursor-pointer items-center justify-between px-4 py-3 text-[14px] font-medium text-text">
                      Line conditions
                      <span className="text-[12px] font-normal text-text-3">codec, jitter, dropouts, level, truncation</span>
                    </summary>
                    <div className="grid gap-4 border-t border-line p-4 sm:grid-cols-2">
                      <Field id="sc-codec" label="Codec" optional error={err("audio.codec")} hint="Round-tripped exactly; runs at 8 kHz.">
                        <Select value={draft.audio.codec} onChange={(e) => setDraft((d) => ({ ...d, audio: { ...d.audio, codec: e.target.value } }))}>
                          <option value="">None</option>
                          {CODECS.map(([value, label]) => (
                            <option key={value} value={value}>
                              {label}
                            </option>
                          ))}
                        </Select>
                      </Field>
                      <Field id="sc-rate" label="Sample rate" optional error={err("audio.sample_rate_hz")}>
                        <Select value={draft.audio.sample_rate_hz} onChange={(e) => setDraft((d) => ({ ...d, audio: { ...d.audio, sample_rate_hz: e.target.value } }))}>
                          <option value="">Provider default</option>
                          {SAMPLE_RATES_HZ.map((rate) => (
                            <option key={rate} value={String(rate)}>
                              {rate.toLocaleString("en-IN")} Hz
                            </option>
                          ))}
                        </Select>
                      </Field>
                      {NUMERIC_CONDITIONS.map((c) => (
                        <Field key={c.key} id={`sc-${c.key}`} label={`${c.label} (${c.unit})`} optional error={err(`audio.${c.key}`)} hint={c.hint}>
                          <Input
                            type="number"
                            min={c.min}
                            max={c.max}
                            step={c.integer ? 1 : "any"}
                            inputMode="decimal"
                            placeholder={`${c.min} to ${c.max}`}
                            value={draft.audio.conditions[c.key] ?? ""}
                            onChange={(e) => {
                              const value = e.target.value;
                              setDraft((d) => ({ ...d, audio: { ...d.audio, conditions: { ...d.audio.conditions, [c.key]: value } } }));
                            }}
                          />
                        </Field>
                      ))}
                    </div>
                  </details>
                </SectionFrame>
              ) : null}

              {section === "rules" ? (
                <SectionFrame title="Conversation rules" description="Optional limits on how the conversation may proceed.">
                  <label className="flex cursor-pointer items-start gap-2.5">
                    <input type="checkbox" className="mt-0.5 size-4" checked={draft.constraints.enabled} onChange={(e) => setDraft((d) => ({ ...d, constraints: { ...d.constraints, enabled: e.target.checked } }))} />
                    <span>
                      <span className="block text-[14px] font-medium text-text">Declare conversation rules</span>
                      <span className="mt-0.5 block text-[12px] text-text-3">Off leaves the server&rsquo;s defaults in place.</span>
                    </span>
                  </label>
                  {draft.constraints.enabled ? (
                    <div className="space-y-5 border-t border-line pt-5">
                      <Field id="sc-silence" label="Silence before the caller re-prompts (s)" error={err("constraints.max_silence_seconds")} hint="Above 0, up to 60.">
                        <Input type="number" min={0.5} max={60} step={0.5} inputMode="decimal" value={draft.constraints.max_silence_seconds} onChange={(e) => setDraft((d) => ({ ...d, constraints: { ...d.constraints, max_silence_seconds: e.target.value } }))} className="w-32" />
                      </Field>
                      <div className="rounded-md border border-line bg-bg-soft p-4">
                        <label className="flex cursor-pointer items-start gap-2.5">
                          <input type="checkbox" className="mt-0.5 size-4" checked={draft.constraints.allow_interruptions} onChange={(e) => setDraft((d) => ({ ...d, constraints: { ...d.constraints, allow_interruptions: e.target.checked } }))} />
                          <span>
                            <span className="block text-[14px] font-medium text-text">Caller may interrupt the bot</span>
                            <span className="mt-0.5 block text-[12px] leading-relaxed text-text-3">
                              Declared intent. A run reports it as not enforced. Actual interruption is set per run, in milliseconds, and only
                              the streaming voice adapter (ws_voice) can talk over a bot.
                            </span>
                          </span>
                        </label>
                      </div>
                      <ListEditor
                        id="sc-required"
                        label="Phrases the bot must say"
                        hint="Checked against the bot's turns after normalisation; a paraphrase does not count."
                        items={draft.constraints.required_phrases}
                        max={20}
                        error={err("constraints.required_phrases")}
                        placeholder="policy number"
                        onChange={(required_phrases) => setDraft((d) => ({ ...d, constraints: { ...d.constraints, required_phrases } }))}
                      />
                      <ListEditor
                        id="sc-forbidden"
                        label="Phrases the bot must never say"
                        items={draft.constraints.forbidden_phrases}
                        max={20}
                        error={err("constraints.forbidden_phrases")}
                        placeholder="I cannot help"
                        onChange={(forbidden_phrases) => setDraft((d) => ({ ...d, constraints: { ...d.constraints, forbidden_phrases } }))}
                      />
                    </div>
                  ) : null}
                </SectionFrame>
              ) : null}
            </div>
          </div>
        )}
      </div>

      <aside className="min-w-0 xl:sticky xl:top-6 xl:self-start">
        <div className="rounded-lg border border-line bg-bg shadow-1">
          <div className="border-b border-line px-4 py-3">
            <h2 className="text-[14px] font-semibold text-text">Validation</h2>
          </div>
          <div className="space-y-3 p-4">
            {validation === null ? (
              <p className="flex gap-2 text-[13px] text-text-3">
                <AlertCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                Not checked since the last change. Save checks it with the server first.
              </p>
            ) : validation.valid ? (
              <p role="status" className="flex gap-2 text-[13px] font-medium text-ok">
                <CheckCircle2 aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                Valid. The server accepts this scenario.
              </p>
            ) : (
              <div role="alert" className="space-y-2">
                <p className="flex gap-2 text-[13px] font-medium text-bad">
                  <AlertCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                  {validation.errors.length} problem{validation.errors.length === 1 ? "" : "s"} to fix
                </p>
                <ul className="space-y-1.5">
                  {validation.errors.map((e, i) => (
                    <li key={`${e.field}-${i}`}>
                      <button
                        type="button"
                        onClick={() => {
                          if (tab === "source") return;
                          setSection(sectionOf(e.field));
                        }}
                        className="text-left text-[12px] leading-relaxed text-text-2 hover:text-text"
                      >
                        <span className="font-mono text-bad">{e.field || "document"}</span> {e.message}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {error ? <Notice tone="bad">{error}</Notice> : null}
            <div className="grid gap-2 pt-1">
              <Button tone="primary" disabled={busy !== null || !ready} onClick={() => void save()}>
                {busy ? <Loader2 aria-hidden="true" className="size-4 animate-spin" /> : null}
                {busy === "saving" ? "Saving…" : busy === "validating" ? "Checking…" : mode === "edit" ? "Validate and save" : "Validate and create"}
              </Button>
              <Button tone="secondary" disabled={busy !== null} onClick={() => void validate()}>
                Check without saving
              </Button>
            </div>
          </div>
          <details className="border-t border-line">
            <summary className="cursor-pointer px-4 py-3 text-[13px] font-medium text-text">Preview YAML</summary>
            <pre className="max-h-80 overflow-auto border-t border-line bg-bg-soft p-4 font-mono text-[11.5px] leading-relaxed text-text-2">{yaml}</pre>
          </details>
        </div>
      </aside>
    </div>
  );
}

function SectionFrame({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="space-y-5">
      <header>
        <h2 className="text-[16px] font-semibold tracking-[-0.01em] text-text">{title}</h2>
        <p className="mt-1 text-[13px] leading-relaxed text-text-3">{description}</p>
      </header>
      {children}
    </section>
  );
}

function Toggle({ pressed, onClick, children }: { pressed: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={cx(
        "h-8 rounded-full border px-3 text-[12px] font-medium transition-colors",
        pressed ? "border-accent bg-accent-soft text-accent" : "border-line-strong bg-bg text-text-2 hover:border-text-3",
      )}
    >
      {children}
    </button>
  );
}

/** A list of short strings with add and remove. */
function ListEditor({
  id,
  label,
  hint,
  items,
  onChange,
  placeholder,
  error,
  min = 0,
  max = 20,
}: {
  id: string;
  label: string;
  hint?: string;
  items: string[];
  onChange: (items: string[]) => void;
  placeholder?: string;
  error?: string | null;
  min?: number;
  max?: number;
}) {
  return (
    <fieldset aria-describedby={hint ? `${id}-hint` : undefined}>
      <legend className="text-[13px] font-medium text-text">{label}</legend>
      {hint ? (
        <p id={`${id}-hint`} className="mt-0.5 text-[12px] leading-relaxed text-text-3">
          {hint}
        </p>
      ) : null}
      <ul className="mt-2 space-y-2">
        {items.map((item, index) => (
          <li key={index} className="flex gap-2">
            <input
              aria-label={`${label} ${index + 1}`}
              value={item}
              maxLength={500}
              placeholder={placeholder}
              onChange={(e) => onChange(items.map((v, i) => (i === index ? e.target.value : v)))}
              className={cx(controlClass, "h-9")}
            />
            <button
              type="button"
              disabled={items.length <= min}
              onClick={() => onChange(items.filter((_, i) => i !== index))}
              className="flex size-9 shrink-0 items-center justify-center rounded-md text-text-3 hover:bg-bg-sunk hover:text-bad disabled:opacity-30"
            >
              <Trash2 aria-hidden="true" className="size-4" />
              <span className="sr-only">
                Remove {label.toLowerCase()} {index + 1}
              </span>
            </button>
          </li>
        ))}
      </ul>
      {items.length < max ? (
        <button type="button" onClick={() => onChange([...items, ""])} className="mt-2 inline-flex h-8 items-center gap-1.5 text-[13px] font-medium text-accent hover:underline">
          <Plus aria-hidden="true" className="size-3.5" />
          Add {label.toLowerCase().replace(/s$/, "")}
        </button>
      ) : null}
      {error ? <p className="mt-1.5 text-[12px] font-medium text-bad">{error}</p> : null}
    </fieldset>
  );
}

/** Facts the caller may give when asked, as key/value pairs. */
function FactsEditor({
  facts,
  onChange,
  error,
}: {
  facts: { key: string; value: string }[];
  onChange: (facts: { key: string; value: string }[]) => void;
  error?: string | null;
}) {
  return (
    <fieldset>
      <legend className="text-[13px] font-medium text-text">Known facts</legend>
      <p className="mt-0.5 text-[12px] leading-relaxed text-text-3">
        What the caller can give when the bot asks. Values are kept as written, so a leading zero survives.
      </p>
      <ul className="mt-2 space-y-2">
        {facts.map((fact, index) => (
          <li key={index} className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)_auto] gap-2">
            <input
              aria-label={`Fact ${index + 1} name`}
              value={fact.key}
              placeholder="policy_number"
              maxLength={100}
              onChange={(e) => onChange(facts.map((f, i) => (i === index ? { ...f, key: e.target.value } : f)))}
              className={cx(controlClass, "h-9 font-mono text-[13px]")}
            />
            <input
              aria-label={`Fact ${index + 1} value`}
              value={fact.value}
              placeholder="PMFBY2026114827"
              maxLength={500}
              onChange={(e) => onChange(facts.map((f, i) => (i === index ? { ...f, value: e.target.value } : f)))}
              className={cx(controlClass, "h-9")}
            />
            <button
              type="button"
              onClick={() => onChange(facts.filter((_, i) => i !== index))}
              className="flex size-9 items-center justify-center rounded-md text-text-3 hover:bg-bg-sunk hover:text-bad"
            >
              <Trash2 aria-hidden="true" className="size-4" />
              <span className="sr-only">Remove fact {index + 1}</span>
            </button>
          </li>
        ))}
      </ul>
      {facts.length < 50 ? (
        <button type="button" onClick={() => onChange([...facts, { key: "", value: "" }])} className="mt-2 inline-flex h-8 items-center gap-1.5 text-[13px] font-medium text-accent hover:underline">
          <Plus aria-hidden="true" className="size-3.5" />
          Add fact
        </button>
      ) : null}
      {error ? <p className="mt-1.5 text-[12px] font-medium text-bad">{error}</p> : null}
    </fieldset>
  );
}
