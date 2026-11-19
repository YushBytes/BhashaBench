import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const router = { refresh: vi.fn(), replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const api = vi.hoisted(() => ({
  validateScenario: vi.fn(),
  updateScenario: vi.fn(),
  copyScenario: vi.fn(),
  archiveScenario: vi.fn(),
  restoreScenario: vi.fn(),
  deleteScenario: vi.fn(),
}));
vi.mock("@/lib/api/client", async (original) => ({
  ...(await original<typeof import("@/lib/api/client")>()),
  api,
}));

import { ScenarioManager } from "@/components/domain/scenario-manager";
import { ApiError } from "@/lib/api/client";

const props = {
  scenarioId: "s1",
  suiteId: "u1",
  name: "tamil_crop_insurance",
  spec: { name: "tamil_crop_insurance", language: "ta-IN" },
  archived: false,
  canEdit: true,
  canDelete: true,
};

describe("ScenarioManager", () => {
  afterEach(cleanup);

  it("shows the server's refusal when recorded runs block a delete, and stays on the page", async () => {
    const user = userEvent.setup();
    api.deleteScenario.mockRejectedValue(
      new ApiError("scenario has 2 recorded run(s); Archive it instead", {
        kind: "http",
        status: 409,
      }),
    );
    render(<ScenarioManager {...props} />);
    await user.click(screen.getByRole("button", { name: "Delete…" }));
    await user.click(screen.getByRole("button", { name: "Delete permanently" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("scenario has 2 recorded run(s); Archive it instead");
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("asks before deleting, and keeping it sends nothing", async () => {
    const user = userEvent.setup();
    render(<ScenarioManager {...props} />);
    await user.click(screen.getByRole("button", { name: "Delete…" }));
    await user.click(screen.getByRole("button", { name: "Keep it" }));
    expect(api.deleteScenario).not.toHaveBeenCalled();
  });

  it("saves only after the server validated the edit", async () => {
    const user = userEvent.setup();
    api.validateScenario.mockResolvedValue({ valid: true, errors: [] });
    api.updateScenario.mockResolvedValue({ name: "tamil_crop_insurance" });
    render(<ScenarioManager {...props} />);
    const save = screen.getByRole("button", { name: "Save changes" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    await user.click(screen.getByRole("button", { name: "Validate" }));
    expect(await screen.findByText("Valid. It can be saved.")).toBeTruthy();
    await user.click(save);
    expect(api.updateScenario).toHaveBeenCalledWith("s1", JSON.stringify(props.spec, null, 2));
  });

  it("lists field errors from the validator and keeps Save disabled", async () => {
    const user = userEvent.setup();
    api.validateScenario.mockResolvedValue({
      valid: false,
      errors: [{ field: "persona.accent", message: "unknown accent", type: "value_error" }],
    });
    render(<ScenarioManager {...props} />);
    await user.click(screen.getByRole("button", { name: "Validate" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("persona.accent: unknown accent");
    const save = screen.getByRole("button", { name: "Save changes" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
  });

  it("archives, then offers restore once the page reloads archived", async () => {
    const user = userEvent.setup();
    api.archiveScenario.mockResolvedValue({});
    const { rerender } = render(<ScenarioManager {...props} />);
    await user.click(screen.getByRole("button", { name: "Archive" }));
    expect(api.archiveScenario).toHaveBeenCalledWith("s1");
    rerender(<ScenarioManager {...props} archived />);
    expect(screen.getByRole("button", { name: "Restore" })).toBeTruthy();
  });

  it("is read-only to a viewer, and hides Delete from a member", () => {
    const { unmount } = render(
      <ScenarioManager {...props} canEdit={false} canDelete={false} />,
    );
    expect(screen.getByText(/read-only to you/)).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
    unmount();
    render(<ScenarioManager {...props} canDelete={false} />);
    expect(screen.queryByRole("button", { name: "Delete…" })).toBeNull();
  });
});
