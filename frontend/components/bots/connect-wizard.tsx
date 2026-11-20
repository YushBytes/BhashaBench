"use client";

/**
 * "Connect your chatbot": bring a bot you already run into BhashaBench.
 *
 * Three steps. First the person chooses how their bot is reached, and is
 * told what that path needs *before* any field asks for it. Then the form,
 * which applies the server's shape rules as they type. Then save and check:
 * the integration is saved (unverified), and a connection check through the
 * run's own adapter is run at once, so the person sees a real outcome rather
 * than a form that merely "submitted".
 *
 * Two paths are offered only as explanations, because nothing else would be
 * honest: a bot on another platform needs a thin service that speaks one of
 * the protocols (no vendor API is spoken directly, and no SDK is published),
 * and the demo is the offline simulation, labelled as such.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { ArrowLeft, ArrowRight, Bot, Eye, EyeOff, FlaskConical, Loader2, Puzzle, Radio, Workflow } from "lucide-react";

import { CheckResult } from "@/components/bots/check-result";
import { Field, Input, Select } from "@/components/ui/field";
import { failureMessage } from "@/components/ui/interactive";
import { Button, ButtonLink, Notice, Panel, cx, linkClass } from "@/components/ui/primitives";
import { Badge } from "@/components/ui/status";
import { api } from "@/lib/api/client";
import type { BotIntegration, IntegrationProtocol } from "@/lib/api/types";
import { PROTOCOLS, isPlainTransport, validateDraft, type DraftErrors } from "@/lib/integration";

export interface ProjectChoice {
  id: string;
  label: string;
}

type Path = IntegrationProtocol | "custom" | "demo";

const PATHS: { value: Path; title: string; blurb: string; icon: typeof Bot }[] = [
  { value: "http", title: PROTOCOLS.http.title, blurb: "Your bot already answers text over an HTTP API.", icon: Workflow },
  { value: "ws_voice", title: PROTOCOLS.ws_voice.title, blurb: "Your bot already holds a live voice conversation.", icon: Radio },
  { value: "custom", title: "A bot on another platform", blurb: "Its own REST or WebSocket format, a hosted bot builder, or a phone number.", icon: Puzzle },
  { value: "demo", title: "No bot yet: try the demo", blurb: "Run a scenario offline against scripted replies to learn the workflow.", icon: FlaskConical },
];

export function ConnectWizard({
  projects,
  languages,
  initialProjectId,
}: {
  projects: ProjectChoice[];
  languages: { code: string; label: string }[];
  initialProjectId?: string;
}) {
  const router = useRouter();
  const [path, setPath] = useState<Path | null>(null);
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [projectId, setProjectId] = useState(
    projects.some((p) => p.id === initialProjectId) ? (initialProjectId ?? "") : (projects[0]?.id ?? ""),
  );
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [language, setLanguage] = useState(languages.some((l) => l.code === "hi-IN") ? "hi-IN" : (languages[0]?.code ?? ""));
  const [touched, setTouched] = useState(false);
  const [phase, setPhase] = useState<"idle" | "saving" | "checking">("idle");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<BotIntegration | null>(null);

  const protocol: IntegrationProtocol | null = path === "http" || path === "ws_voice" ? path : null;
  const errors: DraftErrors = protocol ? validateDraft({ name, protocol, url, token }) : {};
  const shown = touched ? errors : {};
  const copy = protocol ? PROTOCOLS[protocol] : null;

  if (projects.length === 0) {
    return (
      <Notice tone="warn">
        Connecting a bot needs the member role or above in a project. Ask a workspace admin, or create a workspace of your own in Settings.
      </Notice>
    );
  }

  async function saveAndCheck() {
    if (!protocol) return;
    setTouched(true);
    if (Object.keys(errors).length > 0 || !projectId) return;
    setError(null);
    setPhase("saving");
    let created: BotIntegration;
    try {
      created = await api.createIntegration(projectId, { name: name.trim(), protocol, url: url.trim(), token, default_language: language });
    } catch (cause) {
      setError(failureMessage(cause, "The bot could not be saved."));
      setPhase("idle");
      return;
    }
    // The token has done its job in this browser; it is not kept.
    setToken("");
    setSaved(created);
    setStep(3);
    setPhase("checking");
    try {
      const result = await api.checkIntegration(created.id);
      setSaved(result.integration);
    } catch (cause) {
      setError(failureMessage(cause, "The bot was saved, but the connection check could not be run."));
    } finally {
      setPhase("idle");
      router.refresh();
    }
  }

  async function checkAgain() {
    if (!saved) return;
    setError(null);
    setPhase("checking");
    try {
      setSaved((await api.checkIntegration(saved.id)).integration);
    } catch (cause) {
      setError(failureMessage(cause, "The connection check could not be run."));
    } finally {
      setPhase("idle");
    }
  }

  return (
    <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="min-w-0 space-y-4">
        <Progress step={step} />

        {step === 1 ? (
          <Panel>
            <div className="border-b border-line px-4 py-3.5 sm:px-5">
              <h2 className="text-[15px] font-semibold text-text">How is your bot reached?</h2>
              <p className="mt-0.5 text-[13px] leading-relaxed text-text-3">
                You are connecting a chatbot you already run. BhashaBench calls it as a caller would; it does not build or host one.
              </p>
            </div>
            <fieldset className="grid gap-3 p-4 sm:grid-cols-2 sm:p-5">
              <legend className="sr-only">Connection method</legend>
              {PATHS.map((option) => {
                const Icon = option.icon;
                return (
                  <label
                    key={option.value}
                    className={cx(
                      "flex cursor-pointer gap-3 rounded-lg border p-4 transition-colors",
                      path === option.value ? "border-accent bg-accent-soft/50" : "border-line hover:border-line-strong",
                    )}
                  >
                    <input type="radio" name="path" className="sr-only" checked={path === option.value} onChange={() => setPath(option.value)} />
                    <span className="flex size-9 shrink-0 items-center justify-center rounded-md border border-line bg-bg-soft">
                      <Icon aria-hidden="true" className="size-4 text-text" strokeWidth={1.75} />
                    </span>
                    <span className="min-w-0">
                      <span className="block text-[14px] font-medium text-text">{option.title}</span>
                      <span className="mt-0.5 block text-[12px] leading-relaxed text-text-3">{option.blurb}</span>
                    </span>
                  </label>
                );
              })}
            </fieldset>
            {path ? <PathDetail path={path} /> : null}
            <div className="flex justify-end border-t border-line px-4 py-3 sm:px-5">
              {path === "demo" ? (
                <ButtonLink href="/app/runs/new" tone="primary">
                  Open the demo run
                  <ArrowRight aria-hidden="true" className="size-4" />
                </ButtonLink>
              ) : (
                <Button tone="primary" disabled={!protocol} onClick={() => setStep(2)}>
                  Continue
                  <ArrowRight aria-hidden="true" className="size-4" />
                </Button>
              )}
            </div>
          </Panel>
        ) : null}

        {step === 2 && protocol && copy ? (
          <Panel>
            <div className="border-b border-line px-4 py-3.5 sm:px-5">
              <h2 className="text-[15px] font-semibold text-text">{copy.title}</h2>
              <p className="mt-0.5 text-[13px] leading-relaxed text-text-3">
                Saving contacts nothing. The connection is checked right after, through the same code a test run uses.
              </p>
            </div>
            <form
              noValidate
              className="grid gap-4 p-4 sm:grid-cols-2 sm:p-5"
              onSubmit={(event) => {
                event.preventDefault();
                void saveAndCheck();
              }}
            >
              <Field id="bot-project" label="Project" hint="A run can use this bot only from suites in the same project.">
                <Select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field id="bot-name" label="Name" error={shown.name} hint="Unique within the project, e.g. Support bot (staging).">
                <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={120} autoComplete="off" />
              </Field>
              <Field
                id="bot-url"
                label={copy.urlLabel}
                error={shown.url}
                className="sm:col-span-2"
                hint={
                  isPlainTransport(url)
                    ? "Plain http:// or ws:// is accepted only for a bot on the server's own machine during development. A deployed BhashaBench refuses it."
                    : "Public addresses only: local, private-network and cloud-metadata addresses are refused when the connection is checked."
                }
              >
                <Input
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder={copy.urlPlaceholder}
                  inputMode="url"
                  autoComplete="off"
                  spellCheck={false}
                  className="font-mono text-[13px]"
                />
              </Field>
              <div className="min-w-0">
                <Field
                  id="bot-token"
                  label="Bearer token"
                  error={shown.token}
                  hint="Sent as Authorization: Bearer <token>. Encrypted before it is stored, and never shown again: afterwards only its last four characters appear."
                >
                  <Input
                    type={showToken ? "text" : "password"}
                    value={token}
                    onChange={(e) => setToken(e.target.value)}
                    autoComplete="new-password"
                    spellCheck={false}
                    className="font-mono text-[13px]"
                  />
                </Field>
                <button
                  type="button"
                  aria-pressed={showToken}
                  onClick={() => setShowToken((value) => !value)}
                  className="mt-1.5 inline-flex items-center gap-1.5 text-[12px] text-text-3 hover:text-text"
                >
                  {showToken ? <EyeOff aria-hidden="true" className="size-3.5" /> : <Eye aria-hidden="true" className="size-3.5" />}
                  {showToken ? "Hide token" : "Show token"}
                </button>
              </div>
              <Field id="bot-language" label="Language for the check" hint="The connection check opens its session in this language.">
                <Select value={language} onChange={(e) => setLanguage(e.target.value)}>
                  {languages.map((l) => (
                    <option key={l.code} value={l.code}>
                      {l.label}
                    </option>
                  ))}
                </Select>
              </Field>
              {error ? (
                <p role="alert" className="rounded-md border border-bad/25 bg-bad-soft px-3 py-2.5 text-[13px] text-bad sm:col-span-2">
                  {error}
                </p>
              ) : null}
              <div className="flex flex-wrap justify-between gap-2 border-t border-line pt-4 sm:col-span-2">
                <Button tone="ghost" onClick={() => setStep(1)} disabled={phase !== "idle"}>
                  <ArrowLeft aria-hidden="true" className="size-4" />
                  Back
                </Button>
                <Button type="submit" tone="primary" disabled={phase !== "idle"} aria-busy={phase !== "idle"}>
                  {phase !== "idle" ? <Loader2 aria-hidden="true" className="size-4 animate-spin" /> : null}
                  {phase === "saving" ? "Saving…" : "Save and check connection"}
                </Button>
              </div>
            </form>
          </Panel>
        ) : null}

        {step === 3 && saved ? (
          <Panel>
            <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-4 py-3.5 sm:px-5">
              <div className="min-w-0">
                <h2 className="text-[15px] font-semibold text-text">{saved.name}</h2>
                <p className="mt-0.5 truncate font-mono text-[12px] text-text-3">{saved.url}</p>
              </div>
              <Badge tone="idle">Configuration saved</Badge>
            </div>
            <div className="p-4 sm:p-5">
              {phase === "checking" ? (
                <p role="status" className="flex items-center gap-2 text-[13px] text-text-2">
                  <Loader2 aria-hidden="true" className="size-4 animate-spin" />
                  Checking the connection through the run&rsquo;s own adapter…
                </p>
              ) : (
                <CheckResult integration={saved} />
              )}
              {error ? (
                <p role="alert" className="mt-3 rounded-md border border-bad/25 bg-bad-soft px-3 py-2.5 text-[13px] text-bad">
                  {error}
                </p>
              ) : null}
            </div>
            <div className="flex flex-wrap justify-end gap-2 border-t border-line px-4 py-3 sm:px-5">
              <ButtonLink href={`/app/bots/${saved.id}`} tone="ghost">
                Open bot
              </ButtonLink>
              {saved.check_status === "connected" ? (
                <ButtonLink href={`/app/runs/new?bot=${saved.id}`} tone="primary">
                  Test this bot
                  <ArrowRight aria-hidden="true" className="size-4" />
                </ButtonLink>
              ) : (
                <Button tone="primary" onClick={() => void checkAgain()} disabled={phase !== "idle"}>
                  Check again
                </Button>
              )}
            </div>
          </Panel>
        ) : null}
      </div>

      <aside className="min-w-0 space-y-4 lg:sticky lg:top-6 lg:self-start">
        <Panel className="p-4">
          <h2 className="text-[14px] font-semibold text-text">{copy ? "What you will need" : "Before you start"}</h2>
          {copy ? (
            <ul className="mt-2 list-disc space-y-1.5 pl-4 text-[13px] leading-relaxed text-text-2">
              {copy.needs.map((need) => (
                <li key={need}>{need}</li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-[13px] leading-relaxed text-text-2">
              Your bot must speak one of BhashaBench&rsquo;s two published protocols. Each is a few endpoints; the reference bot in the repository implements both.
            </p>
          )}
          <p className="mt-3 text-[12px] leading-relaxed text-text-3">
            Full contract: <span className="font-mono">docs/BOT_PROTOCOL.md</span>. Step-by-step guide: <span className="font-mono">docs/CONNECT_YOUR_BOT.md</span>.
          </p>
        </Panel>
        {copy ? (
          <Panel className="p-4">
            <h2 className="text-[14px] font-semibold text-text">What a test will measure</h2>
            <p className="mt-2 text-[13px] leading-relaxed text-text-2">{copy.tests}</p>
          </Panel>
        ) : null}
      </aside>
    </div>
  );
}

function Progress({ step }: { step: 1 | 2 | 3 }) {
  const labels = ["Choose method", "Enter details", "Check connection"];
  return (
    <ol className="flex flex-wrap gap-2" aria-label="Progress">
      {labels.map((label, index) => {
        const n = index + 1;
        const state = n < step ? "done" : n === step ? "current" : "todo";
        return (
          <li
            key={label}
            aria-current={state === "current" ? "step" : undefined}
            className={cx(
              "flex items-center gap-2 rounded-full border px-3 py-1 text-[12px]",
              state === "current" ? "border-text text-text" : state === "done" ? "border-line text-text-2" : "border-line text-text-3",
            )}
          >
            <span className="font-mono">{n}</span>
            {label}
          </li>
        );
      })}
    </ol>
  );
}

function PathDetail({ path }: { path: Path }) {
  const body: Record<Path, ReactNode> = {
    http: <p>{PROTOCOLS.http.summary} Its runs are text bot tests.</p>,
    ws_voice: <p>{PROTOCOLS.ws_voice.summary} Its runs are external voice-bot tests.</p>,
    custom: (
      <>
        <p>
          BhashaBench does not speak any vendor&rsquo;s API directly, and no SDK package is published. Put a thin service in front of your bot that speaks
          one of the two protocols; <span className="font-mono">backend/reference_bot/</span> is a working example of both. Then connect that service here.
        </p>
        <p className="mt-2">A phone number cannot be tested: no telephony provider is integrated.</p>
      </>
    ),
    demo: (
      <p>
        The demo is an <strong>offline simulation</strong>: the bot&rsquo;s side is a scripted reply file on the server, nothing leaves the server, and the run is
        labelled as an offline simulation everywhere. No figure from it describes a real bot. The local Docker stack ships the reply file; on
        another server the operator sets <span className="font-mono">PIPELINE_FIXTURE_BOT_TEXT_PATH</span>.{" "}
        <Link href="/app/scenarios" className={linkClass}>
          Pick a scenario
        </Link>{" "}
        first if you have none.
      </p>
    ),
  };
  return <div className="border-t border-line bg-bg-soft px-4 py-3 text-[13px] leading-relaxed text-text-2 sm:px-5">{body[path]}</div>;
}
