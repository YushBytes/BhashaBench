import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { Pencil, PlayCircle } from "lucide-react";

import { RunsTable } from "@/components/domain/runs-table";
import { ScenarioActions } from "@/components/scenario/scenario-actions";
import { PageBody, PageHeader } from "@/components/shell/page";
import {
  ButtonLink,
  DetailSkeleton,
  EmptyState,
  ErrorState,
  Fact,
  Notice,
  Panel,
  PanelBody,
  PanelHeader,
} from "@/components/ui/primitives";
import { Badge } from "@/components/ui/status";
import { ApiError, api } from "@/lib/api/client";
import { can, loadContext, projectOf } from "@/lib/api/context";
import { signInAgainIfExpired } from "@/lib/api/server";
import { CODECS } from "@/lib/conditions";
import { formatTimestamp, langAttr } from "@/lib/format";
import { SCENARIO_NOISE_PROFILES, SWITCH_TRIGGERS, draftFromSpec } from "@/lib/scenario-draft";

export const metadata = { title: "Scenario" };

type SearchParams = Record<string, string | string[] | undefined>;

export default function ScenarioPage({ params, searchParams }: { params: Promise<{ scenarioId: string }>; searchParams: Promise<SearchParams> }) {
  return (
    <Suspense
      fallback={
        <>
          <PageHeader title="Scenario" crumbs={[{ href: "/app/scenarios", label: "Scenarios" }]} />
          <PageBody>
            <DetailSkeleton />
          </PageBody>
        </>
      }
    >
      <Scenario params={params} searchParams={searchParams} />
    </Suspense>
  );
}

const label = (pairs: readonly (readonly [string, string])[], value: string) => pairs.find(([v]) => v === value)?.[1] ?? value;

