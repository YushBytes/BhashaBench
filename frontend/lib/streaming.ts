/**
 * A streaming bot turn's caller barge-in evidence, in words.
 *
 * Reads `evidence.caller_barge_in` from a `bot_exchange` stage. Every
 * figure is the backend's measurement; when the interruption was not sent,
 * the sentence says why instead of reporting a result.
 */

type Json = Record<string, unknown>;

export function describeBargeIn(evidence: Json | null | undefined): string | null {
  const barge = evidence?.caller_barge_in;
  if (barge === null || typeof barge !== "object") return null;
  const b = barge as Json;
  if (b.sent !== true) {
    return `Caller barge-in not sent: ${String(b.not_sent_reason ?? "no reason recorded")}.`;
  }
  const at = Math.round(Number(b.sent_after_bot_speech_ms));
  const stopped = Math.round(Number(b.bot_stopped_after_ms));
  return b.bot_yielded === true
    ? `Caller talked over the bot ${at} ms into its reply; the bot stopped within ${stopped} ms.`
    : `Caller talked over the bot ${at} ms into its reply; the bot kept talking for ${stopped} ms (did not yield within ${Number(b.yield_window_ms)} ms).`;
}
