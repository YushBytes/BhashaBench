import { notFound } from "next/navigation";
import { Suspense } from "react";
import { ArrowRight } from "lucide-react";

import { CheckResult } from "@/components/bots/check-result";
import { CheckButton, EditDetails, RemoveIntegration, ReplaceToken } from "@/components/bots/integration-actions";
import { PageBody, PageHeader } from "@/components/shell/page";
import { ButtonLink, DetailSkeleton, ErrorState, Notice, Panel, PanelBody, PanelHeader } from "@/components/ui/primitives";
import { Badge, IntegrationStatusBadge, MODE_COPY } from "@/components/ui/status";
import { ApiError, api } from "@/lib/api/client";
import { can, loadContext, projectOf } from "@/lib/api/context";
import { signInAgainIfExpired } from "@/lib/api/server";
import type { BotIntegration } from "@/lib/api/types";
import { formatTimestamp } from "@/lib/format";
import { PROTOCOLS } from "@/lib/integration";

export const metadata = { title: "Connected bot" };

const CRUMBS = [{ href: "/app/bots", label: "Bots" }];

export default function IntegrationPage({ params }: { params: Promise<{ integrationId: string }> }) {
  return (
    <Suspense
      fallback={
        <>
          <PageHeader title="Connected bot" crumbs={CRUMBS} />
          <PageBody>
            <DetailSkeleton />
          </PageBody>
        </>
      }
    >
      <Detail params={params} />
    </Suspense>
  );
}

async function Detail({ params }: { params: Promise<{ integrationId: string }> }) {
  const { integrationId } = await params;
  let integration: BotIntegration;
  let role;
  let projectLabel = "Project";
  try {
    const context = await loadContext();
    integration = await api.integration(integrationId, { cache: "no-store", headers: context.auth });
    const project = projectOf(context, integration.project_id);
    role = project?.role;
    if (project) projectLabel = `${project.workspace_name} / ${project.name}`;
  } catch (error) {
    signInAgainIfExpired(error);
    if (error instanceof ApiError && error.status === 404) notFound();
    return (
      <>
        <PageHeader title="Connected bot" crumbs={CRUMBS} />
        <PageBody>
          <Panel>
            <ErrorState title="This bot could not be loaded" detail={error instanceof ApiError ? error.message : "The API did not answer."} />
          </Panel>
        </PageBody>
      </>
    );
  }

  const edit = can(role, "edit");
  const manage = can(role, "manage");
  const copy = PROTOCOLS[integration.protocol];
  const declared = integration.declared;

  return (
    <>
      <PageHeader
        crumbs={[...CRUMBS, { label: integration.name }]}
        title={integration.name}
        description={copy.summary}
        meta={
          <div className="flex flex-wrap gap-1.5">
            <IntegrationStatusBadge status={integration.check_status} />
            <Badge tone="idle">{integration.protocol === "http" ? "Text bot" : "Voice bot"}</Badge>
            <Badge tone="ink">Contacts an external bot</Badge>
          </div>
        }
        actions={
          <>
            {edit ? <CheckButton integration={integration} /> : null}
            {integration.check_status === "connected" ? (
              <ButtonLink href={`/app/runs/new?bot=${integration.id}`} tone="secondary">
                Test this bot
                <ArrowRight aria-hidden="true" className="size-4" />
              </ButtonLink>
            ) : null}
          </>
        }
      />
      <PageBody>
        <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="min-w-0 space-y-6">
            {integration.check_status !== "connected" ? (
              <Notice tone={integration.check_status === "failed" ? "bad" : "warn"}>
                {integration.check_status === "failed"
                  ? "The last connection check failed, so no test run can use this bot until a check succeeds."
                  : "Not verified: saving contacts nothing, and a change of URL or token makes the last check irrelevant. Check the connection before testing."}
              </Notice>
            ) : null}
            <Panel>
              <PanelHeader title="Last connection check" description="Through the same adapter, outbound rules and address pinning a run uses." />
              <PanelBody>
                <CheckResult integration={integration} />
              </PanelBody>
            </Panel>
            <Panel>
              <PanelHeader
                title="Declared by the adapter"
                description="What this protocol can do. A declaration is not a measurement: the check above and each run say what actually happened."
              />
              <PanelBody>
                <dl className="grid gap-3 text-[13px] sm:grid-cols-2">
                  <Item label="Tested as">{MODE_COPY[declared.execution_mode]?.label ?? declared.execution_mode}</Item>
                  <Item label="Audio in">{declared.accepts_containers.length ? declared.accepts_containers.join(", ") : "None: text only"}</Item>
                  <Item label="Sessions">{declared.supports_sessions ? "Yes" : "No"}</Item>
                  <Item label="Caller barge-in">{declared.supports_caller_barge_in ? "Supported by the stream; measured per run" : "Not possible over this protocol"}</Item>
                </dl>
                <ul className="mt-4 space-y-1 border-t border-line pt-3">
                  {declared.notes.map((note) => (
                    <li key={note} className="text-[12px] leading-relaxed text-text-2">
                      {note}
                    </li>
                  ))}
                </ul>
              </PanelBody>
            </Panel>
          </div>
          <aside className="min-w-0 space-y-4">
            <Panel>
              <PanelHeader title="Configuration" level={3} />
              <PanelBody>
                <dl className="space-y-3 text-[13px]">
                  <Item label="Project">{projectLabel}</Item>
                  <Item label={copy.urlLabel}>
                    <span className="break-all font-mono text-[12px]">{integration.url}</span>
                  </Item>
                  <Item label="Token">
                    <span className="font-mono text-[12px]">{integration.credential_hint}</span>
                    <span className="block text-[12px] text-text-3">Encrypted at rest; never shown in full.</span>
                  </Item>
                  <Item label="Check language">
                    <span className="font-mono text-[12px]">{integration.default_language}</span>
                  </Item>
                  <Item label="Saved">{formatTimestamp(integration.created_at)}</Item>
                </dl>
              </PanelBody>
              {edit ? (
                <div className="flex flex-wrap gap-2 border-t border-line px-4 py-3 sm:px-5">
                  <EditDetails integration={integration} />
                  <ReplaceToken integration={integration} />
                  {manage ? <RemoveIntegration integration={integration} /> : null}
                </div>
              ) : (
                <p className="border-t border-line px-4 py-3 text-[12px] text-text-3 sm:px-5">Your role can view this bot but not change or check it.</p>
              )}
            </Panel>
          </aside>
        </div>
      </PageBody>
    </>
  );
}

function Item({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[12px] text-text-3">{label}</dt>
      <dd className="mt-0.5 text-text">{children}</dd>
    </div>
  );
}
