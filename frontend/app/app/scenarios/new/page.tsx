import { Suspense } from "react";

import { ScenarioBuilder } from "@/components/scenario/scenario-builder";
import { PageBody, PageHeader } from "@/components/shell/page";
import { DetailSkeleton, ErrorState, Panel } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api/client";
import { can, loadContext, projectOf } from "@/lib/api/context";
import { signInAgainIfExpired } from "@/lib/api/server";
import type { LanguageCatalogue, ScenarioLibrary } from "@/lib/api/types";

export const metadata = { title: "New scenario" };

type SearchParams = Record<string, string | string[] | undefined>;
const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) || undefined;

export default function NewScenarioPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  return (
    <>
      <PageHeader
        crumbs={[{ href: "/app/scenarios", label: "Scenarios" }, { label: "New" }]}
        title="Build a scenario"
        description="Work through the sections, or edit the YAML directly. Nothing is stored until the server has validated it."
      />
      <PageBody>
        <Suspense fallback={<DetailSkeleton />}>
          <Builder searchParams={searchParams} />
        </Suspense>
      </PageBody>
    </>
  );
}

async function Builder({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  let editable: { id: string; label: string }[];
  let languages: LanguageCatalogue;
  let library: ScenarioLibrary | null;
  try {
    const context = await loadContext();
    let suites;
    [suites, languages, library] = await Promise.all([
      api.suites({ cache: "no-store", headers: context.auth, query: { limit: 100 } }),
      api.languages({ revalidate: 3600 }),
      // The library is a convenience; the builder works without it.
      api.scenarioLibrary({ cache: "no-store", headers: context.auth }).catch(() => null),
    ]);
    editable = suites.items
      .map((s) => ({ suite: s, project: projectOf(context, s.project_id) }))
      .filter(({ project }) => can(project?.role, "edit"))
      .map(({ suite, project }) => ({ id: suite.id, label: `${project?.name ?? "Project"} / ${suite.name}` }));
  } catch (error) {
    signInAgainIfExpired(error);
    return (
      <Panel>
        <ErrorState title="The builder could not be loaded" detail={error instanceof ApiError ? error.message : "The API did not answer."} />
      </Panel>
    );
  }
  return (
    <ScenarioBuilder
      mode="create"
      suites={editable}
      initialSuiteId={one(params.suite)}
      initialTemplate={one(params.template)}
      languages={languages.languages}
      library={library?.scenarios ?? null}
    />
  );
}
