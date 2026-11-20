import { Suspense } from "react";

import { PasswordForm } from "@/components/settings/password-form";
import { SettingsNav } from "@/components/settings/settings-nav";
import { PageBody, PageHeader } from "@/components/shell/page";
import { DetailSkeleton, ErrorState, Fact, Panel, PanelBody, PanelHeader } from "@/components/ui/primitives";
import { Badge } from "@/components/ui/status";
import { ApiError } from "@/lib/api/client";
import { loadContext } from "@/lib/api/context";
import { signInAgainIfExpired } from "@/lib/api/server";
import { formatTimestamp } from "@/lib/format";

export const metadata = { title: "Account and security" };

export default function AccountPage() {
  return (
    <>
      <PageHeader title="Settings" description="The workspace you are working in, the people in it, and your own account." />
      <PageBody>
        <SettingsNav current="/app/settings/account" />
        <Suspense fallback={<DetailSkeleton />}>
          <Account />
        </Suspense>
      </PageBody>
    </>
  );
}

async function Account() {
  let context;
  try {
    context = await loadContext();
  } catch (error) {
    signInAgainIfExpired(error);
    return (
      <Panel>
        <ErrorState title="Your account could not be loaded" detail={error instanceof ApiError ? error.message : "The API did not answer."} />
      </Panel>
    );
  }
  const { me } = context;
  return (
    <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <Panel>
        <PanelHeader title="Profile" description="The API has no endpoint to change your name or email, so they are shown read-only." />
        <PanelBody>
          <dl className="grid gap-5">
            <Fact label="Name">{me.user.display_name}</Fact>
            <Fact label="Email" mono>
              {me.user.email}
            </Fact>
            <Fact label="This session expires">{formatTimestamp(me.session_expires_at) ?? "Not reported"}</Fact>
            <Fact label="Workspaces">
              <span className="flex flex-wrap gap-1.5">
                {me.workspaces.map((w) => (
                  <Badge key={w.workspace_id} tone="idle">
                    {w.workspace_name} · {w.role}
                  </Badge>
                ))}
              </span>
            </Fact>
          </dl>
        </PanelBody>
      </Panel>
      <Panel>
        <PanelHeader
          title="Password"
          description="Changing it signs out every other session. Your session cookie is HttpOnly: no script on this site can read it."
        />
        <PanelBody>
          <PasswordForm email={me.user.email} />
        </PanelBody>
      </Panel>
    </div>
  );
}
