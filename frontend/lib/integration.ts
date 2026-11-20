/**
 * Connected bots: the rules the "Connect your chatbot" form applies before
 * anything is sent, and the words for each connection-check outcome.
 *
 * Transcribed from backend/app/services/integration_service.py (URL and
 * token rules) and backend/app/pipeline/bots/probe.py (outcomes). The server
 * applies the same rules again and its message is shown as worded;
 * `tests/integration.test.mjs` reads both files and fails if a bound, a
 * scheme or an outcome here disagrees.
 *
 * This module decides nothing about *where* a bot may be reached. Whether a
 * host is public, private or a metadata address is decided by the server's
 * outbound guard when the connection is checked - a browser cannot know what
 * a name resolves to on the server.
 */

import type { IntegrationOutcome, IntegrationProtocol } from "./api/types.ts";

export const MIN_TOKEN_CHARS = 16;
export const MAX_TOKEN_CHARS = 4096;
export const MAX_URL_CHARS = 2048;

export const SCHEMES: Record<IntegrationProtocol, readonly string[]> = {
  http: ["https", "http"],
  ws_voice: ["wss", "ws"],
};

export interface ProtocolCopy {
  title: string;
  summary: string;
  tests: string;
  mode: "text_bot_test" | "external_bot_test";
  urlLabel: string;
  urlPlaceholder: string;
  needs: string[];
}

export const PROTOCOLS: Record<IntegrationProtocol, ProtocolCopy> = {
  http: {
    title: "Text chatbot over HTTP",
    summary: "Your bot answers text turns at an HTTPS endpoint that speaks bhashabench-text-bot/1.",
    tests: "What the bot says: task completion, each reply's words and latency. No audio moves, so nothing about speech is measured.",
    mode: "text_bot_test",
    urlLabel: "Base URL",
    urlPlaceholder: "https://bot.example.com",
    needs: [
      "An HTTPS base URL serving POST /v1/sessions, POST /v1/sessions/{id}/turns and DELETE /v1/sessions/{id}",
      "A bearer token of 16 or more characters that your bot checks on every request",
      "The language your bot should be addressed in",
    ],
  },
  ws_voice: {
    title: "Real-time voice bot over WebSocket",
    summary: "Your bot accepts a WebSocket that speaks bhashabench-voice-bot/1 and streams audio both ways.",
    tests: "What the bot hears and says aloud: synthesised caller speech under the line conditions you choose, the bot's audio, its transcript, latency and barge-in.",
    mode: "external_bot_test",
    urlLabel: "WebSocket URL",
    urlPlaceholder: "wss://bot.example.com/v1/voice",
    needs: [
      "A wss:// URL that answers the start message with ready",
      "Audio in and out as 16 kHz mono pcm_s16le, in 20 ms frames",
      "A bearer token of 16 or more characters, checked during the handshake",
    ],
  },
};

export interface Draft {
  name: string;
  protocol: IntegrationProtocol;
  url: string;
  token: string;
}

export type DraftErrors = Partial<Record<"name" | "url" | "token", string>>;

/** The same shape checks the server applies. Returns no error for a draft it would accept. */
export function validateDraft(draft: Draft, { tokenRequired = true } = {}): DraftErrors {
  const errors: DraftErrors = {};
  const name = draft.name.trim();
  if (name.length < 1 || name.length > 120) errors.name = "A name of 1 to 120 characters.";
  const url = urlProblem(draft.protocol, draft.url);
  if (url) errors.url = url;
  if (tokenRequired || draft.token !== "") {
    const token = tokenProblem(draft.token);
    if (token) errors.token = token;
  }
  return errors;
}

export function urlProblem(protocol: IntegrationProtocol, raw: string): string | null {
  const value = raw.trim();
  if (!value) return "Enter the bot's URL.";
  if (value.length > MAX_URL_CHARS) return `At most ${MAX_URL_CHARS} characters.`;
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    return "This is not a complete URL.";
  }
  const scheme = parsed.protocol.replace(/:$/, "");
  const allowed = SCHEMES[protocol];
  if (!allowed.includes(scheme)) {
    return `A ${protocol === "http" ? "text" : "voice"} bot's URL starts with ${allowed.map((s) => `${s}://`).join(" or ")}.`;
  }
  if (parsed.username || parsed.password) {
    return "Remove the username or password from the URL; the token field is where the credential goes, encrypted.";
  }
  if (parsed.hash) return "Remove the #fragment; no request can send it.";
  if (!parsed.hostname) return "The URL has no host.";
  return null;
}

export function tokenProblem(token: string): string | null {
  if (token.length < MIN_TOKEN_CHARS || token.length > MAX_TOKEN_CHARS) {
    return `${MIN_TOKEN_CHARS} to ${MAX_TOKEN_CHARS} characters; it is sent as Authorization: Bearer <token>.`;
  }
  if (/\s/.test(token)) return "A token has no spaces or line breaks.";
  return null;
}

/** Plain http/ws is accepted only for a bot on the server's own machine in development. */
export function isPlainTransport(url: string): boolean {
  return /^(http|ws):\/\//i.test(url.trim());
}

export interface OutcomeCopy {
  title: string;
  advice: string;
}

export const OUTCOMES: Record<IntegrationOutcome, OutcomeCopy> = {
  connected: { title: "Connection successful", advice: "Every step of the check succeeded. You can run a test against this bot." },
  authentication_failed: { title: "Authentication failed", advice: "Your bot refused the token. Replace it with the one your bot expects." },
  target_refused: {
    title: "Address not allowed",
    advice:
      "BhashaBench refused this URL before connecting: it is a private, local or cloud-metadata address, it does not resolve, or it is plain http to a public host. Use a public https:// or wss:// address.",
  },
  unreachable: { title: "Bot unreachable", advice: "Nothing accepted the connection. Check the host, the port and that the bot is running." },
  timeout: { title: "Connection timed out", advice: "The bot did not answer in time. Check its health and try again." },
  protocol_error: {
    title: "Protocol not recognised",
    advice: "Something answered, but not in the protocol this integration is set to. Check the path and the protocol.",
  },
  session_rejected: {
    title: "Session refused",
    advice: "The voice bot refused the session, most often the audio format. It must accept 16 kHz pcm_s16le in 20 ms frames.",
  },
};

export const CAPABILITY_LABELS: Record<string, string> = {
  reachable: "Reachable",
  authenticated: "Token accepted",
  session_lifecycle: "Session opened and closed",
  text_exchange: "Answered a text turn",
  protocol_accepted: "Protocol accepted",
  audio_format_accepted: "Audio format accepted (16 kHz pcm_s16le)",
  audio_input: "Audio input",
  audio_output: "Audio output",
  caller_barge_in: "Yields when interrupted",
};

/** Capabilities the protocol itself does not carry: `false` there is a fact, not a failure. */
export const NOT_CARRIED: Record<IntegrationProtocol, readonly string[]> = {
  http: ["audio_input", "audio_output"],
  ws_voice: [],
};
