import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HistoryActions } from "@/components/history/HistoryActions";

describe("HistoryActions", () => {
  it("opens on right click without activating the history item, then deletes", async () => {
    const open = vi.fn();
    const remove = vi.fn().mockResolvedValue(undefined);
    render(<HistoryActions title="Saved topic" onDelete={remove}><button onClick={open}>Saved topic</button></HistoryActions>);
    fireEvent.contextMenu(screen.getByRole("button", { name: "Saved topic" }), { clientX: 100, clientY: 100 });
    expect(open).not.toHaveBeenCalled();
    expect(screen.getByRole("menuitem", { name: "Delete" })).toHaveFocus();
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
    expect(remove).toHaveBeenCalledTimes(1);
  });

  it("shows errors and allows retry without removing the record", async () => {
    const remove = vi.fn().mockRejectedValueOnce(new Error("Server unavailable")).mockResolvedValue(undefined);
    render(<HistoryActions title="Saved topic" onDelete={remove}><span>Saved topic</span></HistoryActions>);
    fireEvent.click(screen.getByRole("button", { name: "More actions · Saved topic" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Server unavailable");
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
    expect(remove).toHaveBeenCalledTimes(2);
  });

  it("supports keyboard menu access and dismissal", () => {
    render(<HistoryActions title="Saved topic" onDelete={vi.fn()}><button>Saved topic</button></HistoryActions>);
    fireEvent.keyDown(screen.getByRole("button", { name: "Saved topic" }), { key: "F10", shiftKey: true });
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "More actions · Saved topic" })).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "More actions · Saved topic" }));
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});
