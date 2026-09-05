import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, getEnvironmentSettings, saveEnvironmentSettings } from "@/lib/api";
import type { EnvironmentField, EnvironmentSettings } from "@/types/api";
import { SettingsPanel } from "./SettingsPanel";

vi.mock("@/lib/api", async (loadOriginal) => ({ ...await loadOriginal<typeof import("@/lib/api")>(), getEnvironmentSettings: vi.fn(), saveEnvironmentSettings: vi.fn() }));
const field = (key: string, value: string | null, extra: Partial<EnvironmentField> = {}): EnvironmentField => ({ key, value, group: "llm", kind: "string", options: [], sensitive: false, configured: true, in_file: true, minimum: null, maximum: null, exclusive_minimum: false, ...extra });
const snapshot: EnvironmentSettings = { revision: "a".repeat(64), restart_required: false, fields: [
  field("LLM_MODEL", "model-a"), field("LLM_API_KEY", null, { sensitive: true }),
  field("API_PORT", "8000", { group: "runtime", kind: "integer", minimum: 1, maximum: 65535 }),
  field("AUTH_REQUIRED", "false", { group: "security", kind: "boolean" }),
] };

describe("SettingsPanel", () => {
  beforeEach(() => {
    vi.mocked(getEnvironmentSettings).mockReset().mockResolvedValue(snapshot);
    vi.mocked(saveEnvironmentSettings).mockReset().mockResolvedValue({ ...snapshot, revision: "b".repeat(64), restart_required: true });
  });

  it("saves only changed fields and clears newly typed credentials after saving", async () => {
    render(<SettingsPanel />);
    const model = await screen.findByLabelText("Model name");
    const secret = screen.getByLabelText("API key");
    expect(secret).toHaveValue("");
    expect(secret).toHaveAttribute("type", "password");
    expect(secret).toHaveAttribute("placeholder", "Configured · enter to replace");
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
    fireEvent.change(model, { target: { value: "model-b" } });
    fireEvent.change(secret, { target: { value: "replacement-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(saveEnvironmentSettings).toHaveBeenCalledWith(snapshot.revision, { LLM_MODEL: "model-b", LLM_API_KEY: "replacement-secret" }));
    expect(await screen.findByText("Saved to .env")).toBeInTheDocument();
    expect(secret).toHaveValue("");
    expect(screen.getByText(/Restart the API and web services/)).toBeInTheDocument();
  });

  it("keeps existing secrets untouched unless explicitly replaced or cleared", async () => {
    render(<SettingsPanel />);
    fireEvent.change(await screen.findByLabelText("Model name"), { target: { value: "model-b" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(saveEnvironmentSettings).toHaveBeenCalledWith(snapshot.revision, { LLM_MODEL: "model-b" }));
    await screen.findByText("Saved to .env");
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.getByLabelText("API key")).toBeDisabled();
    expect(screen.getByText("This value will be removed on save.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(screen.getByLabelText("API key")).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(saveEnvironmentSettings).toHaveBeenLastCalledWith("b".repeat(64), { LLM_API_KEY: "" }));
  });

  it("searches environment variable names and keeps changes across categories", async () => {
    render(<SettingsPanel />);
    fireEvent.change(await screen.findByLabelText("Model name"), { target: { value: "model-b" } });
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "API_PORT" } });
    fireEvent.change(screen.getByLabelText("API port"), { target: { value: "9000" } });
    fireEvent.click(screen.getByRole("button", { name: "Security" }));
    fireEvent.click(screen.getByRole("switch", { name: "Require authentication" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(saveEnvironmentSettings).toHaveBeenCalledWith(snapshot.revision, { LLM_MODEL: "model-b", API_PORT: "9000", AUTH_REQUIRED: "true" }));
  });

  it("preserves edits on conflicts until the user explicitly reloads", async () => {
    vi.mocked(saveEnvironmentSettings).mockRejectedValue(new ApiError("Reload settings before saving", 409, "settings_conflict"));
    render(<SettingsPanel />);
    fireEvent.change(await screen.findByLabelText("Model name"), { target: { value: "model-b" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Configuration changed elsewhere");
    expect(screen.getByLabelText("Model name")).toHaveValue("model-b");
    fireEvent.click(screen.getByRole("button", { name: "Discard edits and reload" }));
    await waitFor(() => expect(screen.getByLabelText("Model name")).toHaveValue("model-a"));
  });

  it("offers retry after an initial read fails", async () => {
    vi.mocked(getEnvironmentSettings).mockRejectedValueOnce(new Error("Offline"));
    render(<SettingsPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(await screen.findByLabelText("Model name")).toHaveValue("model-a");
  });
});
