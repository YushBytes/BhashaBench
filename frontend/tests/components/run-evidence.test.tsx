import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const router = { refresh: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const api = vi.hoisted(() => ({ supplyBotText: vi.fn(), supplyBotAudio: vi.fn() }));
vi.mock("@/lib/api/client", async (original) => ({
  ...(await original<typeof import("@/lib/api/client")>()),
  api,
}));

import { RunEvidence } from "@/components/runs/evidence";
import { BotReply } from "@/components/runs/run-controls";
import { EvaluationView } from "@/components/runs/evaluation-view";
import type { EvaluationRead, Run } from "@/lib/api/types";

const run = (extra: Partial<Run>): Run =>
  ({
    run_id: "r1",
    mode: "external_bot_test",
    bot_audio_externally_received: false,
    bot_text_externally_received: false,
    bot_text_replies_received: 0,
    uses_language_model: false,
    stt_provider: "gnani_prisma",
    tts_provider: "gnani_timbre",
    settings_not_enforced: [],
    ...extra,
  }) as Run;

describe("RunEvidence", () => {
  afterEach(cleanup);

  it("derives the caution from the replies, not from the mode label", () => {
    render(<RunEvidence run={run({ mode: "external_bot_test", bot_audio_externally_received: false })} />);
    expect(screen.getByText("Labelled an external bot test, but no external audio arrived")).toBeTruthy();
  });

  it("names offline speech providers, so scripted transcripts are never read as recognition", () => {
    render(<RunEvidence run={run({ mode: "audio_fixture_test", stt_provider: "fake" })} />);
    expect(screen.getByText("Offline speech providers")).toBeTruthy();
  });

  it("cautions that unreviewed caller phrases may be the caller's fault, and says nothing when reviewed", () => {
    render(<RunEvidence run={run({ caller_phrase_review: "unreviewed", language: "bn-IN" })} />);
    expect(screen.getByText("The caller's phrases in this language are unreviewed")).toBeTruthy();
    cleanup();
    render(<RunEvidence run={run({ caller_phrase_review: "reviewed", language: "ta-IN" })} />);
    expect(screen.queryByText("The caller's phrases in this language are unreviewed")).toBeNull();
  });

  it("says unknown, never 'all enforced', for a run that predates the record", () => {
    render(<RunEvidence run={run({ settings_not_enforced: null })} />);
    expect(screen.getByText(/were not recorded for this run/)).toBeTruthy();
  });
});

describe("BotReply", () => {
  afterEach(cleanup);

  it("asks once before recording silence, then sends the empty reply", async () => {
    const user = userEvent.setup();
    api.supplyBotText.mockResolvedValue({});
    render(<BotReply runId="r1" turn={2} kind="text" />);
    await user.click(screen.getByRole("button", { name: "Send reply" }));
    expect(api.supplyBotText).not.toHaveBeenCalled();
    expect(screen.getByText(/records that the bot stayed silent/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Send reply" }));
    expect(api.supplyBotText).toHaveBeenCalledWith("r1", "");
    expect(router.refresh).toHaveBeenCalled();
  });

  it("uploads the chosen audio file to the run", async () => {
    const user = userEvent.setup();
    api.supplyBotAudio.mockResolvedValue({});
    render(<BotReply runId="r1" turn={3} kind="audio" />);
    const upload = screen.getByRole("button", { name: "Upload reply" }) as HTMLButtonElement;
    expect(upload.disabled).toBe(true);
    const file = new File([new Uint8Array([82, 73, 70, 70])], "reply.wav", { type: "audio/wav" });
    await user.upload(screen.getByLabelText(/as an audio file/), file);
    await user.click(upload);
    expect(api.supplyBotAudio).toHaveBeenCalledWith("r1", file);
  });
});

describe("EvaluationView", () => {
  afterEach(cleanup);

  it("shows a missing WER as not reported with the evaluator's reason, never as a number", () => {
    const evaluation: EvaluationRead = {
      evaluation_id: "e1",
      run_id: "r1",
      evaluator_version: "bb-eval-2",
      verdict: "undetermined",
      evidence_fingerprint: "x",
      created_at: "2026-11-19T00:00:00Z",
      criteria: [{ name: "task_completion", status: "undetermined", reason: "the run was cancelled" }],
      metrics: { wer: { value: null, reason: "no reviewed reference transcript" } },
      measures_audio: true,
    };
    render(<EvaluationView evaluations={[evaluation]} catalogue={null} finished />);
    expect(screen.getByText("Not reported")).toBeTruthy();
    expect(screen.getByText("no reviewed reference transcript")).toBeTruthy();
    expect(screen.queryByText("0.0%")).toBeNull();
    expect(screen.getByText("Semantic correctness")).toBeTruthy();
  });
});