async function Scenario({ params, searchParams }: { params: Promise<{ scenarioId: string }>; searchParams: Promise<SearchParams> }) {
  const { scenarioId } = await params;
  const flags = await searchParams;
  let context, scenario, suite, languages, runs;
  try {
    context = await loadContext();
    scenario = await api.scenario(scenarioId, { cache: "no-store", headers: context.auth });
    [suite, languages, runs] = await Promise.all([
      api.suite(scenario.suite_id, { cache: "no-store", headers: context.auth }),
      api.languages({ revalidate: 3600 }),
      api.runs({ cache: "no-store", headers: context.auth, query: { suite_id: scenario.suite_id, scenario: scenario.name, limit: 8 } }),
    ]);
  } catch (error) {
    signInAgainIfExpired(error);
    if (error instanceof ApiError && error.status === 404) notFound();
    return (
      <>
        <PageHeader title="Scenario" crumbs={[{ href: "/app/scenarios", label: "Scenarios" }]} />
        <PageBody>
          <Panel>
            <ErrorState title="This scenario could not be loaded" detail={error instanceof ApiError ? error.message : "The API did not answer."} />
          </Panel>
        </PageBody>
      </>
    );
  }

  const project = projectOf(context, suite.project_id);
  const edit = can(project?.role, "edit");
  const archived = scenario.archived_at !== null;
  const d = draftFromSpec(scenario.spec);
  const language = languages.languages.find((l) => l.code === d.language);
  const accent = language?.accents.find((a) => a.key === d.persona.accent);
  const conditions = Object.entries(d.audio.conditions).filter(([, v]) => v);

  return (
    <>
      <PageHeader
        crumbs={[
          { href: "/app/scenarios", label: "Scenarios" },
          { href: `/app/suites/${suite.id}`, label: suite.name },
          { label: scenario.name },
        ]}
        title={<span className="font-mono text-[22px] sm:text-[24px]">{scenario.name}</span>}
        description={scenario.description ?? undefined}
        meta={
          <>
            <Badge tone="idle">
              <span lang={langAttr(d.language)}>{language ? `${language.name} · ${language.endonym}` : d.language}</span>
            </Badge>
            {archived ? <Badge tone="warn">Archived</Badge> : null}
            {d.tags.map((tag) => (
              <Badge key={tag} tone="idle">
                #{tag}
              </Badge>
            ))}
          </>
        }
        actions={
          <>
            {edit && !archived ? (
              <ButtonLink href={`/app/scenarios/${scenario.id}/edit`} tone="secondary">
                <Pencil aria-hidden="true" className="size-4" />
                Edit
              </ButtonLink>
            ) : null}
            {!archived ? (
              <ButtonLink href={`/app/runs/new?scenario=${scenario.id}`} tone="primary">
                <PlayCircle aria-hidden="true" className="size-4" />
                Run this scenario
              </ButtonLink>
            ) : null}
          </>
        }
      />
      <PageBody>
        {flags.created ? <Notice tone="ok">Scenario created. Run it, or keep refining it.</Notice> : null}
        {flags.saved ? <Notice tone="ok">Saved. Runs from now on use this definition; earlier runs keep theirs.</Notice> : null}

        <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <div className="min-w-0 space-y-6">
            <Panel>
              <PanelHeader title="Caller and goal" />
              <PanelBody className="space-y-5">
                <dl className="grid gap-5 sm:grid-cols-2">
                  <Fact label="Identity">
                    <span lang={langAttr(d.language)}>{d.persona.identity}</span>
                  </Fact>
                  <Fact label="Speaking style">{d.persona.speaking_style}</Fact>
                  <Fact label="Objective">
                    <span lang={langAttr(d.language)}>{d.goal.objective}</span>
                  </Fact>
                  <Fact label="Turn limit" mono>
                    {d.goal.max_turns}
                  </Fact>
                </dl>
                {d.persona.traits.length > 0 ? (
                  <div className="flex flex-wrap gap-1.5">
                    {d.persona.traits.map((trait) => (
                      <Badge key={trait} tone="idle">
                        {trait}
                      </Badge>
                    ))}
                  </div>
                ) : null}
              </PanelBody>
            </Panel>

            <Panel>
              <PanelHeader title="What the bot must achieve" description="Checked as keywords heard in the bot's turns: an indicator, not a judgement." />
              <ol className="divide-y divide-line">
                {d.expected_outcomes.filter(Boolean).map((outcome, index) => (
                  <li key={outcome} className="flex gap-3 px-4 py-3 text-[14px] text-text sm:px-5">
                    <span className="font-mono text-[12px] text-text-3">{index + 1}</span>
                    {outcome}
                  </li>
                ))}
              </ol>
              {d.known_facts.length > 0 ? (
                <div className="border-t border-line px-4 py-4 sm:px-5">
                  <p className="text-[12px] font-medium text-text-3">Facts the caller can give</p>
                  <dl className="mt-2 grid gap-x-6 gap-y-2 sm:grid-cols-2">
                    {d.known_facts.map((fact) => (
                      <div key={fact.key} className="flex min-w-0 justify-between gap-3 border-b border-dashed border-line pb-1.5">
                        <dt className="font-mono text-[12px] text-text-3">{fact.key}</dt>
                        <dd className="truncate text-[13px] text-text">{fact.value}</dd>
                      </div>
                    ))}
                  </dl>
                </div>
              ) : null}
            </Panel>

            <div className="grid min-w-0 gap-6 lg:grid-cols-2">
              <Panel>
                <PanelHeader title="Audio conditions" description="Requested for the caller's audio. Each run records what was applied." />
                <PanelBody>
                  <dl className="grid gap-4">
                    <Fact label="Environment">{label(SCENARIO_NOISE_PROFILES, d.audio.noise_profile)}</Fact>
                    <Fact label="Signal-to-noise, packet loss" mono>
                      {d.audio.snr_db} dB · {d.audio.packet_loss_percent}%
                    </Fact>
                    <Fact label="Codec">{d.audio.codec ? label(CODECS, d.audio.codec) : "None"}</Fact>
                    <Fact label="Line conditions" mono>
                      {conditions.length === 0 ? "None declared" : conditions.map(([k, v]) => `${k}=${v}`).join(" · ")}
                    </Fact>
                  </dl>
                </PanelBody>
              </Panel>
              <Panel>
                <PanelHeader title="Language" />
                <PanelBody>
                  <dl className="grid gap-4">
                    <Fact label="Accent" hint={d.persona.accent ? "Requested, not guaranteed. Each run records whether it was applied." : undefined}>
                      {accent ? accent.name : d.persona.accent || "None requested"}
                    </Fact>
                    <Fact label="Code-mixing">
                      {d.code_mixing.enabled
                        ? d.code_mixing.expected
                          ? `Mixes in ${d.code_mixing.secondary.join(", ")}${d.code_mixing.secondary_ratio ? ` · about ${Math.round(Number(d.code_mixing.secondary_ratio) * 100)}% of words` : ""}`
                          : "Asserted monolingual"
                        : "Not declared"}
                    </Fact>
                    {d.code_mixing.enabled && d.code_mixing.switch_triggers.length > 0 ? (
                      <Fact label="Switches on">{d.code_mixing.switch_triggers.map((t) => label(SWITCH_TRIGGERS, t)).join(", ")}</Fact>
                    ) : null}
                  </dl>
                </PanelBody>
              </Panel>
            </div>

            {d.constraints.enabled ? (
              <Panel>
                <PanelHeader title="Conversation rules" />
                <PanelBody>
                  <dl className="grid gap-4 sm:grid-cols-2">
                    <Fact label="Re-prompt after silence" mono>
                      {d.constraints.max_silence_seconds} s
                    </Fact>
                    <Fact label="Caller may interrupt" hint="Declared intent; actual interruption is set per run on ws_voice.">
                      {d.constraints.allow_interruptions ? "Yes" : "No"}
                    </Fact>
                    <Fact label="Bot must say">{d.constraints.required_phrases.join(", ") || "Nothing required"}</Fact>
                    <Fact label="Bot must never say">{d.constraints.forbidden_phrases.join(", ") || "Nothing forbidden"}</Fact>
                  </dl>
                </PanelBody>
              </Panel>
            ) : null}

            <Panel>
              <PanelHeader title="Runs of this scenario" description={`${runs.total} in this suite`} />
              {runs.items.length === 0 ? (
                <EmptyState title="Not run yet">Run it offline first to check the caller&rsquo;s logic, then against your bot.</EmptyState>
              ) : (
                <RunsTable runs={runs.items} compact />
              )}
            </Panel>
          </div>

          <div className="min-w-0 space-y-6">
            <Panel>
              <PanelHeader title="Manage" />
              <PanelBody>
                <ScenarioActions
                  scenarioId={scenario.id}
                  suiteId={scenario.suite_id}
                  name={scenario.name}
                  archived={archived}
                  canEdit={edit}
                  canDelete={can(project?.role, "manage")}
                />
              </PanelBody>
            </Panel>
            <Panel>
              <PanelHeader title="Details" />
              <PanelBody>
                <dl className="grid gap-4">
                  <Fact label="Suite">
                    <Link href={`/app/suites/${suite.id}`} className="text-accent hover:underline">
                      {suite.name}
                    </Link>
                  </Fact>
                  <Fact label="Project">{project?.name ?? "Not visible to you"}</Fact>
                  <Fact label="Specification version" mono>
                    v{scenario.spec_version}
                  </Fact>
                  <Fact label="Created">{formatTimestamp(scenario.created_at)}</Fact>
                  <Fact label="Updated">{formatTimestamp(scenario.updated_at)}</Fact>
                  {archived ? <Fact label="Archived">{formatTimestamp(scenario.archived_at)}</Fact> : null}
                  <Fact label="Scenario id" mono>
                    {scenario.id}
                  </Fact>
                </dl>
              </PanelBody>
            </Panel>
          </div>
        </div>
      </PageBody>
    </>
  );
}
