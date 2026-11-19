import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { ScenarioManager } from "@/components/domain/scenario-manager";
import { PageBody, PageHeader } from "@/components/shell/page-header";
import { DetailSkeleton } from "@/components/ui/loading";
import { ErrorState, Fact, Panel, PanelHeader } from "@/components/ui/primitives";
import { Badge } from "@/components/ui/status";
import { ApiError, api } from "@/lib/api/client";
import { allows, roleForSuite } from "@/lib/api/roles";
import { sessionHeaders, signInAgainIfExpired } from "@/lib/api/server";
import type { ScenarioDetail } from "@/lib/api/types";
import { formatTimestampShort } from "@/lib/format";

export const metadata = { title: "Scenario" };

export default function ScenarioPage({ params }: { params: Promise<{ scenarioId: string }> }) {
  return (
    <Suspense
      fallback={
        <>
          <PageHeader title="Scenario" />
          <PageBody>
            <DetailSkeleton />
          </PageBody>
        </>
      }
    >
      <ScenarioDetailView params={params} />
    </Suspense>
  );
}

async function ScenarioDetailView({ params }: { params: Promise<{ scenarioId: string }> }) {
  const auth = await sessionHeaders();
  const { scenarioId } = await params;

  let scenario: ScenarioDetail;
  try {
    scenario = await api.scenario(scenarioId, { cache: "no-store", headers: auth });
  } catch (error) {
    signInAgainIfExpired(error);
    if (error instanceof ApiError && error.status === 404) notFound();
    return (
      <>
        <PageHeader title="Scenario" />
        <PageBody>
          <Panel>
            <ErrorState
              title="This scenario could not be loaded"
              detail={error instanceof ApiError ? error.message : "The request failed."}
            />
          </Panel>
        </PageBody>
      </>
    );
  }

  const role = await roleForSuite(scenario.suite_id, auth);
  const archived = scenario.archived_at !== null;

  return (
    <>
      <PageHeader
        title={scenario.name}
        description={scenario.description ?? undefined}
        breadcrumb={
          <Link href="/app/scenarios" className="text-text-muted hover:text-text">
            ← Scenarios
          </Link>
        }
        actions={archived ? <Badge tone="warn">Archived</Badge> : null}
      />
      <PageBody>
        <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <Panel>
            <PanelHeader title="Manage" />
            <div className="p-4 sm:p-5">
              <ScenarioManager
                scenarioId={scenario.id}
                suiteId={scenario.suite_id}
                name={scenario.name}
                spec={scenario.spec}
                archived={archived}
                canEdit={allows(role, "edit")}
                canDelete={allows(role, "delete")}
              />
            </div>
          </Panel>
          <Panel>
            <PanelHeader title="Details" />
            <dl className="grid gap-3 p-4 sm:p-5">
              <Fact label="Language" mono>
                {scenario.language}
              </Fact>
              <Fact label="Your role" mono>
                {role ?? "unknown"}
              </Fact>
              <Fact label="Updated" mono>
                {formatTimestampShort(scenario.updated_at) ?? "—"}
              </Fact>
              <Fact label="Archived" mono>
                {archived ? (formatTimestampShort(scenario.archived_at) ?? "yes") : "no"}
              </Fact>
              <Fact label="Id" mono>
                {scenario.id}
              </Fact>
            </dl>
            <div className="border-t border-line p-4 sm:p-5">
              <Link
                href={`/app/runs?scenario=${encodeURIComponent(scenario.name)}`}
                className="text-[13px] text-accent hover:underline"
              >
                Runs of this scenario
              </Link>
            </div>
          </Panel>
        </div>
      </PageBody>
    </>
  );
}
