import { Suspense } from "react";

import { PageBody, PageHeader } from "@/components/shell/page-header";
import { PanelSkeleton } from "@/components/ui/loading";
import {
  ErrorState,
  Fact,
  Panel,
  PanelHeader,
  cx,
} from "@/components/ui/primitives";
import { AvailabilityBadge, Badge, SelectedBadge } from "@/components/ui/status";
import { ApiError, api } from "@/lib/api/client";
import type {
  BotAdapters,
  CallerProviders,
  LanguageCatalogue,
  SpeechProviders,
  TranscriptionProviders,
} from "@/lib/api/types";

export const metadata = { title: "Providers" };

/**
 * Every integration, what it can do, and what it cannot.
 *
 * The limitations are the point of this page. `notes[]` on each provider is
 * the vendor-documentation record the backend keeps - gaps, contradictions
 * and capabilities that are described by name but never given a wire value.
 * Rendered verbatim, because a summary of a caveat is not a caveat.
 */
export default function ProvidersPage() {
  return (
    <>
      <PageHeader
        title="Providers"
        description="What each integration can do, measured against the thirteen catalogue languages — and, in the notes, exactly where each vendor's documentation runs out."
      />
      <PageBody>
        <Suspense fallback={<PanelSkeleton title="Providers" rows={6} />}>
          <ProviderPanels />
        </Suspense>
      </PageBody>
    </>
  );
}

