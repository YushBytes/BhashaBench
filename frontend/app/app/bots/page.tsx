import Link from "next/link";
import { Suspense } from "react";
import { Bot, Mic, PhoneOff, Plug, Plus, Radio, Speaker, Workflow } from "lucide-react";

import { PageBody, PageHeader } from "@/components/shell/page";
import { ButtonLink, ErrorState, Notice, Panel, PanelHeader, StatsSkeleton, TableSkeleton, cx, linkClass } from "@/components/ui/primitives";
import { AvailabilityBadge, Badge, IntegrationStatusBadge, SelectedBadge } from "@/components/ui/status";
import { ApiError, api } from "@/lib/api/client";
import { can, loadContext } from "@/lib/api/context";
import { signInAgainIfExpired } from "@/lib/api/server";
import type { BotAdapters, BotIntegration, CallerProviders, SpeechProviders, TranscriptionProviders } from "@/lib/api/types";
import { formatBytes, formatTimestampShort } from "@/lib/format";

export const metadata = { title: "Bots" };

export default function BotsPage() {
  return (
    <>
      <PageHeader
        title="Bots"
        description="The chatbots your workspace has connected, and what this deployment itself can talk to. A connected bot counts as connected only after a connection check succeeds."
        actions={
          <ButtonLink href="/app/bots/connect" tone="primary">
            <Plus aria-hidden="true" className="size-4" />
            Connect your chatbot
          </ButtonLink>
        }
      />
      <PageBody>
        <div className="space-y-8">
          <Suspense fallback={<TableSkeleton rows={3} />}>
            <ConnectedBots />
          </Suspense>
          <Suspense fallback={<StatsSkeleton count={4} />}>
            <Catalogue />
          </Suspense>
        </div>
      </PageBody>
    </>
  );
}

const ADAPTER_ICON: Record<string, typeof Bot> = { ws_voice: Radio, http: Workflow, manual: Mic, scripted: Bot };

