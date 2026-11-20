import { notFound } from "next/navigation";
import { Suspense } from "react";

import { ScenarioBuilder } from "@/components/scenario/scenario-builder";
import { PageBody, PageHeader } from "@/components/shell/page";
import { DetailSkeleton, ErrorState, Notice, Panel } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api/client";
import { can, loadContext } from "@/lib/api/context";
import { signInAgainIfExpired } from "@/lib/api/server";
import type { LanguageCatalogue, Role, ScenarioDetail } from "@/lib/api/types";

export const metadata = { title: "Edit scenario" };

export default function EditScenarioPage({ params }: { params: Promise<{ scenarioId: string }> }) {
  return (
    <Suspense
      fallback={
        <>
          <PageHeader crumbs={[{ href: "/app/scenarios", label: "Scenarios" }]} title="Edit scenario" />
          <PageBody>
            <DetailSkeleton />
          </PageBody>
        </>
      }
    >
      <Editor params={params} />
    </Suspense>
  );
}

async function Editor({ params }: { params: Promise<{ scenarioId: string }> }) {
  const { scenarioId } = await params;
  let scenario: ScenarioDetail;
  let languages: LanguageCatalogue;
  let role: Role | undefined;
  try {
    const context = await loadContext();
    [scenario, languages] = await Promise.all([
      api.scenario(scenarioId, { cache: "no-store", headers: context.auth }),
      api.languages({ revalidate: 3600 }),
    ]);
    const suite = await api.suite(scenario.suite_id, { cache: "no-store", headers: context.auth });
    role = context.projects.find((p) => p.id === suite.project_id)?.role;
  } catch (error) {
    signInAgainIfExpired(error);
    if (error instanceof ApiError && error.status === 404) notFound();
    return (
      <>
        <PageHeader crumbs={[{ href: "/app/scenarios", label: "Scenarios" }]} title="Edit scenario" />
        <PageBody>
          <Panel>
            <ErrorState title="This scenario could not be loaded" detail={error instanceof ApiError ? error.message : "The API did not answer."} />
          </Panel>
        </PageBody>
      </>
    );
  }

  return (
    <>
      <PageHeader
        crumbs={[
          { href: "/app/scenarios", label: "Scenarios" },
          { href: `/app/scenarios/${scenario.id}`, label: scenario.name },
          { label: "Edit" },
        ]}
        title={`Edit ${scenario.name}`}
        description="Saving replaces the definition and keeps the same scenario id, so its recorded runs still point to it. The server does not keep comments from an uploaded file."
      />
      <PageBody>
        {!can(role, "edit") ? (
          <Notice tone="warn">Your role in this workspace is viewer, so this scenario cannot be edited by you.</Notice>
        ) : (
          <ScenarioBuilder mode="edit" scenarioId={scenario.id} suites={[]} languages={languages.languages} library={null} initialSpec={scenario.spec} />
        )}
      </PageBody>
    </>
  );
}
