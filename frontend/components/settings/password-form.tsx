"use client";

import { useState } from "react";
import { KeyRound } from "lucide-react";

import { PasswordInput } from "@/components/auth/password-input";
import { Field } from "@/components/ui/field";
import { failureMessage } from "@/components/ui/interactive";
import { Button, Notice } from "@/components/ui/primitives";
import { api } from "@/lib/api/client";
import { passwordProblem } from "@/lib/password";

/**
 * Change the password. The server signs out every other session and says
 * how many; this session stays signed in.
 */
export function PasswordForm({ email }: { email: string }) {
  const [errors, setErrors] = useState<{ current?: string; next?: string; repeat?: string }>({});
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  return (
    <form
      noValidate
      className="max-w-md space-y-4"
      onSubmit={async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const data = new FormData(form);
        const current = String(data.get("current") ?? "");
        const next = String(data.get("next") ?? "");
        const repeat = String(data.get("repeat") ?? "");
        const problems: typeof errors = {};
        if (!current) problems.current = "Enter your current password.";
        const p = passwordProblem(next, email);
        if (p) problems.next = p;
        else if (next === current) problems.next = "Choose a password different from the current one.";
        if (repeat !== next) problems.repeat = "The two new passwords differ.";
        setErrors(problems);
        setDone(null);
        if (Object.keys(problems).length > 0) return;
        setPending(true);
        setError(null);
        try {
          const result = await api.changePassword(current, next);
          form.reset();
          setDone(
            result.other_sessions_revoked > 0
              ? `Password changed. ${result.other_sessions_revoked} other session${result.other_sessions_revoked === 1 ? " was" : "s were"} signed out.`
              : "Password changed. You had no other sessions to sign out.",
          );
        } catch (cause) {
          setError(failureMessage(cause, "The password was not changed."));
        } finally {
          setPending(false);
        }
      }}
    >
      <Field id="pw-current" label="Current password" error={errors.current}>
        <PasswordInput name="current" autoComplete="current-password" />
      </Field>
      <Field id="pw-next" label="New password" error={errors.next} hint="At least 12 characters, not your email address.">
        <PasswordInput name="next" autoComplete="new-password" />
      </Field>
      <Field id="pw-repeat" label="New password again" error={errors.repeat}>
        <PasswordInput name="repeat" autoComplete="new-password" />
      </Field>
      {error ? <Notice tone="bad">{error}</Notice> : null}
      {done ? <Notice tone="ok">{done}</Notice> : null}
      <Button type="submit" tone="primary" disabled={pending}>
        <KeyRound aria-hidden="true" className="size-4" />
        {pending ? "Changing…" : "Change password"}
      </Button>
    </form>
  );
}
