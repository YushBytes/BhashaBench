import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

const api = vi.hoisted(() => ({
  turnReferences: vi.fn(),
  addTurnReference: vi.fn(),
}));
vi.mock("@/lib/api/client", async (original) => ({
  ...(await original<typeof import("@/lib/api/client")>()),
  api,
}));

import { ReferenceEditor } from "@/components/runs/reference-editor";

describe("ReferenceEditor", () => {
  beforeEach(() => {
    api.turnReferences.mockResolvedValue({ run_id: "r1", turn_index: 1, references: [] });
  });
  afterEach(cleanup);

  it("says a turn without a reference has no WER, and starts the draft from the transcript", async () => {
    const user = userEvent.setup();
    render(<ReferenceEditor runId="r1" turnIndex={1} transcript="namaste ji" canEdit />);
    expect(await screen.findByText(/None recorded, so this turn has no WER or CER/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Add reference" }));
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("namaste ji");
  });

  it("sends the reviewer's corrected text and says to evaluate again", async () => {
    const user = userEvent.setup();
    api.addTurnReference.mockResolvedValue({
      reference_id: "x",
      run_id: "r1",
      turn_index: 1,
      text: "namaste ji, policy number?",
      reviewer: null,
      created_at: "2026-11-19T00:00:00Z",
    });
    render(<ReferenceEditor runId="r1" turnIndex={1} transcript="namaste ji" canEdit />);
    await user.click(await screen.findByRole("button", { name: "Add reference" }));
    const box = screen.getByRole("textbox");
    await user.clear(box);
    await user.type(box, "namaste ji, policy number?");
    await user.click(screen.getByRole("button", { name: "Save reference" }));
    expect(api.addTurnReference).toHaveBeenCalledWith("r1", 1, {
      text: "namaste ji, policy number?",
    });
    expect(
      await screen.findByText("Saved. Evaluate again to include it in WER and CER."),
    ).toBeTruthy();
    expect(screen.getByText("namaste ji, policy number?")).toBeTruthy();
    expect(refresh).toHaveBeenCalled();
  });

  it("will not save an empty reference", async () => {
    const user = userEvent.setup();
    render(<ReferenceEditor runId="r1" turnIndex={1} transcript="" canEdit />);
    await user.click(await screen.findByRole("button", { name: "Add reference" }));
    const save = screen.getByRole("button", { name: "Save reference" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
  });

  it("offers no editing to a viewer", async () => {
    render(<ReferenceEditor runId="r1" turnIndex={1} transcript="x" canEdit={false} />);
    expect(await screen.findByText(/None recorded/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Add reference" })).toBeNull();
  });
});
