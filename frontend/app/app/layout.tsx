import { Suspense } from "react";

import { Account } from "@/components/shell/account";
import { Shell } from "@/components/shell/sidebar";
import { Skeleton } from "@/components/ui/primitives";

export const metadata = { title: { default: "Workspace", template: "%s · BhashaBench" } };

/**
 * The workspace. `proxy.ts` sends a visit without a session cookie to sign
 * in; the API decides on every request, and a page that receives a 401
 * redirects through `signInAgainIfExpired`.
 */
export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  return (
    <Shell
      account={
        <Suspense fallback={<Skeleton className="h-[88px] w-full" />}>
          <Account />
        </Suspense>
      }
    >
      {children}
    </Shell>
  );
}
