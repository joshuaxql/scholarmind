import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { WorkspaceShell } from "@/components/layout/WorkspaceShell";
import { ModeSwitch } from "@/components/layout/ModeSwitch";
import { deleteResearch, listPapers, listResearch, removePaperHistory } from "@/lib/api";

const route = vi.hoisted(() => ({ pathname: "/", replace: vi.fn() }));
vi.mock("next/navigation", () => ({ usePathname: () => route.pathname, useRouter: () => ({ replace: route.replace }) }));
vi.mock("@/lib/api", () => ({ listPapers: vi.fn(), listResearch: vi.fn(), deleteResearch: vi.fn(), removePaperHistory: vi.fn() }));

describe("WorkspaceShell", () => {
  beforeEach(() => {
    route.pathname = "/";
    route.replace.mockReset();
    vi.mocked(deleteResearch).mockReset();
    vi.mocked(removePaperHistory).mockReset();
    vi.mocked(listPapers).mockResolvedValue({ items: [], total: 0, limit: 8, offset: 0 });
    vi.mocked(listResearch).mockResolvedValue({ items: [], total: 0, limit: 8, offset: 0 });
  });

  it("provides both work modes and tracks the active route", async () => {
    const view = render(<WorkspaceShell><ModeSwitch mode="paper" /></WorkspaceShell>);
    const navigation = within(screen.getByRole("navigation", { name: "Work mode" }));
    expect(navigation.getByRole("link", { name: "Paper reading" })).toHaveAttribute("aria-current", "page");
    expect(navigation.getByRole("link", { name: "Topic exploration" })).toHaveAttribute("href", "/research");
    route.pathname = "/research/saved-topic";
    view.rerender(<WorkspaceShell><ModeSwitch mode="research" /></WorkspaceShell>);
    expect(navigation.getByRole("link", { name: "Topic exploration" })).toHaveAttribute("aria-current", "page");
    expect(navigation.getByRole("link", { name: "Paper reading" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: "New task" })).toHaveAttribute("href", "/research");
    await screen.findByText("Your topics will appear here");
  });

  it("links saved topics to a restorable page", async () => {
    vi.mocked(listResearch).mockResolvedValue({ items: [{ id: "saved-1", topic: "Multimodal RAG" }], total: 1, limit: 8, offset: 0 } as Awaited<ReturnType<typeof listResearch>>);
    render(<WorkspaceShell><p>Workspace</p></WorkspaceShell>);
    expect(await screen.findByRole("link", { name: "Multimodal RAG" })).toHaveAttribute("href", "/research/saved-1");
  });

  it("clears the current draft when starting a new task", async () => {
    render(<WorkspaceShell><input aria-label="Draft" defaultValue="" /></WorkspaceShell>);
    fireEvent.change(screen.getByLabelText("Draft"), { target: { value: "Old draft" } });
    fireEvent.click(screen.getByRole("link", { name: "New task" }));
    expect(screen.getByLabelText("Draft")).toHaveValue("");
    await screen.findByText("Your papers will appear here");
  });

  it("keeps both modes available when history fails", async () => {
    vi.mocked(listResearch).mockRejectedValueOnce(new Error("Offline"));
    render(<WorkspaceShell><p>Workspace</p></WorkspaceShell>);
    fireEvent.click(await screen.findByRole("button", { name: "History unavailable · Retry" }));
    expect(screen.getByRole("link", { name: "Topic exploration" })).toHaveAttribute("href", "/research");
    expect(await screen.findByText("Your topics will appear here")).toBeInTheDocument();
  });

  it("deletes the current exploration and returns to a new task", async () => {
    route.pathname = "/research/saved-1";
    vi.mocked(deleteResearch).mockResolvedValue(undefined);
    vi.mocked(listResearch).mockResolvedValue({ items: [{ id: "saved-1", topic: "Delete this exploration" }], total: 1, limit: 8, offset: 0 } as Awaited<ReturnType<typeof listResearch>>);
    render(<WorkspaceShell><p>Workspace</p></WorkspaceShell>);
    fireEvent.contextMenu(await screen.findByRole("link", { name: "Delete this exploration" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
    await waitFor(() => expect(route.replace).toHaveBeenCalledWith("/research"));
    expect(deleteResearch).toHaveBeenCalledWith("saved-1");
    expect(screen.queryByRole("link", { name: "Delete this exploration" })).not.toBeInTheDocument();
  });

  it("removes a recent paper without calling the exploration deletion endpoint", async () => {
    vi.mocked(removePaperHistory).mockResolvedValue(undefined);
    vi.mocked(listPapers).mockResolvedValue({ items: [{ id: "paper-1", title: "Recent paper", status: "ready" }], total: 1, limit: 8, offset: 0 } as Awaited<ReturnType<typeof listPapers>>);
    render(<WorkspaceShell><p>Workspace</p></WorkspaceShell>);
    fireEvent.contextMenu(await screen.findByRole("link", { name: "Recent paper" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Remove from recent papers" }));
    await waitFor(() => expect(screen.queryByRole("link", { name: "Recent paper" })).not.toBeInTheDocument());
    expect(removePaperHistory).toHaveBeenCalledWith("paper-1");
    expect(deleteResearch).not.toHaveBeenCalled();
  });
});
