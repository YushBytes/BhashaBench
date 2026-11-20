import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { parse } from "yaml";

const router = { refresh: vi.fn(), replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const api = vi.hoisted(() => ({
  validateScenario: vi.fn(),
  createScenario: vi.fn(),
  updateScenario: vi.fn(),
}));
vi.mock("@/lib/api/client", async (original) => ({
  ...(await original<typeof import("@/lib/api/client")>()),
  api,
}));

import { ScenarioBuilder } from "@/components/scenario/scenario-builder";
import type { Language, LibraryScenario } from "@/lib/api/types";

const languages: Language[] = [
  { code: "hi-IN", name: "Hindi", endonym: "हिन्दी", script: "Deva", locale: "hi_IN", accents: [] },
  {
    code: "ta-IN",
    name: "Tamil",
    endonym: "தமிழ்",
    script: "Taml",
    locale: "ta_IN",
    accents: [{ key: "ta-IN.west", name: "Western Tamil Nadu", description: "" }],
  },
];

const library: LibraryScenario[] = [
  {
    key: "demo/tamil",
    name: "tamil_demo",
    language: "ta-IN",
    description: "A demo",
    objective: "Check a claim.",
    yaml: "name: tamil_demo\nlanguage: ta-IN\n# a comment\npersona:\n  identity: farmer\ngoal:\n  objective: >-\n    Check the\n    claim.\nexpected_outcomes:\n  - State the claim status\n",
  },
];

function renderCreate() {
  return render(<ScenarioBuilder mode="create" suites={[{ id: "u1", label: "Default / Release" }]} languages={languages} library={library} />);
}

describe("ScenarioBuilder", () => {
  afterEach(cleanup);

  it("loads a reference scenario into the guided form, folded YAML included", async () => {
    const user = userEvent.setup();
    renderCreate();
    await user.selectOptions(screen.getByLabelText("Start from"), "demo/tamil");
    expect((screen.getByLabelText("Name") as HTMLInputElement).value).toBe("tamil_demo");
    await user.click(screen.getByRole("button", { name: /Goal and outcomes/ }));
    expect((screen.getByLabelText("Objective") as HTMLTextAreaElement).value).toBe("Check the claim.");
  });

  it("validates with the server before creating, and sends the suite and the YAML it showed", async () => {
    const user = userEvent.setup();
    api.validateScenario.mockResolvedValue({ valid: true, errors: [], normalized_yaml: null });
    api.createScenario.mockResolvedValue({ id: "s9", name: "tamil_demo" });
    renderCreate();
    await user.selectOptions(screen.getByLabelText("Start from"), "demo/tamil");
    await user.click(screen.getByRole("button", { name: "Validate and create" }));
    expect(api.validateScenario).toHaveBeenCalledTimes(1);
    const sent = api.createScenario.mock.calls[0];
    expect(sent[0]).toBe("u1");
    expect(sent[1]).toBe(api.validateScenario.mock.calls[0][0]);
    expect(parse(sent[1])).toMatchObject({ name: "tamil_demo", language: "ta-IN", goal: { objective: "Check the claim." } });
    expect(router.push).toHaveBeenCalledWith("/app/scenarios/s9?created=1");
  });

  it("does not create when the server refuses, and puts each error on its field and section", async () => {
    const user = userEvent.setup();
    api.validateScenario.mockResolvedValue({
      valid: false,
      errors: [{ field: "goal.objective", message: "String should have at least 1 character", type: "string_too_short" }],
      normalized_yaml: null,
    });
    renderCreate();
    await user.click(screen.getByRole("button", { name: "Validate and create" }));
    expect(api.createScenario).not.toHaveBeenCalled();
    // The builder jumps to the section that owns the first error.
    const objective = await screen.findByLabelText("Objective");
    expect(objective.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getAllByText("String should have at least 1 character").length).toBeGreaterThan(0);
    const nav = screen.getByRole("navigation", { name: "Scenario sections" });
    expect(within(nav).getByText(/errors/).closest("button")?.textContent).toContain("Goal and outcomes");
  });

  it("offers only the chosen language's accent profiles, and clears the accent when the language changes", async () => {
    const user = userEvent.setup();
    renderCreate();
    await user.selectOptions(screen.getByLabelText("Language"), "ta-IN");
    await user.click(screen.getByRole("button", { name: /Language and accent/ }));
    await user.selectOptions(screen.getByLabelText(/Accent profile/), "ta-IN.west");
    await user.click(screen.getByRole("button", { name: /Basics/ }));
    await user.selectOptions(screen.getByLabelText("Language"), "hi-IN");
    await user.click(screen.getByRole("button", { name: /Language and accent/ }));
    const accent = screen.getByLabelText(/Accent profile/) as HTMLSelectElement;
    expect(accent.value).toBe("");
    expect([...accent.options].map((o) => o.value)).toEqual([""]);
  });

  it("edits through PUT on the same scenario id", async () => {
    const user = userEvent.setup();
    api.validateScenario.mockResolvedValue({ valid: true, errors: [], normalized_yaml: null });
    api.updateScenario.mockResolvedValue({ id: "s1", name: "x" });
    render(
      <ScenarioBuilder
        mode="edit"
        scenarioId="s1"
        suites={[]}
        languages={languages}
        library={null}
        initialSpec={{ name: "x", language: "hi-IN", persona: { identity: "a" }, goal: { objective: "b" }, expected_outcomes: ["c"] }}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Validate and save" }));
    expect(api.updateScenario.mock.calls[0][0]).toBe("s1");
    expect(api.createScenario).not.toHaveBeenCalled();
  });
});
