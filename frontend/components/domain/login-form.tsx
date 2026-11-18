"use client";

/**
 * Sign-in.
 *
 * Posts to `/api/v1/auth/login` on this origin with `session_type: "cookie"`,
 * so the API sets an HttpOnly cookie and returns no token: nothing on this
 * page can read the credential it just obtained, which is the point.
 *
 * Every failure from the API reads the same ("email or password is incorrect,
 * or the account is locked") by design; this form shows that message as it
 * is rather than guessing which case applied.
 */

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api/client";
import { safeNext } from "@/lib/redirect";

const field =
  "mt-1.5 block w-full rounded-md border border-line-strong bg-surface-raised px-3 py-2.5 " +
  "text-[15px] text-text outline-none transition-colors placeholder:text-text-dim " +
  "focus:border-accent focus-visible:ring-2 focus-visible:ring-accent/40";

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const expired = params.get("expired") === "1";
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setPending(true);
    setError(null);
    try {
      await api.login(String(data.get("email") ?? ""), String(data.get("password") ?? ""));
      router.replace(safeNext(params.get("next")));
      router.refresh();
    } catch (cause) {
      setError(
        cause instanceof ApiError ? cause.message : "Sign-in failed for an unknown reason.",
      );
      setPending(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      {expired && error === null ? (
        <p role="status" className="rounded-md border border-line bg-surface px-3 py-2.5 text-[13px] text-text-muted">
          Your session ended. Sign in again to continue.
        </p>
      ) : null}
      <label className="block text-[13px] font-medium text-text-muted">
        Email
        <input
          name="email"
          type="email"
          autoComplete="username"
          required
          className={field}
        />
      </label>
      <label className="block text-[13px] font-medium text-text-muted">
        Password
        <input
          name="password"
          type="password"
          autoComplete="current-password"
          required
          className={field}
        />
      </label>
      {error !== null ? (
        <p role="alert" className="rounded-md border border-bad/40 bg-bad-dim px-3 py-2.5 text-[13px] text-text">
          {error}
        </p>
      ) : null}
      <Button type="submit" tone="primary" className="w-full" disabled={pending}>
        {pending ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}
