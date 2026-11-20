import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const router = { refresh: vi.fn(), replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const api = vi.hoisted(() => ({ createRun: vi.fn(), startRunInBackground: vi.fn() }));
vi.mock("@/lib/api/client", async (original) => ({
  ...(await original<typeof import("@/lib/api/client")>()),
  api,
}));

import { NewRunForm, type ScenarioOption } from "@/components/runs/new-run-form";
import { ApiError } from "@/lib/api/client";
import type { BotAdapter, BotAdapters } from "@/lib/api/types";

const adapter = (name: string, extra: Partial<BotAdapter> = {}): BotAdapter => ({
  name,
  display_name: name,
  selected: false,
  contacts_external_system: false,
  available: true,
  unavailable_reason: null,
  supports_sessions: false,
  supports_caller_barge_in: false,
  requires_credentials: false,
  accepts_containers: ["wav"],
  notes: [],
  ...extra,
});

const adapters: BotAdapters = {
  selected: "scripted",
  adapters: [
    adapter("scripted"),
    adapter("ws_voice", { contacts_external_system: true, supports_caller_barge_in: true }),
    adapter("http", { contacts_external_system: true, accepts_containers: [], available: false, unavailable_reason: "BOT_HTTP_URL is not set" }),
  ],
  telephony_status: "Not implemented.",
  execution_modes: ["offline_simulation", "audio_fixture_test", "external_bot_test", "text_bot_test"],
};

const scenarios: ScenarioOption[] = [
  {
    id: "sc1",
    suite_id: "su1",
    name: "tamil_demo",
    description: null,
    language: "ta-IN",
    created_at: "",
    updated_at: "",
    archived_at: null,
    suite_label: "Default / Release",
  },
];

describe("NewRunForm", () => {
  afterEach(cleanup);

  it("creates then starts the run in the background, and opens it", async () => {
    const user = userEvent.setup();
    api.createRun.mockResolvedValue({ run_id: "r1" });
    api.startRunInBackground.mockResolvedValue({});
    render(<NewRunForm scenarios={scenarios} adapters={adapters} initialScenarioId="sc1" />);
    await user.click(screen.getByRole("button", { name: "Start test run" }));
    expect(api.createRun).toHaveBeenCalledWith(
      expect.objectContaining({ suite_id: "su1", scenario_id: "sc1", mode: "audio_fixture_test", bot_adapter: "scripted", caller_barge_in_after_ms: null }),
    );
    expect(api.startRunInBackground).toHaveBeenCalledWith("r1");
    expect(router.push).toHaveBeenCalledWith("/app/runs/r1");
  });

  it("says the run exists, with a link, when it was created but did not start", async () => {
    const user = userEvent.setup();
    api.createRun.mockResolvedValue({ run_id: "abcdef12-0000-0000-0000-000000000000" });
    api.startRunInBackground.mockRejectedValue(new ApiError("too many runs in flight", { kind: "http", status: 503 }));
    render(<NewRunForm scenarios={scenarios} adapters={adapters} initialScenarioId="sc1" />);
    await user.click(screen.getByRole("button", { name: "Start test run" }));
    expect(await screen.findByText("The run was created but did not start")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open run abcdef12" }).getAttribute("href")).toBe("/app/runs/abcdef12-0000-0000-0000-000000000000");
    expect(router.push).not.toHaveBeenCalled();
  });

  it("offers caller barge-in only on an adapter that can talk over the bot", async () => {
    const user = userEvent.setup();
    render(<NewRunForm scenarios={scenarios} adapters={adapters} initialScenarioId="sc1" />);
    const field = screen.getByLabelText(/Caller interrupts the bot after/) as HTMLInputElement;
    expect(field.disabled).toBe(true);
    await user.click(screen.getByRole("radio", { name: /External voice bot/ }));
    expect((screen.getByLabelText(/Caller interrupts the bot after/) as HTMLInputElement).disabled).toBe(false);
  });

  it("refuses an out-of-range line condition before sending anything", async () => {
    const user = userEvent.setup();
    render(<NewRunForm scenarios={scenarios} adapters={adapters} initialScenarioId="sc1" />);
    await user.type(screen.getByLabelText(/Jitter/), "999");
    await user.click(screen.getByRole("button", { name: "Start test run" }));
    expect(api.createRun).not.toHaveBeenCalled();
    expect(screen.getAllByText(/Jitter must be between 0 and 300 ms/).length).toBeGreaterThan(0);
  });

  it("will not pick an adapter this deployment has not configured", () => {
    render(<NewRunForm scenarios={scenarios} adapters={adapters} initialScenarioId="sc1" />);
    expect((screen.getByRole("radio", { name: /^http/ }) as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByText("Not configured: BOT_HTTP_URL is not set")).toBeTruthy();
  });
});
