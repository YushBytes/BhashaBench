"use client";

/**
 * Self-service sign-up, shown only when the deployment enables it
 * (`AUTH_ALLOW_SIGNUP`, on in the local Docker stack). Creates the account
 * and its own workspace with a Default project, then signs in with the same
 * credentials - the cookie session is set by the API, never by this page.
 * The password rules are the server's (12+ characters, not the email); its
 * refusal is shown as worded.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api/client";

const field =
  "mt-1.5 block w-full rounded-md border border-line-strong bg-surface-raised px-3 py-2.5 " +
  "text-[15px] text-text outline-none transition-colors focus:border-accent";

export function SignupForm() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const email = String(data.get("email") ?? "");
    const password = String(data.get("password") ?? "");
    setPending(true);
    setError(null);
    try {
      await api.signup({
        email,
        password,
        display_name: String(data.get("display_name") ?? ""),
        workspace_name: String(data.get("workspace_name") ?? ""),
      });
      await api.login(email, password);
      router.replace("/app");
      router.refresh();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Sign-up failed.");
      setPending(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      <label className="block text-[13px] font-medium text-text-muted">
        Your name
        <input name="display_name" required maxLength={200} autoComplete="name" className={field} />
      </label>
      <label className="block text-[13px] font-medium text-text-muted">
        Email
        <input name="email" type="email" required autoComplete="username" className={field} />
      </label>
      <label className="block text-[13px] font-medium text-text-muted">
        Password (12 characters or more)
        <input name="password" type="password" required minLength={12} autoComplete="new-password" className={field} />
      </label>
      <label className="block text-[13px] font-medium text-text-muted">
        Workspace name
        <input name="workspace_name" required maxLength={200} placeholder="My team" className={field} />
      </label>
      {error !== null ? (
        <p role="alert" className="rounded-md border border-bad/40 bg-bad-dim px-3 py-2.5 text-[13px] text-text">
          {error}
        </p>
      ) : null}
      <Button type="submit" tone="primary" className="w-full" disabled={pending}>
        {pending ? "Creating your account…" : "Create account"}
      </Button>
    </form>
  );
}
