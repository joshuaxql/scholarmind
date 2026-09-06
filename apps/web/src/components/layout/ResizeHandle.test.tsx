import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ResizeHandle, useResizablePanel } from "./ResizeHandle";

function Example({ axis = "x", unit = "px", factor = 1 }: { axis?: "x" | "y"; unit?: "px" | "%"; factor?: number }) {
  const panel = useResizablePanel({ storageKey: "test", initial: unit === "%" ? 40 : 240, min: unit === "%" ? 25 : 100, max: unit === "%" ? 70 : 500, axis, unit });
  return <div data-testid="group" style={panel.style}>
    <section id="test-panel">Panel content</section>
    <ResizeHandle {...panel.handleProps} label="Resize panel" controls="test-panel" factor={factor} />
    <iframe title="Document" />
  </div>;
}

beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal("PointerEvent", class extends MouseEvent {
    pointerId: number;
    constructor(type: string, init: PointerEventInit = {}) { super(type, init); this.pointerId = init.pointerId ?? 1; }
  });
  Element.prototype.setPointerCapture = vi.fn();
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function measure(width = 240, height = 240) {
  vi.spyOn(document.getElementById("test-panel")!, "getBoundingClientRect").mockReturnValue({ width, height } as DOMRect);
  vi.spyOn(screen.getByTestId("group"), "getBoundingClientRect").mockReturnValue({ width: 1000, height: 800 } as DOMRect);
}

describe("ResizeHandle", () => {
  it("supports keyboard adjustment, bounds, and reset", () => {
    render(<Example />);
    const handle = screen.getByRole("separator", { name: "Resize panel" });
    fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(handle).toHaveAttribute("aria-valuenow", "250");
    fireEvent.keyDown(handle, { key: "End" });
    fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(handle).toHaveAttribute("aria-valuenow", "500");
    fireEvent.keyDown(handle, { key: "Home" });
    expect(handle).toHaveAttribute("aria-valuenow", "100");
    fireEvent.doubleClick(handle);
    expect(handle).toHaveAttribute("aria-valuenow", "240");
  });

  it("drags with pointer capture and shields PDF iframes until release", () => {
    render(<Example />);
    measure();
    const handle = screen.getByRole("separator");
    fireEvent.pointerDown(handle, { clientX: 240, button: 0, pointerId: 9 });
    expect(handle.setPointerCapture).toHaveBeenCalledWith(9);
    expect(document.documentElement.dataset.resizing).toBe("x");
    expect(document.querySelector(".resize-shield")).toBeInTheDocument();
    fireEvent.pointerMove(handle, { clientX: 310, pointerId: 9 });
    expect(screen.getByTestId("group").style.getPropertyValue("--panel-size")).toBe("310px");
    fireEvent.pointerUp(handle, { pointerId: 9 });
    expect(document.documentElement.dataset.resizing).toBeUndefined();
    expect(document.querySelector(".resize-shield")).toBeNull();
  });

  it("resizes proportional columns using actual container dimensions", () => {
    render(<Example unit="%" />);
    measure(400);
    const handle = screen.getByRole("separator");
    fireEvent.pointerDown(handle, { clientX: 400, button: 0 });
    fireEvent.pointerMove(handle, { clientX: 500 });
    expect(handle).toHaveAttribute("aria-valuenow", "50");
    fireEvent.pointerMove(handle, { clientX: 950 });
    expect(handle).toHaveAttribute("aria-valuenow", "70");
    fireEvent.pointerCancel(handle);
    expect(document.documentElement.dataset.resizing).toBeUndefined();
  });

  it("supports a top edge that grows an input upward and cleans up on unmount", () => {
    const { unmount } = render(<Example axis="y" factor={-1} />);
    measure();
    const handle = screen.getByRole("separator");
    expect(handle).toHaveAttribute("aria-orientation", "horizontal");
    fireEvent.pointerDown(handle, { clientY: 300, button: 0 });
    fireEvent.pointerMove(handle, { clientY: 250 });
    expect(handle).toHaveAttribute("aria-valuenow", "290");
    fireEvent.pointerUp(handle);
    fireEvent.keyDown(handle, { key: "ArrowUp" });
    expect(handle).toHaveAttribute("aria-valuenow", "300");
    fireEvent.pointerDown(handle, { clientY: 250, button: 0 });
    unmount();
    expect(document.documentElement.dataset.resizing).toBeUndefined();
  });

  it("restores saved dimensions after remounting", async () => {
    const { unmount } = render(<Example />);
    fireEvent.keyDown(screen.getByRole("separator"), { key: "ArrowRight" });
    unmount();
    render(<Example />);
    await waitFor(() => expect(screen.getByRole("separator")).toHaveAttribute("aria-valuenow", "250"));
  });

  it.each([["NaN", 240], ["Infinity", 240], ["{}", 240], ["", 240], ["99999", 500], ["-1", 100]]) ("validates stored dimensions: %s", async (value, expected) => {
    const read = vi.spyOn(Storage.prototype, "getItem");
    window.localStorage.setItem("scholarmind-layout-test", String(value));
    render(<Example />);
    await waitFor(() => expect(read).toHaveBeenCalledWith("scholarmind-layout-test"));
    expect(screen.getByRole("separator")).toHaveAttribute("aria-valuenow", String(expected));
  });

  it("works when local storage is unavailable", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("Blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("Blocked"); });
    render(<Example />);
    fireEvent.keyDown(screen.getByRole("separator"), { key: "ArrowRight" });
    expect(screen.getByRole("separator")).toHaveAttribute("aria-valuenow", "250");
  });
});
