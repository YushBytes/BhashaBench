import Link from "next/link";
import { Suspense } from "react";
import { ArrowRight, Bot, FolderKanban, ShieldCheck } from "lucide-react";

import { SettingsNav } from "@/components/settings/settings-nav";
import { CreateWorkspace } from "@/components/settings/team-controls";
import { PageBody, PageHeader } from "@/components/shell/page";
import { DetailSkeleton, ErrorState, Fact, Panel, PanelBody, PanelHeader } from "@/components/ui/primitives";
import { Badge, HealthBadge } from "@/components/ui/status";
import { ApiError, api } from "@/lib/api/client";
import { loadContext } from "@/lib/api/context";
import { signInAgainIfExpired } from "@/lib/api/server";
import { formatTimestamp } from "@/lib/format";

export const metadata = { title: "Settings" };

export default function SettingsPage() {
  return (
    <>
      <PageHeader title="Settings" description="The workspace you are working in, the people in it, and your own account." />
      <PageBody>
        <SettingsNav current="/app/settings" />
        <Suspense fallback={<DetailSkeleton />}>
          <Workspace />
        </Suspense>
      </PageBody>
    </>
  );
}

async function Workspace() {
  let context;
  let health;
  try {
    context = await loadContext();
    health = await api.health({ cache: "no-store" }).catch(() => null);
  } catch (error) {
    signInAgainIfExpired(error);
    return (
      <Panel>
        <ErrorState title="Settings could not be loaded" detail={error instanceof ApiError ? error.message : "The API did not answer."} />
      </Panel>
    );
  }
  const w = context.current;
  const projects = w ? context.projects.filter((p) => p.workspace_id === w.id) : [];

  return (
    <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
      <div className="min-w-0 space-y-6">
        {w ? (
          <Panel>
            <PanelHeader
              title={w.name}
              description="The current workspace. Switch workspaces from the menu at the bottom of the sidebar."
              actions={<Badge tone="idle">Your role: {w.role}</Badge>}
            />
            <PanelBody>
              <dl className="grid gap-5 sm:grid-cols-2">
                <Fact label="Slug" mono>
                  {w.slug}
                </Fact>
                <Fact label="Created">{formatTimestamp(w.created_at)}</Fact>
                <Fact label="Projects">{projects.length}</Fact>
                <Fact label="Workspace id" mono>
                  {w.id}
                </Fact>
              </dl>
              <p className="mt-5 text-[12px] text-text-3">The API has no endpoint to rename or delete a workspace, so neither is offered here.</p>
            </PanelBody>
          </Panel>
        ) : (
          <Panel>
            <PanelBody>
              <p className="text-[14px] text-text-2">You are not in any workspace yet. Create one below.</p>
            </PanelBody>
          </Panel>
        )}

        <Panel>
          <PanelHeader title="New workspace" />
          <PanelBody>
            <CreateWorkspace />
          </PanelBody>
        </Panel>
      </div>

      <div className="min-w-0 space-y-6">
        <Panel>
          <PanelHeader title="Related" />
          <ul className="divide-y divide-line">
            {[
              { href: "/app/projects", label: "Projects", body: "Create, rename and delete projects.", icon: FolderKanban },
              { href: "/app/settings/team", label: "Team and roles", body: "Members and what each role may do.", icon: ShieldCheck },
              { href: "/app/bots", label: "Adapters and providers", body: "Configured on the server by its operator.", icon: Bot },
            ].map((item) => (
              <li key={item.href}>
                <Link href={item.href} className="group flex items-center gap-3 px-4 py-3 transition-colors hover:bg-bg-soft sm:px-5">
                  <item.icon aria-hidden="true" className="size-4 text-text-3" />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[14px] font-medium text-text">{item.label}</span>
                    <span className="block text-[12px] text-text-3">{item.body}</span>
                  </span>
                  <ArrowRight aria-hidden="true" className="size-4 text-text-3 transition-transform group-hover:translate-x-0.5" />
                </Link>
              </li>
            ))}
          </ul>
        </Panel>
        {health ? (
          <Panel>
            <PanelHeader title="Service health" actions={<HealthBadge status={health.status} />} />
            <ul className="divide-y divide-line">
              {health.components.map((c) => (
                <li key={c.name} className="px-4 py-3 sm:px-5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-[12px] text-text">{c.name}</span>
                    <HealthBadge status={c.status} />
                  </div>
                  <p className="mt-1 text-[12px] leading-relaxed text-text-3">{c.detail}</p>
                </li>
              ))}
            </ul>
            <p className="border-t border-line px-4 py-2.5 font-mono text-[11px] text-text-3 sm:px-5">
              {health.service} {health.version} · API {health.api_version} · {health.environment}
            </p>
          </Panel>
        ) : null}
      </div>
    </div>
  );
}