async function ConnectedBots() {
  let groups: { id: string; label: string; editable: boolean; bots: BotIntegration[] }[];
  try {
    const context = await loadContext();
    const lists = await Promise.all(
      context.projects.map((p) => api.integrations(p.id, { cache: "no-store", headers: context.auth })),
    );
    groups = context.projects.map((p, i) => ({
      id: p.id,
      label: `${p.workspace_name} / ${p.name}`,
      editable: can(p.role, "edit"),
      bots: lists[i] ?? [],
    }));
  } catch (error) {
    signInAgainIfExpired(error);
    return (
      <Panel>
        <ErrorState title="Your connected bots could not be loaded" detail={error instanceof ApiError ? error.message : "The API did not answer."} />
      </Panel>
    );
  }
  const all = groups.flatMap((g) => g.bots.map((b) => ({ ...b, project: g.label })));
  return (
    <section aria-labelledby="connected-title" className="space-y-3">
      <div>
        <h2 id="connected-title" className="text-[16px] font-semibold tracking-[-0.01em] text-text">
          Your connected bots
        </h2>
        <p className="mt-0.5 text-[13px] text-text-3">Chatbots you run elsewhere, reached over a published protocol with a token stored encrypted.</p>
      </div>
      {all.length === 0 ? (
        <Panel className="flex flex-col items-start gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex gap-3">
            <Plug aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-text-3" strokeWidth={1.75} />
            <div>
              <p className="text-[14px] font-medium text-text">No bot connected yet</p>
              <p className="mt-0.5 max-w-prose text-[13px] leading-relaxed text-text-3">
                Connect a text chatbot over HTTP or a real-time voice bot over WebSocket, check the connection, then test it against any scenario.
              </p>
            </div>
          </div>
          {groups.some((g) => g.editable) ? (
            <ButtonLink href="/app/bots/connect" tone="secondary">
              Connect your chatbot
            </ButtonLink>
          ) : null}
        </Panel>
      ) : (
        <ul className="grid gap-3 lg:grid-cols-2">
          {all.map((bot) => (
            <li key={bot.id}>
              <Panel as="article" className="h-full p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <Link href={`/app/bots/${bot.id}`} className={cx(linkClass, "text-[15px]")}>
                    {bot.name}
                  </Link>
                  <IntegrationStatusBadge status={bot.check_status} />
                  <Badge tone="idle">{bot.protocol === "http" ? "Text bot" : "Voice bot"}</Badge>
                </div>
                <p className="mt-1.5 truncate font-mono text-[12px] text-text-3">{bot.url}</p>
                <p className="mt-1 text-[12px] text-text-3">
                  {bot.project}
                  {bot.last_checked_at ? ` · checked ${formatTimestampShort(bot.last_checked_at)}` : " · never checked"}
                </p>
              </Panel>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

async function Catalogue() {
  let adapters: BotAdapters, stt: TranscriptionProviders, tts: SpeechProviders, callers: CallerProviders;
  try {
    const { auth } = await loadContext();
    const o = { cache: "no-store" as const, headers: auth };
    [adapters, stt, tts, callers] = await Promise.all([api.botAdapters(o), api.transcriptionProviders(o), api.speechProviders(o), api.callerProviders(o)]);
  } catch (error) {
    signInAgainIfExpired(error);
    return (
      <Panel>
        <ErrorState title="The catalogue could not be loaded" detail={error instanceof ApiError ? error.message : "The API did not answer."} />
      </Panel>
    );
  }

  const fakeInUse = stt.selected === "fake" || tts.selected === "fake";

  return (
    <div className="space-y-6">
      {fakeInUse ? (
        <Notice tone="warn">
          This deployment uses the offline fake for {stt.selected === "fake" && tts.selected === "fake" ? "speech to text and text to speech" : stt.selected === "fake" ? "speech to text" : "text to speech"}.
          Its transcripts are scripted, so no accuracy figure from these runs describes a real speech engine.
        </Notice>
      ) : null}

      <section aria-labelledby="adapters-title" className="space-y-3">
        <div>
          <h2 id="adapters-title" className="text-[16px] font-semibold tracking-[-0.01em] text-text">
            Server adapters
          </h2>
          <p className="mt-0.5 text-[13px] text-text-3">
            Configured by this deployment&rsquo;s operator, not by a form here. A run records whether replies really came from outside.
          </p>
        </div>
        <ul className="grid gap-4 lg:grid-cols-2">
          {adapters.adapters.map((adapter) => {
            const Icon = ADAPTER_ICON[adapter.name] ?? Bot;
            return (
              <li key={adapter.name}>
                <Panel as="article" className="h-full">
                  <div className="flex items-start gap-3 border-b border-line px-4 py-4 sm:px-5">
                    <span className="flex size-10 shrink-0 items-center justify-center rounded-lg border border-line bg-bg-soft">
                      <Icon aria-hidden="true" className="size-5 text-text" strokeWidth={1.75} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-[15px] font-semibold text-text">{adapter.display_name}</h3>
                        <code className="font-mono text-[12px] text-text-3">{adapter.name}</code>
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        <AvailabilityBadge available={adapter.available} reason={adapter.unavailable_reason} />
                        <Badge tone={adapter.contacts_external_system ? "ink" : "idle"}>
                          {adapter.contacts_external_system ? "Contacts an external bot" : "In-process, sends nowhere"}
                        </Badge>
                        {adapter.name === adapters.selected ? <Badge tone="idle">Server default</Badge> : null}
                      </div>
                    </div>
                  </div>
                  <div className="space-y-3 px-4 py-4 sm:px-5">
                    {!adapter.available && adapter.unavailable_reason ? (
                      <p className="rounded-md border border-warn/25 bg-warn-soft px-3 py-2 text-[12px] text-warn">Not configured: {adapter.unavailable_reason}</p>
                    ) : null}
                    <dl className="grid grid-cols-2 gap-3 text-[13px] sm:grid-cols-4">
                      <Capability label="Sessions" value={adapter.supports_sessions} />
                      <Capability label="Caller barge-in" value={adapter.supports_caller_barge_in === true} />
                      <Capability label="Credentials" value={adapter.requires_credentials} yes="Required" no="None" />
                      <div>
                        <dt className="text-[12px] text-text-3">Audio in</dt>
                        <dd className="mt-0.5 font-mono text-[12px] text-text">{adapter.accepts_containers.join(", ") || "text only"}</dd>
                      </div>
                    </dl>
                    {adapter.notes.length > 0 ? (
                      <ul className="space-y-1 border-t border-line pt-3">
                        {adapter.notes.map((note) => (
                          <li key={note} className="text-[12px] leading-relaxed text-text-2">
                            {note}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                </Panel>
              </li>
            );
          })}
        </ul>
        <div className="flex gap-3 rounded-lg border border-line bg-bg px-4 py-3 shadow-1">
          <PhoneOff aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-text-3" />
          <div className="min-w-0 text-[13px]">
            <p className="font-medium text-text">Telephony</p>
            <p className="mt-0.5 text-text-2">{adapters.telephony_status}</p>
            <p className="mt-1 text-text-3">Modes a run can be created in: {adapters.execution_modes.join(", ")}.</p>
          </div>
        </div>
      </section>

      <section aria-labelledby="speech-title" className="space-y-3">
        <div>
          <h2 id="speech-title" className="text-[16px] font-semibold tracking-[-0.01em] text-text">
            Speech providers
          </h2>
          <p className="mt-0.5 text-[13px] text-text-3">Synthesis of the caller&rsquo;s turns and transcription of the bot&rsquo;s replies.</p>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <Panel>
            <PanelHeader title="Speech to text" icon={<Mic aria-hidden="true" className="size-4" />} />
            <ul className="divide-y divide-line">
              {stt.providers.map((p) => (
                <li key={p.name} className="space-y-2 px-4 py-4 sm:px-5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[14px] font-medium text-text">{p.display_name}</span>
                    {p.selected ? <SelectedBadge /> : null}
                    <AvailabilityBadge available={p.available} reason={p.unavailable_reason} />
                  </div>
                  <p className="text-[12px] text-text-3">
                    {p.languages.length} languages
                    {p.unsupported_catalogue_languages.length > 0 ? ` · not ${p.unsupported_catalogue_languages.join(", ")}` : ""}
                    {p.max_batch_bytes ? ` · up to ${formatBytes(p.max_batch_bytes)} a request` : ""}
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    <Pill on={p.supports_streaming}>Streaming</Pill>
                    <Pill on={p.supports_confidence}>Confidence</Pill>
                    <Pill on={p.supports_word_timestamps}>Word timings</Pill>
                    <Pill on={p.supports_partial_results}>Partial results</Pill>
                  </div>
                  {p.notes.slice(0, 2).map((note) => (
                    <p key={note} className="text-[12px] leading-relaxed text-text-2">
                      {note}
                    </p>
                  ))}
                </li>
              ))}
            </ul>
          </Panel>
          <Panel>
            <PanelHeader title="Text to speech" icon={<Speaker aria-hidden="true" className="size-4" />} />
            <ul className="divide-y divide-line">
              {tts.providers.map((p) => (
                <li key={p.name} className="space-y-2 px-4 py-4 sm:px-5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[14px] font-medium text-text">{p.display_name}</span>
                    {p.selected ? <SelectedBadge /> : null}
                    <AvailabilityBadge available={p.available} reason={p.unavailable_reason} />
                  </div>
                  <p className="text-[12px] text-text-3">
                    {p.languages.length} languages · {p.voices.length} voice{p.voices.length === 1 ? "" : "s"}
                    {p.voices_are_exhaustive ? "" : " listed (not exhaustive)"}
                    {p.sample_rates.length > 0 ? ` · ${p.sample_rates.join(", ")} Hz` : ""}
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    <Pill on={p.supports_streaming}>Streaming</Pill>
                    <Pill on={p.supports_audio_tags}>Audio tags</Pill>
                  </div>
                  {p.notes.slice(0, 2).map((note) => (
                    <p key={note} className="text-[12px] leading-relaxed text-text-2">
                      {note}
                    </p>
                  ))}
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </section>

      <section aria-labelledby="caller-title" className="space-y-3">
        <h2 id="caller-title" className="text-[16px] font-semibold tracking-[-0.01em] text-text">
          Caller
        </h2>
        <Panel>
          <ul className="divide-y divide-line">
            {callers.providers.map((p) => (
              <li key={p.name} className="flex flex-col gap-2 px-4 py-4 sm:flex-row sm:items-start sm:justify-between sm:px-5">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[14px] font-medium text-text">{p.display_name}</span>
                    {p.selected ? <SelectedBadge /> : null}
                    <Badge tone="idle">{p.uses_language_model ? "Language model" : "Rule engine"}</Badge>
                  </div>
                  {p.notes.slice(0, 2).map((note) => (
                    <p key={note} className="mt-1 text-[12px] leading-relaxed text-text-2">
                      {note}
                    </p>
                  ))}
                </div>
                <AvailabilityBadge available={p.available} reason={p.unavailable_reason} />
              </li>
            ))}
          </ul>
          <p className="border-t border-line bg-bg-soft px-4 py-3 text-[12px] leading-relaxed text-text-2 sm:px-5">{callers.evon_status}</p>
        </Panel>
      </section>
    </div>
  );
}

function Capability({ label, value, yes = "Yes", no = "No" }: { label: string; value: boolean; yes?: string; no?: string }) {
  return (
    <div>
      <dt className="text-[12px] text-text-3">{label}</dt>
      <dd className={cx("mt-0.5 text-[13px] font-medium", value ? "text-text" : "text-text-3")}>{value ? yes : no}</dd>
    </div>
  );
}

function Pill({ on, children }: { on: boolean; children: React.ReactNode }) {
  return (
    <span className={cx("rounded-full border px-2 py-0.5 text-[11px]", on ? "border-line-strong text-text" : "border-line text-text-3 line-through decoration-text-3/50")}>
      {children}
      <span className="sr-only">{on ? ": supported" : ": not supported"}</span>
    </span>
  );
}
