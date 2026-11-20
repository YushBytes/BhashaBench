/**
 * The outcome of a connection check, and what it did and did not establish.
 *
 * Three states per capability, never two: verified, failed (or not carried by
 * the protocol at all), and "not checked". A handshake that succeeded says
 * nothing about whether the bot answers audio well, so that row stays "not
 * checked" instead of borrowing the check's green.
 */

import { CheckCircle2, XCircle } from "lucide-react";

import { cx } from "@/components/ui/primitives";
import { VerifiedMark } from "@/components/ui/status";
import type { BotIntegration } from "@/lib/api/types";
import { formatTimestamp } from "@/lib/format";
import { CAPABILITY_LABELS, NOT_CARRIED, OUTCOMES } from "@/lib/integration";

export function CheckResult({ integration }: { integration: BotIntegration }) {
  const check = integration.last_check;
  if (!check) {
    return (
      <p className="rounded-md border border-dashed border-line px-3 py-3 text-[13px] leading-relaxed text-text-3">
        Not checked yet. Saving contacts nothing: run a connection check to find out whether BhashaBench can reach this bot.
      </p>
    );
  }
  const copy = OUTCOMES[check.outcome] ?? { title: check.outcome, advice: "" };
  const ok = check.outcome === "connected";
  const notCarried = NOT_CARRIED[integration.protocol];
  return (
    <div className="space-y-3">
      <div
        role="status"
        className={cx("flex gap-3 rounded-md border px-3 py-3", ok ? "border-ok/25 bg-ok-soft" : "border-bad/25 bg-bad-soft")}
      >
        {ok ? (
          <CheckCircle2 aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-ok" />
        ) : (
          <XCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-bad" />
        )}
        <div className="min-w-0">
          <p className={cx("text-[14px] font-semibold", ok ? "text-ok" : "text-bad")}>{copy.title}</p>
          <p className="mt-0.5 break-words text-[13px] leading-relaxed text-text-2">{check.message}</p>
          {!ok && copy.advice ? <p className="mt-1 text-[12px] leading-relaxed text-text-2">{copy.advice}</p> : null}
          <p className="mt-1 text-[12px] text-text-3">
            {integration.last_checked_at ? `Checked ${formatTimestamp(integration.last_checked_at)}` : null}
            {check.latency_ms !== null ? ` · ${Math.round(check.latency_ms)} ms end to end` : null}
          </p>
        </div>
      </div>
      <dl className="divide-y divide-line rounded-md border border-line">
        {orderedCapabilities(check.verified).map(([key, value]) => (
          <div key={key} className="flex items-center justify-between gap-3 px-3 py-2">
            <dt className="text-[13px] text-text-2">{CAPABILITY_LABELS[key] ?? key}</dt>
            <dd>
              <VerifiedMark value={value} notCarried={value === false && notCarried.includes(key)} />
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** The check's capabilities in reading order. JSONB does not keep key order,
 *  so a reloaded check would otherwise list them shuffled. */
function orderedCapabilities(verified: Record<string, boolean | null>): [string, boolean | null][] {
  const known = Object.keys(CAPABILITY_LABELS).filter((key) => key in verified);
  const rest = Object.keys(verified).filter((key) => !(key in CAPABILITY_LABELS)).sort();
  return [...known, ...rest].map((key) => [key, verified[key] ?? null]);
}
