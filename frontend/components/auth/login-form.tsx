"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Loader2 } from "lucide-react";

import { PasswordInput } from "@/components/auth/password-input";
import { Field, Input } from "@/components/ui/field";
import { failureMessage } from "@/components/ui/interactive";
import { Button, Notice, linkClass } from "@/components/ui/primitives";
import { api } from "@/lib/api/client";
import { safeNext } from "@/lib/redirect";

/**
 * Sign in with a first-party HttpOnly cookie. The API answers every failure
 * with one 401 and one message, so the form shows that message as worded
 * rather than guessing which field was wrong.
 */
export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<{ email?: string; password?: string }>({});

  return (
    <form
      noValidate
      className="space-y-5"
      onSubmit={async (event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        const email = String(data.get("email") ?? "").trim();
        const password = String(data.get("password") ?? "");
        const problems: typeof fieldErrors = {};
        if (!email) problems.email = "Enter your email address.";
        else if (!email.includes("@")) problems.email = "That does not look like an email address.";
        if (!password) problems.password = "Enter your password.";
        setFieldErrors(problems);
        if (Object.keys(problems).length > 0) return;

        setPending(true);
        setError(null);
        try {
          await api.login(email, password);
          router.replace(next);
          router.refresh();
        } catch (cause) {
          setError(failureMessage(cause, "Signing in failed."));
          setPending(false);
        }
      }}
    >
      {params.get("expired") ? <Notice tone="warn">Your session ended. Sign in again to continue.</Notice> : null}
      {params.get("signed_out") ? <Notice tone="ok">You are signed out.</Notice> : null}
      {params.get("password_changed") ? (
        <Notice tone="ok">Password changed. Sign in with the new one.</Notice>
      ) : null}

      <Field id="email" label="Email" error={fieldErrors.email}>
        <Input name="email" type="email" autoComplete="email" inputMode="email" className="h-10" />
      </Field>
      <Field
        id="password"
        label="Password"
        error={fieldErrors.password}
        hint="Forgotten passwords cannot be reset from here yet. If you are signed in on another device, change it under Settings."
      >
        <PasswordInput name="password" autoComplete="current-password" />
      </Field>

      {error ? <Notice tone="bad">{error}</Notice> : null}

      <Button type="submit" tone="primary" size="lg" className="w-full" disabled={pending} aria-busy={pending}>
        {pending ? <Loader2 aria-hidden="true" className="size-4 animate-spin" /> : null}
        {pending ? "Signing in…" : "Sign in"}
      </Button>

      <p className="text-center text-[14px] text-text-3">
        New to BhashaBench?{" "}
        <Link href="/signup" className={linkClass}>
          Create an account
        </Link>
      </p>
    </form>
  );
}
