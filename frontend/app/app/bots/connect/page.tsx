import { Suspense } from "react";

import { ConnectWizard, type ProjectChoice } from "@/components/bots/connect-wizard";
import { PageBody, PageHeader } from "@/components/shell/page";
import { DetailSkeleton, ErrorState, Panel } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api/client";
import { can, loadContext } from "@/lib/api/context";
import { signInAgainIfExpired } from "@/lib/api/server";

export const metadata = { title: "Connect your chatbot" };

type SearchParams = Record<string, string | string[] | undefined>;

export default function ConnectBotPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  return (
    <>
      <PageHeader
        crumbs={[{ href: "/app/bots", label: "Bots" }, { label: "Connect" }]}
        title="Connect your chatbot"
        description="Bring a chatbot you already run. BhashaBench calls it the way a caller would, and records what happened."
      />
      <PageBody>
        <Suspense fallback={<DetailSkeleton />}>
          <Wizard searchParams={searchParams} />
        </Suspense>
      </PageBody>
    </>
  );
}

async function Wizard({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  let projects: ProjectChoice[];
  let languages: { code: string; label: string }[];
  try {
    const context = await loadContext();
    const catalogue = await api.languages({ cache: "no-store", headers: context.auth });
    projects = context.projects.filter((p) => can(p.role, "edit")).map((p) => ({ id: p.id, label: `${p.workspace_name} / ${p.name}` }));
    languages = catalogue.languages.map((l) => ({ code: l.code, label: `${l.name} (${l.endonym}) · ${l.code}` }));
  } catch (error) {
    signInAgainIfExpired(error);
    return (
      <Panel>
        <ErrorState title="The connection form could not be loaded" detail={error instanceof ApiError ? error.message : "The API did not answer."} />
      </Panel>
    );
  }
  return <ConnectWizard projects={projects} languages={languages} initialProjectId={typeof params.project === "string" ? params.project : undefined} />;
}
