import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const router = { refresh: vi.fn(), replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const api = vi.hoisted(() => ({
  copyScenario: vi.fn(),
  archiveScenario: vi.fn(),
  restoreScenario: vi.fn(),
  deleteScenario: vi.fn(),
}));
vi.mock("@/lib/api/client", async (original) => ({
  ...(await original<typeof import("@/lib/api/client")>()),
  api,
}));

import { ScenarioActions } from "@/components/scenario/scenario-actions";
import { ApiError } from "@/lib/api/client";

const props = {
  scenarioId: "s1",
  suiteId: "u1",
  name: "tamil_crop_insurance",
  archived: false,
  canEdit: true,
  canDelete: true,
};

describe("ScenarioActions", () => {
  afterEach(cleanup);

  it("shows the server's refusal when recorded runs block a delete, and stays on the page", async () => {
    const user = userEvent.setup();
    api.deleteScenario.mockRejectedValue(
      new ApiError("scenario has 2 recorded run(s); Archive it instead", { kind: "http", status: 409 }),
    );
    render(<ScenarioActions {...props} />);
    await user.click(screen.getByRole("button", { name: "Delete…" }));
    await user.click(screen.getByRole("button", { name: "Delete permanently" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("scenario has 2 recorded run(s); Archive it instead");
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("asks before deleting, and keeping it sends nothing", async () => {
    const user = userEvent.setup();
    render(<ScenarioActions {...props} />);
    await user.click(screen.getByRole("button", { name: "Delete…" }));
    await user.click(screen.getByRole("button", { name: "Keep it" }));
    expect(api.deleteScenario).not.toHaveBeenCalled();
  });

  it("duplicates under the name typed, into the same suite, and opens the copy", async () => {
    const user = userEvent.setup();
    api.copyScenario.mockResolvedValue({ id: "s2", name: "tamil_v2" });
    render(<ScenarioActions {...props} />);
    const box = screen.getByRole("textbox", { name: "Duplicate in this suite" });
    await user.clear(box);
    await user.type(box, "tamil_v2");
    await user.click(screen.getByRole("button", { name: "Duplicate" }));
    expect(api.copyScenario).toHaveBeenCalledWith("s1", "u1", "tamil_v2");
    expect(router.push).toHaveBeenCalledWith("/app/scenarios/s2");
  });

  it("archives, then offers restore once the page reloads archived", async () => {
    const user = userEvent.setup();
    api.archiveScenario.mockResolvedValue({});
    const { rerender } = render(<ScenarioActions {...props} />);
    await user.click(screen.getByRole("button", { name: "Archive" }));
    expect(api.archiveScenario).toHaveBeenCalledWith("s1");
    rerender(<ScenarioActions {...props} archived />);
    expect(screen.getByRole("button", { name: "Restore" })).toBeTruthy();
  });

  it("is read-only to a viewer, and hides Delete from a member", () => {
    const { unmount } = render(<ScenarioActions {...props} canEdit={false} canDelete={false} />);
    expect(screen.getByText(/read-only to you/)).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
    unmount();
    render(<ScenarioActions {...props} canDelete={false} />);
    expect(screen.queryByRole("button", { name: "Delete…" })).toBeNull();
  });
});
