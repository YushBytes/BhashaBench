"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ChevronsUpDown, LogOut, UserRound } from "lucide-react";

import { failureMessage } from "@/components/ui/interactive";
import { cx } from "@/components/ui/primitives";
import { api } from "@/lib/api/client";
import type { Role } from "@/lib/api/types";

/**
 * The signed-in user, the workspace switcher and sign-out.
 *
 * The switcher sets a preference cookie and re-renders: it chooses which
 * workspace the settings and project pages open on. It is not an access
 * control - the API scopes every request by membership regardless.
 */
export function AccountMenu({
  user,
  workspaces,
  currentId,
}: {
  user: { display_name: string; email: string };
  workspaces: { id: string; name: string; role: Role }[];
  currentId: string | null;
}) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  function choose(id: string) {
    document.cookie = `bb_workspace=${encodeURIComponent(id)}; path=/; max-age=31536000; samesite=lax`;
    router.refresh();
  }

  async function signOut() {
    setPending(true);
    setError(null);
    try {
      await api.logout();
      router.replace("/login?signed_out=1");
      router.refresh();
    } catch (cause) {
      setError(failureMessage(cause, "Signing out failed."));
      setPending(false);
    }
  }

  const current = workspaces.find((w) => w.id === currentId) ?? null;

  return (
    <div className="space-y-1.5">
      {workspaces.length > 0 ? (
        <label className="relative block">
          <span className="sr-only">Current workspace</span>
          <select
            value={currentId ?? ""}
            onChange={(event) => choose(event.target.value)}
            className="h-10 w-full appearance-none truncate rounded-md border border-line bg-bg-soft pl-2.5 pr-8 text-left text-[13px] font-medium text-text hover:border-line-strong"
          >
            {workspaces.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name} · {w.role}
              </option>
            ))}
          </select>
          <ChevronsUpDown aria-hidden="true" className="pointer-events-none absolute right-2.5 top-3 size-4 text-text-3" />
        </label>
      ) : null}
      <div className="flex items-center gap-2 rounded-md px-1.5 py-1">
        <Link
          href="/app/settings/account"
          className="flex min-w-0 flex-1 items-center gap-2 rounded-md py-1 hover:text-accent"
        >
          <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-bg-sunk text-text-2">
            <UserRound aria-hidden="true" className="size-4" />
          </span>
          <span className="min-w-0">
            <span className="block truncate text-[13px] font-medium text-text">{user.display_name}</span>
            <span className="block truncate text-[12px] text-text-3">
              {current ? `${current.role} in ${current.name}` : user.email}
            </span>
          </span>
        </Link>
        <button
          type="button"
          onClick={() => void signOut()}
          disabled={pending}
          title="Sign out"
          className={cx(
            "flex size-9 shrink-0 items-center justify-center rounded-md text-text-3 hover:bg-bg-sunk hover:text-text",
            pending && "opacity-50",
          )}
        >
          <LogOut aria-hidden="true" className="size-4" />
          <span className="sr-only">Sign out</span>
        </button>
      </div>
      {error ? (
        <p role="alert" className="px-1.5 text-[12px] text-bad">
          {error}
        </p>
      ) : null}
    </div>
  );
}
