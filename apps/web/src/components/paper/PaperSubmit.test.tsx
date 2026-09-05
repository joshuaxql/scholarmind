import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PaperSubmit } from "@/components/paper/PaperSubmit";
import { createPaper } from "@/lib/api";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/api", () => ({ createPaper: vi.fn() }));

const mockedCreatePaper = vi.mocked(createPaper);

describe("PaperSubmit", () => {
  beforeEach(() => {
    push.mockReset();
    mockedCreatePaper.mockReset();
  });

  it("creates a paper and navigates to its reading desk", async () => {
    mockedCreatePaper.mockResolvedValue({
      created: true,
      paper: { id: "paper-123" },
    } as Awaited<ReturnType<typeof createPaper>>);
    render(<PaperSubmit />);

    fireEvent.change(screen.getByLabelText("arXiv ID or URL"), { target: { value: "2501.06713" } });
    fireEvent.submit(screen.getByRole("button", { name: "Read paper" }).closest("form")!);

    await waitFor(() => expect(mockedCreatePaper).toHaveBeenCalledWith("2501.06713"));
    expect(push).toHaveBeenCalledWith("/papers/paper-123");
  });

  it("shows a recoverable API error", async () => {
    mockedCreatePaper.mockRejectedValue(new Error("arXiv is unavailable"));
    render(<PaperSubmit />);
    fireEvent.change(screen.getByLabelText("arXiv ID or URL"), { target: { value: "2501.06713" } });
    fireEvent.click(screen.getByRole("button", { name: "Read paper" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("arXiv is unavailable");
    expect(screen.getByRole("button", { name: "Read paper" })).toBeEnabled();
  });
});