async function ProviderPanels() {
  let stt: TranscriptionProviders | null = null;
  let tts: SpeechProviders | null = null;
  let caller: CallerProviders | null = null;
  let adapters: BotAdapters | null = null;
  let languages: LanguageCatalogue | null = null;
  let failure: string | null = null;

  try {
    [stt, tts, caller, adapters, languages] = await Promise.all([
      api.transcriptionProviders({ cache: "no-store" }),
      api.speechProviders({ cache: "no-store" }),
      api.callerProviders({ cache: "no-store" }),
      api.botAdapters({ cache: "no-store" }),
      api.languages({ revalidate: 3600 }),
    ]);
  } catch (error) {
    failure =
      error instanceof ApiError ? error.message : "Provider status is unavailable.";
  }

  if (failure !== null) {
    return (
      <Panel>
        <ErrorState title="Provider status could not be read" detail={failure} />
      </Panel>
    );
  }

  return (
    <>
        {/* Not implemented, first. A reader scanning this page for what
            works should meet what does not before the capability tables. */}
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-5 md:grid-cols-2">
          <Panel className="border-bad/30">
            <PanelHeader
              title="Gnani Evon"
              actions={<Badge tone="bad">Not implemented</Badge>}
            />
            <p className="px-4 py-3 text-[13px] leading-relaxed text-text-dim">
              {caller?.evon_status}
            </p>
            <p className="border-t border-line px-4 py-3 text-[12px] leading-relaxed text-text-muted">
              The caller engine below is a deterministic rule engine. It is not
              Evon, is not a language model, and is named for what it is.
            </p>
          </Panel>

          <Panel className="border-bad/30">
            <PanelHeader
              title="Telephony"
              actions={<Badge tone="bad">Not implemented</Badge>}
            />
            <p className="px-4 py-3 text-[13px] leading-relaxed text-text-dim">
              {adapters?.telephony_status}
            </p>
            <p className="border-t border-line px-4 py-3 text-[12px] leading-relaxed text-text-muted">
              No run has been placed over a phone line. Every result in this
              product comes from audio moved inside this process or handed to
              it by an operator.
            </p>
          </Panel>
        </div>

        {/* Speech to text */}
        {stt ? (
          <Panel>
            <PanelHeader
              title="Speech to text"
              description="Transcribes the bot's audio."
              actions={<SelectedBadge name={stt.selected} />}
            />
            <ul className="divide-y divide-line">
              {stt.providers.map((provider) => (
                <li key={provider.name} className="px-4 py-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[13px] font-semibold text-text">
                      {provider.display_name}
                    </span>
                    <span className="font-mono text-[12px] text-text-muted">
                      {provider.name}
                    </span>
                    <AvailabilityBadge
                      available={provider.available}
                      reason={provider.unavailable_reason}
                    />
                    {provider.selected ? <Badge tone="accent">Selected</Badge> : null}
                  </div>

                  <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
                    <Fact label="Languages" mono>
                      {provider.languages.length} of {languages?.total ?? "?"}
                    </Fact>
                    <Fact label="Output modes" mono>
                      {provider.modes.length}
                    </Fact>
                    <Fact label="Streaming" mono>
                      {provider.supports_streaming ? "yes" : "no"}
                    </Fact>
                    <Fact
                      label="Confidence"
                      mono
                      hint="Whether the provider reports a confidence score at all."
                    >
                      {provider.supports_confidence ? "yes" : "not reported"}
                    </Fact>
                  </dl>

                  <LanguageCoverage
                    supported={provider.languages}
                    unsupported={provider.unsupported_catalogue_languages}
                    catalogue={languages}
                  />
                  <Notes notes={provider.notes} />
                </li>
              ))}
            </ul>
          </Panel>
        ) : null}

        {/* Text to speech */}
        {tts ? (
          <Panel>
            <PanelHeader
              title="Text to speech"
              description="Synthesises the caller's speech."
              actions={<SelectedBadge name={tts.selected} />}
            />
            <ul className="divide-y divide-line">
              {tts.providers.map((provider) => (
                <li key={provider.name} className="px-4 py-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[13px] font-semibold text-text">
                      {provider.display_name}
                    </span>
                    <span className="font-mono text-[12px] text-text-muted">
                      {provider.name}
                    </span>
                    <AvailabilityBadge
                      available={provider.available}
                      reason={provider.unavailable_reason}
                    />
                    {provider.selected ? <Badge tone="accent">Selected</Badge> : null}
                  </div>

                  <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
                    <Fact label="Languages" mono>
                      {provider.languages.length} of {languages?.total ?? "?"}
                    </Fact>
                    <Fact label="Voices" mono>
                      {provider.voices.length}
                      {provider.voices_are_exhaustive ? "" : "+"}
                    </Fact>
                    <Fact label="Default model" mono>
                      {provider.default_model}
                    </Fact>
                    <Fact label="Streaming" mono>
                      {provider.supports_streaming ? "yes" : "no"}
                    </Fact>
                  </dl>

                  {provider.voices.length > 0 ? (
                    <div className="mt-3">
                      <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
                        Voices
                      </p>
                      <ul className="mt-1.5 flex flex-wrap gap-1.5">
                        {provider.voices.map((voice) => (
                          <li
                            key={voice.name}
                            className="rounded-md border border-line bg-surface-raised px-2 py-1"
                            title={voice.character ?? undefined}
                          >
                            <span className="font-mono text-[12px] text-text">
                              {voice.name}
                            </span>
                            {voice.gender ? (
                              <span className="ml-1.5 text-[11px] text-text-muted">
                                {voice.gender}
                              </span>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}

                  <LanguageCoverage
                    supported={provider.languages}
                    unsupported={provider.unsupported_catalogue_languages}
                    catalogue={languages}
                  />
                  <Notes notes={provider.notes} />
                </li>
              ))}
            </ul>
          </Panel>
        ) : null}

        {/* Caller engine */}
        {caller ? (
          <Panel>
            <PanelHeader
              title="Caller engine"
              description="Decides what the simulated caller says next."
              actions={<SelectedBadge name={caller.selected} />}
            />
            <ul className="divide-y divide-line">
              {caller.providers.map((provider) => (
                <li key={provider.name} className="px-4 py-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[13px] font-semibold text-text">
                      {provider.display_name}
                    </span>
                    <AvailabilityBadge
                      available={provider.available}
                      reason={provider.unavailable_reason}
                    />
                    <Badge
                      tone={provider.uses_language_model ? "accent" : "idle"}
                      title="Whether a learned model generated the caller's words."
                    >
                      {provider.uses_language_model ? "Language model" : "Rule engine"}
                    </Badge>
                    {provider.is_deterministic ? (
                      <Badge tone="ok" title="The same context always yields the same turn.">
                        Deterministic
                      </Badge>
                    ) : null}
                  </div>

                  <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
                    <Fact
                      label="Reviewed languages"
                      mono
                      hint="Languages with reviewed phrase tables."
                    >
                      {provider.languages.join(", ") || "—"}
                    </Fact>
                    <Fact label="Code-mixing" mono>
                      {provider.supports_code_mixing ? "yes" : "no"}
                    </Fact>
                    <Fact label="Credentials" mono>
                      {provider.requires_credentials ? "required" : "none"}
                    </Fact>
                    <Fact label="Turn ceiling" mono>
                      {provider.max_turns_supported ?? "unbounded"}
                    </Fact>
                  </dl>

                  <Notes notes={provider.notes} />
                </li>
              ))}
            </ul>
          </Panel>
        ) : null}

        {/* Bot adapters */}
        {adapters ? (
          <Panel>
            <PanelHeader
              title="Bot adapters"
              description="Where the bot's side of a conversation comes from."
              actions={<Badge tone="accent">Selected · {adapters.selected}</Badge>}
            />
            <ul className="divide-y divide-line">
              {adapters.adapters.map((adapter) => (
                <li key={adapter.name} className="px-4 py-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[13px] font-semibold text-text">
                      {adapter.display_name}
                    </span>
                    <span className="font-mono text-[12px] text-text-muted">
                      {adapter.name}
                    </span>
                    <Badge
                      tone={adapter.contacts_external_system ? "accent" : "idle"}
                      title={
                        adapter.contacts_external_system
                          ? "Using this adapter sends a request out of this process."
                          : "This adapter sends no request anywhere."
                      }
                    >
                      {adapter.contacts_external_system
                        ? "Contacts external system"
                        : "Sends nowhere"}
                    </Badge>
                    {adapter.selected ? <Badge tone="accent">Selected</Badge> : null}
                  </div>
                  <Notes notes={adapter.notes} />
                </li>
              ))}
            </ul>
          </Panel>
        ) : null}
    </>
  );
}

/**
 * Which catalogue languages a provider covers.
 *
 * The gap is the information. A scenario may be authored in Urdu, Odia or
 * Assamese and no Gnani provider can speak or transcribe them, so a run in
 * those languages is refused rather than quietly answered in a neighbouring
 * one.
 */
function LanguageCoverage({
  supported,
  unsupported,
  catalogue,
}: {
  supported: string[];
  unsupported: string[];
  catalogue: LanguageCatalogue | null;
}) {
  if (!catalogue) return null;
  const supportedSet = new Set(supported);

  return (
    <div className="mt-3">
      <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
        Catalogue coverage
      </p>
      <ul className="mt-1.5 flex flex-wrap gap-1.5">
        {catalogue.languages.map((entry) => {
          const covered = supportedSet.has(entry.code);
          return (
            <li
              key={entry.code}
              title={
                covered
                  ? `${entry.name} is supported.`
                  : `${entry.name} is in the catalogue and this provider cannot handle it.`
              }
              className={cx(
                "flex items-center gap-1.5 rounded-md border px-2 py-1",
                covered
                  ? "border-ok/25 bg-ok-dim"
                  : "border-line bg-surface-inset",
              )}
            >
              <span
                aria-hidden="true"
                className={cx(
                  "inline-block size-1.5 rounded-full",
                  covered ? "bg-ok" : "bg-text-muted",
                )}
              />
              <span
                className={cx(
                  "font-mono text-[12px]",
                  covered ? "text-ok" : "text-text-muted line-through",
                )}
              >
                {entry.code}
              </span>
              <span className="sr-only">
                {covered ? "supported" : "not supported"}
              </span>
            </li>
          );
        })}
      </ul>
      {unsupported.length > 0 ? (
        <p className="mt-1.5 text-[12px] leading-relaxed text-text-dim">
          {unsupported.length} catalogue language
          {unsupported.length === 1 ? " is" : "s are"} authorable and not
          handled by this provider. A scenario in one of them is refused
          rather than substituted with a neighbouring language.
        </p>
      ) : null}
    </div>
  );
}

function Notes({ notes }: { notes: string[] }) {
  if (notes.length === 0) return null;
  return (
    <details className="group mt-3">
      <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 rounded-md text-[12px] font-medium text-text-dim hover:text-text">
        <svg
          viewBox="0 0 12 12"
          className="size-3 transition-transform group-open:rotate-90"
          aria-hidden="true"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M4.5 2.5 8 6l-3.5 3.5" />
        </svg>
        {notes.length} verified limitation{notes.length === 1 ? "" : "s"}
      </summary>
      <ul className="mt-2 space-y-1.5 border-l border-line pl-3">
        {notes.map((note) => (
          <li key={note} className="text-[12px] leading-relaxed text-text-dim">
            {note}
          </li>
        ))}
      </ul>
    </details>
  );
}
