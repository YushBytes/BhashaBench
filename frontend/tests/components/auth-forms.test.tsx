import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const router = { refresh: vi.fn(), replace: vi.fn(), push: vi.fn() };
let search = new URLSearchParams();
vi.mock("next/navigation", () => ({ useRouter: () => router, useSearchParams: () => search }));

const api = vi.hoisted(() => ({ login: vi.fn(), signup: vi.fn() }));
vi.mock("@/lib/api/client", async (original) => ({
  ...(await original<typeof import("@/lib/api/client")>()),
  api,
}));

import { LoginForm } from "@/components/auth/login-form";
import { SignupForm } from "@/components/auth/signup-form";
import { ApiError } from "@/lib/api/client";

describe("LoginForm", () => {
  afterEach(() => {
    cleanup();
    search = new URLSearchParams();
  });

  it("checks the fields before sending, and ties each error to its field", async () => {
    const user = userEvent.setup();
    render(<LoginForm />);
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(api.login).not.toHaveBeenCalled();
    const email = screen.getByLabelText("Email");
    expect(email.getAttribute("aria-invalid")).toBe("true");
    expect(document.getElementById(email.getAttribute("aria-describedby")!.split(" ")[0])?.textContent).toBe("Enter your email address.");
  });

  it("follows only a safe next path after signing in", async () => {
    const user = userEvent.setup();
    search = new URLSearchParams("next=//evil.example");
    api.login.mockResolvedValue({});
    render(<LoginForm />);
    await user.type(screen.getByLabelText("Email"), "me@example.test");
    await user.type(screen.getByLabelText("Password"), "a long enough phrase");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(router.replace).toHaveBeenCalledWith("/app");
  });

  it("shows the server's single failure message as worded", async () => {
    const user = userEvent.setup();
    api.login.mockRejectedValue(new ApiError("Invalid email or password.", { kind: "http", status: 401 }));
    render(<LoginForm />);
    await user.type(screen.getByLabelText("Email"), "me@example.test");
    await user.type(screen.getByLabelText("Password"), "wrong password!!");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Invalid email or password.");
  });

  it("toggles password visibility and says which state it is in", async () => {
    const user = userEvent.setup();
    render(<LoginForm />);
    const field = screen.getByLabelText("Password") as HTMLInputElement;
    expect(field.type).toBe("password");
    await user.click(screen.getByRole("button", { name: "Show password" }));
    expect(field.type).toBe("text");
    expect(screen.getByRole("button", { name: "Hide password" }).getAttribute("aria-pressed")).toBe("true");
  });
});

describe("SignupForm", () => {
  afterEach(cleanup);

  it("applies the server's password rule before sending", async () => {
    const user = userEvent.setup();
    render(<SignupForm />);
    await user.type(screen.getByLabelText("Your name"), "Asha");
    await user.type(screen.getByLabelText("Work email"), "asha@example.test");
    await user.type(screen.getByLabelText("Password"), "short");
    await user.type(screen.getByLabelText("Workspace name"), "Voice team");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(api.signup).not.toHaveBeenCalled();
    expect(screen.getByText("Use at least 12 characters.")).toBeTruthy();
  });

  it("creates the account, signs in, and lands on the welcome overview", async () => {
    const user = userEvent.setup();
    api.signup.mockResolvedValue({});
    api.login.mockResolvedValue({});
    render(<SignupForm />);
    await user.type(screen.getByLabelText("Your name"), "Asha");
    await user.type(screen.getByLabelText("Work email"), "asha@example.test");
    await user.type(screen.getByLabelText("Password"), "a long enough phrase");
    await user.type(screen.getByLabelText("Workspace name"), "Voice team");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(api.signup).toHaveBeenCalledWith({
      display_name: "Asha",
      email: "asha@example.test",
      password: "a long enough phrase",
      workspace_name: "Voice team",
    });
    expect(api.login).toHaveBeenCalledWith("asha@example.test", "a long enough phrase");
    expect(router.replace).toHaveBeenCalledWith("/app?welcome=1");
  });

  it("says the account exists when sign-in fails after it was created", async () => {
    const user = userEvent.setup();
    api.signup.mockResolvedValue({});
    api.login.mockRejectedValue(new ApiError("rate limited", { kind: "http", status: 429 }));
    render(<SignupForm />);
    await user.type(screen.getByLabelText("Your name"), "Asha");
    await user.type(screen.getByLabelText("Work email"), "asha@example.test");
    await user.type(screen.getByLabelText("Password"), "a long enough phrase");
    await user.type(screen.getByLabelText("Workspace name"), "Voice team");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Your account was created");
  });
});
