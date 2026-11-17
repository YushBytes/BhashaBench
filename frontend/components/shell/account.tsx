"use client";

/**
 * Who is signed in, and the way out.
 *
 * Reads `GET /auth/me` from the browser rather than receiving it from the
 * layout, so the shell stays a static frame. Until it answers, the slot shows
 * nothing rather than a placeholder name: a name that is not the user's is a
 * small lie in the one place they look to confirm whose workspace this is.
 */

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api/client";
import type { Me } from "@/lib/api/types";

export function Account() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    api
      .me({ cache: "no-store", signal: controller.signal })
      .then(setMe)
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 401) {
          router.replace("/login?expired=1");
        }
      });
    return () => controller.abort();
  }, [router]);

  async function signOut() {
    setLeaving(true);
    try {
      await api.logout();
    } finally {
      // Whether or not the server answered, this browser is done with the
      // session; the sign-in page is the honest next screen.
      router.replace("/login");
      router.refresh();
    }
  }

  if (me === null) return <div className="h-[52px]" aria-hidden="true" />;
  const workspace = me.workspaces[0];

  return (
    <div className="flex items-center gap-2 rounded-md px-2.5 py-2">
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px] font-medium text-text" title={me.user.email}>
          {me.user.display_name}
        </p>
        <p className="truncate text-[11px] text-text-dim">
          {workspace
            ? `${workspace.workspace_name} · ${workspace.role}`
            : "No workspace"}
          {me.workspaces.length > 1 ? ` +${me.workspaces.length - 1}` : ""}
        </p>
      </div>
      <button
        type="button"
        onClick={signOut}
        disabled={leaving}
        className="min-h-9 shrink-0 rounded-md px-2 text-[12px] text-text-muted transition-colors hover:bg-surface-raised hover:text-text disabled:opacity-60"
      >
        {leaving ? "Signing out…" : "Sign out"}
      </button>
    </div>
  );
}
