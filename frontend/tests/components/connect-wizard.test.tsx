import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const router = { refresh: vi.fn(), replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const api = vi.hoisted(() => ({ createIntegration: vi.fn(), checkIntegration: vi.fn() }));
vi.mock("@/lib/api/client", async (original) => ({
  ...(await original<typeof import("@/lib/api/client")>()),
  api,
}));

import { ConnectWizard } from "@/components/bots/connect-wizard";
import { ApiError } from "@/lib/api/client";
import type { BotIntegration } from "@/lib/api/types";

const TOKEN = "a-real-looking-bearer-token-1234";

const projects = [{ id: "p1", label: "Acme / Default" }];
const languages = [
  { code: "hi-IN", label: "Hindi (हिन्दी) · hi-IN" },
  { code: "ta-IN", label: "Tamil (தமிழ்) · ta-IN" },
];

function integration(extra: Partial<BotIntegration> = {}): BotIntegration {
  return {
    id: "i1",
    project_id: "p1",
    name: "Support bot",
    protocol: "http",
    url: "https://bot.example.com",
    credential_hint: "…1234",
    default_language: "hi-IN",
    check_status: "unverified",
    last_checked_at: null,
    last_check: null,
    declared: {
      contacts_external_system: true,
      supports_sessions: true,
      requires_credentials: true,
      accepts_containers: [],
      supports_caller_barge_in: false,
      execution_mode: "text_bot_test",
      notes: [],
    },
    created_at: "2026-11-20T10:00:00Z",
    updated_at: "2026-11-20T10:00:00Z",
    ...extra,
  };
}

const connected = integration({
  check_status: "connected",
  last_checked_at: "2026-11-20T10:00:05Z",
  last_check: {
    outcome: "connected",
    message: "The bot opened a session, answered one text turn and closed the session.",
    protocol: "http",
    latency_ms: 41.2,
    verified: { reachable: true, authenticated: true, session_lifecycle: true, text_exchange: true, audio_input: false, audio_output: false },
    detail: {},
  },
});

async function fillTextBot(user: ReturnType<typeof userEvent.setup>, token = TOKEN) {
  await user.click(screen.getByRole("radio", { name: /Text chatbot over HTTP/ }));
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.type(screen.getByLabelText("Name"), "Support bot");
  await user.type(screen.getByLabelText("Base URL"), "https://bot.example.com");
  await user.type(screen.getByLabelText("Bearer token"), token);
}

describe("ConnectWizard", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(cleanup);

  it("explains what a path needs before it asks for anything", async () => {
    const user = userEvent.setup();
    render(<ConnectWizard projects={projects} languages={languages} />);
    expect(screen.queryByLabelText("Bearer token")).toBeNull();
    expect((screen.getByRole("button", { name: "Continue" }) as HTMLButtonElement).disabled).toBe(true);
    await user.click(screen.getByRole("radio", { name: /Real-time voice bot over WebSocket/ }));
    expect(screen.getByText("What you will need")).toBeTruthy();
    expect(screen.getByText(/16 kHz mono pcm_s16le, in 20 ms frames/)).toBeTruthy();
    expect(screen.getByText(/What the bot hears and says aloud/)).toBeTruthy();
  });

  it("does not offer a form for a platform it cannot speak to, and says why", async () => {
    const user = userEvent.setup();
    render(<ConnectWizard projects={projects} languages={languages} />);
    await user.click(screen.getByRole("radio", { name: /A bot on another platform/ }));
    expect(screen.getByText(/no SDK package is published/)).toBeTruthy();
    expect(screen.getByText(/A phone number cannot be tested/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Continue" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("labels the demo as an offline simulation, not a bot", async () => {
    const user = userEvent.setup();
    render(<ConnectWizard projects={projects} languages={languages} />);
    await user.click(screen.getByRole("radio", { name: /No bot yet: try the demo/ }));
    expect(screen.getByText("offline simulation")).toBeTruthy();
    expect(screen.getByText(/No figure from it describes a real bot/)).toBeTruthy();
    expect(screen.getByRole("link", { name: /Open the demo run/ }).getAttribute("href")).toBe("/app/runs/new");
  });

  it("masks the token and refuses a draft the server would refuse, without sending it", async () => {
    const user = userEvent.setup();
    render(<ConnectWizard projects={projects} languages={languages} />);
    await user.click(screen.getByRole("radio", { name: /Text chatbot over HTTP/ }));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect((screen.getByLabelText("Bearer token") as HTMLInputElement).type).toBe("password");
    await user.type(screen.getByLabelText("Name"), "Support bot");
    await user.type(screen.getByLabelText("Base URL"), "wss://bot.example.com");
    await user.type(screen.getByLabelText("Bearer token"), "short");
    await user.click(screen.getByRole("button", { name: "Save and check connection" }));
    expect(api.createIntegration).not.toHaveBeenCalled();
    expect(screen.getByText(/starts with https:\/\/ or http:\/\//)).toBeTruthy();
    expect(screen.getByText(/16 to 4096 characters/)).toBeTruthy();
  });

  it("saves, checks through the API, and offers a test only once connected", async () => {
    const user = userEvent.setup();
    api.createIntegration.mockResolvedValue(integration());
    api.checkIntegration.mockResolvedValue({ integration: connected, ok: true });
    render(<ConnectWizard projects={projects} languages={languages} />);
    await fillTextBot(user);
    await user.click(screen.getByRole("button", { name: "Save and check connection" }));
    expect(api.createIntegration).toHaveBeenCalledWith("p1", {
      name: "Support bot",
      protocol: "http",
      url: "https://bot.example.com",
      token: TOKEN,
      default_language: "hi-IN",
    });
    expect(api.checkIntegration).toHaveBeenCalledWith("i1");
    expect(await screen.findByText("Connection successful")).toBeTruthy();
    expect(screen.getByText("Configuration saved")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Test this bot/ }).getAttribute("href")).toBe("/app/runs/new?bot=i1");
    // A text bot carries no audio: that is shown as a fact of the protocol, not a failure.
    expect(screen.getAllByText("Not in this protocol")).toHaveLength(2);
    expect(document.body.textContent).not.toContain(TOKEN);
  });

  it("shows a failed check as the outcome it was, with no way to test", async () => {
    const user = userEvent.setup();
    api.createIntegration.mockResolvedValue(integration());
    api.checkIntegration.mockResolvedValue({
      ok: false,
      integration: integration({
        check_status: "failed",
        last_check: {
          outcome: "authentication_failed",
          message: "the bot refused the credential when asked to open a session (401)",
          protocol: "http",
          latency_ms: null,
          verified: { reachable: true, authenticated: false, session_lifecycle: null, text_exchange: null, audio_input: false, audio_output: false },
          detail: {},
        },
      }),
    });
    render(<ConnectWizard projects={projects} languages={languages} />);
    await fillTextBot(user);
    await user.click(screen.getByRole("button", { name: "Save and check connection" }));
    const status = await screen.findByRole("status");
    expect(within(status).getByText("Authentication failed")).toBeTruthy();
    expect(screen.getByText(/Replace it with the one your bot expects/)).toBeTruthy();
    expect(screen.queryByRole("link", { name: /Test this bot/ })).toBeNull();
    expect(screen.getAllByText("Not checked")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Check again" })).toBeTruthy();
  });

  it("keeps the form and the server's words when saving is refused", async () => {
    const user = userEvent.setup();
    api.createIntegration.mockRejectedValue(new ApiError("an integration named 'Support bot' already exists in this project", { kind: "http", status: 409 }));
    render(<ConnectWizard projects={projects} languages={languages} />);
    await fillTextBot(user);
    await user.click(screen.getByRole("button", { name: "Save and check connection" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText(/already exists in this project/)).toBeTruthy();
    expect(api.checkIntegration).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Base URL")).toBeTruthy();
  });

  it("asks for a role rather than showing a form nobody may submit", () => {
    render(<ConnectWizard projects={[]} languages={languages} />);
    expect(screen.getByText(/needs the member role or above/)).toBeTruthy();
    expect(screen.queryByRole("radio")).toBeNull();
  });
});
