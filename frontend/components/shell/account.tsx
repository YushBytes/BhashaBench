import { AccountMenu } from "./account-menu";
import { loadContext } from "@/lib/api/context";

/** The account block's data. Inside Suspense: it reads the session. */
export async function Account() {
  // The page body reports a failure (or redirects to sign-in); the chrome
  // stays quiet rather than showing a second error.
  const context = await loadContext().catch(() => null);
  if (!context) return null;
  return (
    <AccountMenu
      user={context.me.user}
      workspaces={context.workspaces.map((w) => ({ id: w.id, name: w.name, role: w.role }))}
      currentId={context.current?.id ?? null}
    />
  );
}
