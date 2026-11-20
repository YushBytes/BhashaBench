import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const router = { refresh: vi.fn(), replace: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const api = vi.hoisted(() => ({ renameSuite: vi.fn(), deleteSuite: vi.fn() }));
vi.mock("@/lib/api/client", async (original) => ({
  ...(await original<typeof import("@/lib/api/client")>()),
  api,
}));

import { SuiteActions as SuiteRow } from "@/components/domain/suite-controls";
import { ApiError } from "@/lib/api/client";

describe("SuiteActions", () => {
  afterEach(cleanup);

  it("deletes an empty suite without asking to take scenarios with it", async () => {
    const user = userEvent.setup();
    api.deleteSuite.mockResolvedValue(undefined);
    render(<SuiteRow id="u1" name="Insurance" canEdit />);
    await user.click(screen.getByRole("button", { name: "Delete…" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(api.deleteSuite).toHaveBeenCalledWith("u1", false);
    expect(router.refresh).toHaveBeenCalled();
  });

  it("asks again, naming what goes too, when the suite still holds scenarios", async () => {
    const user = userEvent.setup();
    api.deleteSuite.mockRejectedValueOnce(
      new ApiError("suite 'Insurance' still holds 2 scenarios; pass cascade=true", {
        kind: "http",
        status: 409,
      }),
    );
    api.deleteSuite.mockResolvedValueOnce(undefined);
    render(<SuiteRow id="u1" name="Insurance" canEdit />);
    await user.click(screen.getByRole("button", { name: "Delete…" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(await screen.findByText(/Delete it and every scenario in it\? Not reversible\./)).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("still holds 2 scenarios");
    await user.click(screen.getByRole("button", { name: "Delete all" }));
    expect(api.deleteSuite).toHaveBeenLastCalledWith("u1", true);
  });

  it("renames with the trimmed name", async () => {
    const user = userEvent.setup();
    api.renameSuite.mockResolvedValue({});
    render(<SuiteRow id="u1" name="Insurance" canEdit />);
    await user.click(screen.getByRole("button", { name: "Rename" }));
    const box = screen.getByRole("textbox", { name: "New name for Insurance" });
    await user.clear(box);
    await user.type(box, "  Crop insurance  ");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(api.renameSuite).toHaveBeenCalledWith("u1", "Crop insurance");
  });

  it("offers no controls without edit rights", () => {
    render(<SuiteRow id="u1" name="Insurance" canEdit={false} />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});
