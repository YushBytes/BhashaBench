"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Loader2 } from "lucide-react";

import { PasswordInput } from "@/components/auth/password-input";
import { Field, Input } from "@/components/ui/field";
import { failureMessage } from "@/components/ui/interactive";
import { Button, Notice, linkClass } from "@/components/ui/primitives";
import { api } from "@/lib/api/client";
import { passwordProblem } from "@/lib/password";

type Errors = Partial<Record<"display_name" | "email" | "password" | "workspace_name", string>>;

/**
 * Create an account. The API creates the user, a workspace they own and a
 * Default project in it, then the form signs in and lands on the overview,
 * whose getting-started list reads what actually exists. Sign-up never joins
 * an existing workspace; an owner adds members by email.
 */
export function SignupForm() {
  const router = useRouter();
  const [errors, setErrors] = useState<Errors>({});
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [stage, setStage] = useState<"creating" | "signing-in" | null>(null);

  return (
    <form
      noValidate
      className="space-y-5"
      onSubmit={async (event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        const body = {
          display_name: String(data.get("display_name") ?? "").trim(),
          email: String(data.get("email") ?? "").trim(),
          password: String(data.get("password") ?? ""),
          workspace_name: String(data.get("workspace_name") ?? "").trim(),
        };
        const problems: Errors = {};
        if (!body.display_name) problems.display_name = "Enter your name.";
        if (!body.email) problems.email = "Enter your email address.";
        else if (!body.email.includes("@")) problems.email = "That does not look like an email address.";
        const passwordError = passwordProblem(body.password, body.email);
        if (passwordError) problems.password = passwordError;
        if (!body.workspace_name) problems.workspace_name = "Name the workspace your tests will live in.";
        setErrors(problems);
        if (Object.keys(problems).length > 0) return;

        setPending(true);
        setError(null);
        setStage("creating");
        try {
          await api.signup(body);
        } catch (cause) {
          setError(failureMessage(cause, "The account was not created."));
          setPending(false);
          setStage(null);
          return;
        }
        setStage("signing-in");
        try {
          await api.login(body.email, body.password);
          router.replace("/app?welcome=1");
          router.refresh();
        } catch (cause) {
          // The account exists; say so, so nobody tries to create it twice.
          setError(`Your account was created, but signing in failed: ${failureMessage(cause, "unknown error")}`);
          setPending(false);
          setStage(null);
        }
      }}
    >
      <Field id="display_name" label="Your name" error={errors.display_name}>
        <Input name="display_name" autoComplete="name" maxLength={200} className="h-10" />
      </Field>
      <Field id="email" label="Work email" error={errors.email}>
        <Input name="email" type="email" autoComplete="email" inputMode="email" maxLength={320} className="h-10" />
      </Field>
      <Field id="password" label="Password" error={errors.password} hint="At least 12 characters. A phrase is easier to remember than symbols.">
        <PasswordInput name="password" autoComplete="new-password" />
      </Field>
      <Field id="workspace_name" label="Workspace name" error={errors.workspace_name} hint="Usually your team or company. You will own it.">
        <Input name="workspace_name" maxLength={200} className="h-10" placeholder="Voice platform team" />
      </Field>

      {error ? <Notice tone="bad">{error}</Notice> : null}

      <Button type="submit" tone="primary" size="lg" className="w-full" disabled={pending} aria-busy={pending}>
        {pending ? <Loader2 aria-hidden="true" className="size-4 animate-spin" /> : null}
        {stage === "creating" ? "Creating your workspace…" : stage === "signing-in" ? "Signing you in…" : "Create account"}
      </Button>

      <p className="text-center text-[14px] text-text-3">
        Already have an account?{" "}
        <Link href="/login" className={linkClass}>
          Sign in
        </Link>
      </p>
    </form>
  );
}
