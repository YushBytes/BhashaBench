import { Suspense } from "react";

import { NewTestForm } from "@/components/domain/new-test-form";
import { PanelSkeleton } from "@/components/ui/loading";
import { PageBody, PageHeader } from "@/components/shell/page-header";
import { ErrorState, Panel } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api/client";
import type {
  BotAdapters,
  Page as PageEnvelope,
  ScenarioSummary,
} from "@/lib/api/types";

export const metadata = { title: "New test" };

/**
 * Everything the form offers comes from the server.
 *
 * The execution modes in particular: `IMPLEMENTED_MODES` excludes
 * `telephony_test`, and the form renders exactly what
 * `bot-adapters/available` returns rather than a list written here. A mode
 * that cannot run must not be selectable, and keeping the list in one place
 * is what guarantees that when telephony eventually exists — or does not.
 */
export default function NewTestPage() {
  return (
    <>
      <PageHeader
        title="New test"
        description="Pick a scenario, choose how much of the system to exercise, and launch. Every option here is what this server can actually do right now."
      />
      <PageBody>
        <Suspense fallback={<PanelSkeleton title="Configuration" rows={8} />}>
          <Form />
        </Suspense>
      </PageBody>
    </>
  );
}

async function Form() {
  let scenarios: PageEnvelope<ScenarioSummary> | null = null;
  let adapters: BotAdapters | null = null;
  let failure: string | null = null;

  try {
    [scenarios, adapters] = await Promise.all([
      api.scenarios({ cache: "no-store", query: { limit: 100 } }),
      api.botAdapters({ cache: "no-store" }),
    ]);
  } catch (error) {
    failure =
      error instanceof ApiError
        ? error.message
        : "The scenario library could not be loaded.";
  }

  if (failure !== null || scenarios === null || adapters === null) {
    return (
      <Panel>
        <ErrorState
          title="This form cannot be built"
          detail={
            <>
              {failure ?? "The API did not answer."} A configuration form
              offering options the server has not confirmed would be a guess,
              so none is shown.
            </>
          }
        />
      </Panel>
    );
  }

  return <NewTestForm scenarios={scenarios.items} adapters={adapters} />;
}
