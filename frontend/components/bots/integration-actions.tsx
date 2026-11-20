"use client";

/**
 * What can be done to a connected bot: check it, change where it is, replace
 * its token, remove it. Each calls the API and then refreshes the page from
 * the server, so the screen never shows a change the server has not accepted.
 *
 * Changing the URL or the token resets the bot to "not verified" on the
 * server; the dialogs say so before anything is sent.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";

import { Field, Input } from "@/components/ui/field";
import { ConfirmAction, Dialog, useAction } from "@/components/ui/interactive";
import { Button } from "@/components/ui/primitives";
import { api } from "@/lib/api/client";
import type { BotIntegration } from "@/lib/api/types";
import { tokenProblem, urlProblem } from "@/lib/integration";

export function CheckButton({ integration }: { integration: BotIntegration }) {
  const { error, pending, run } = useAction();
  return (
    <span className="inline-flex flex-col items-end gap-1">
      <Button tone="primary" onClick={() => void run(() => api.checkIntegration(integration.id), "The check could not be run.")} disabled={pending} aria-busy={pending}>
        {pending ? <Loader2 aria-hidden="true" className="size-4 animate-spin" /> : <RefreshCw aria-hidden="true" className="size-4" />}
        {pending ? "Checking…" : "Check connection"}
      </Button>
      {error ? (
        <span role="alert" className="text-[12px] text-bad">
          {error}
        </span>
      ) : null}
    </span>
  );
}

export function EditDetails({ integration }: { integration: BotIntegration }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(integration.name);
  const [url, setUrl] = useState(integration.url);
  const { error, pending, run, setError } = useAction();
  const urlError = urlProblem(integration.protocol, url);
  const moved = url.trim() !== integration.url;
  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}>
        Edit name or URL
      </Button>
      <Dialog
        open={open}
        onClose={() => {
          setOpen(false);
          setError(null);
        }}
        title="Edit connected bot"
        description={moved ? "A new URL resets the bot to not verified: the last check proved nothing about it." : undefined}
        footer={
          <>
            <Button tone="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              tone="primary"
              disabled={pending || Boolean(urlError) || name.trim() === ""}
              onClick={async () => {
                const done = await run(
                  () => api.updateIntegration(integration.id, { name: name.trim(), ...(moved ? { url: url.trim() } : {}) }),
                  "The change was not saved.",
                );
                if (done) setOpen(false);
              }}
            >
              Save
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field id="edit-name" label="Name">
            <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
          </Field>
          <Field id="edit-url" label="URL" error={urlError}>
            <Input value={url} onChange={(e) => setUrl(e.target.value)} spellCheck={false} className="font-mono text-[13px]" />
          </Field>
          {error ? (
            <p role="alert" className="text-[13px] text-bad">
              {error}
            </p>
          ) : null}
        </div>
      </Dialog>
    </>
  );
}

export function ReplaceToken({ integration }: { integration: BotIntegration }) {
  const [open, setOpen] = useState(false);
  const [token, setToken] = useState("");
  const { error, pending, run, setError } = useAction();
  const problem = token === "" ? null : tokenProblem(token);
  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}>
        Replace token
      </Button>
      <Dialog
        open={open}
        onClose={() => {
          setOpen(false);
          setToken("");
          setError(null);
        }}
        title="Replace the bearer token"
        description={`The stored token ends in ${integration.credential_hint} and cannot be shown. A new one is encrypted on save, and resets the bot to not verified until it is checked again.`}
        footer={
          <>
            <Button tone="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              tone="primary"
              disabled={pending || token === "" || Boolean(problem)}
              onClick={async () => {
                const done = await run(() => api.updateIntegration(integration.id, { token }), "The token was not replaced.");
                if (done) {
                  setToken("");
                  setOpen(false);
                }
              }}
            >
              Replace
            </Button>
          </>
        }
      >
        <Field id="replace-token" label="New token" error={problem}>
          <Input type="password" value={token} onChange={(e) => setToken(e.target.value)} autoComplete="new-password" spellCheck={false} className="font-mono text-[13px]" />
        </Field>
        {error ? (
          <p role="alert" className="mt-3 text-[13px] text-bad">
            {error}
          </p>
        ) : null}
      </Dialog>
    </>
  );
}

export function RemoveIntegration({ integration }: { integration: BotIntegration }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  return (
    <span className="inline-flex flex-col items-start gap-1">
      <ConfirmAction
        label="Remove"
        confirmLabel="Remove bot"
        consequence="Runs that used it keep their evidence; new runs cannot use it."
        onConfirm={async () => {
          try {
            await api.deleteIntegration(integration.id);
            router.push("/app/bots");
            router.refresh();
          } catch (cause) {
            setError(cause instanceof Error ? cause.message : "The bot was not removed.");
          }
        }}
      />
      {error ? (
        <span role="alert" className="text-[12px] text-bad">
          {error}
        </span>
      ) : null}
    </span>
  );
}
