import { Suspense } from "react";

import { NewRunForm, type ScenarioOption } from "@/components/runs/new-run-form";
import { PageBody, PageHeader } from "@/components/shell/page";
import { DetailSkeleton, ErrorState, Panel } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api/client";
import { loadContext } from "@/lib/api/context";
import { signInAgainIfExpired } from "@/lib/api/server";

export const metadata = { title: "New test run" };

type SearchParams = Record<string, string | string[] | undefined>;

export default function NewRunPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  return (
    <>
      <PageHeader
        crumbs={[{ href: "/app/runs", label: "Test runs" }, { label: "New" }]}
        title="New test run"
        description="Choose a scenario, decide how much of the system to exercise, set the line, then start. Every choice is recorded with the run."
      />
      <PageBody>
        <Suspense fallback={<DetailSkeleton />}>
          <Form searchParams={searchParams} />
        </Suspense>
      </PageBody>
    </>
  );
}

async function Form({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const initial = typeof params.scenario === "string" ? params.scenario : undefined;
  let options: ScenarioOption[];
  let adapters;
  try {
    const context = await loadContext();
    const [scenarios, suites, loadedAdapters] = await Promise.all([
      api.scenarios({ cache: "no-store", headers: context.auth, query: { limit: 100 } }),
      api.suites({ cache: "no-store", headers: context.auth }),
      api.botAdapters({ cache: "no-store", headers: context.auth }),
    ]);
    const projectName = new Map(context.projects.map((p) => [p.id, p.name]));
    const suiteLabel = new Map(suites.items.map((s) => [s.id, `${projectName.get(s.project_id) ?? "Project"} / ${s.name}`]));
    adapters = loadedAdapters;
    options = scenarios.items
      .filter((s) => s.archived_at === null)
      .map((s) => ({ ...s, suite_label: suiteLabel.get(s.suite_id) ?? "Suite" }));
  } catch (error) {
    signInAgainIfExpired(error);
    return (
      <Panel>
        <ErrorState title="The run form could not be loaded" detail={error instanceof ApiError ? error.message : "The API did not answer."} />
      </Panel>
    );
  }
  return <NewRunForm scenarios={options} adapters={adapters} initialScenarioId={initial} />;
}
