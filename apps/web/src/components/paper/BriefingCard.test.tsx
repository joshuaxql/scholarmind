import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BriefingCard } from "@/components/paper/BriefingCard";
import { generatePaperSummary, getPaperSummary } from "@/lib/api";
import type { PaperSummary } from "@/types/api";

vi.mock("@/lib/api", () => ({
  getPaperSummary: vi.fn(),
  generatePaperSummary: vi.fn(),
}));
vi.mock("@/components/i18n/I18nProvider", () => ({
  useI18n: () => ({ language: "en", tr: (en: string) => en }),
}));

const mockedGet = vi.mocked(getPaperSummary);
const mockedGenerate = vi.mocked(generatePaperSummary);

const readySummary: PaperSummary = {
  paper_id: "paper-1",
  status: "ready",
  language: "en",
  content: {
    tldr: "The paper studies attention scaling.",
    background: "Attention dominates architectures.",
    contributions: ["A new attention variant"],
    methodology: "Convergence proofs and benchmarks.",
    key_findings: ["Scaling helps until saturation"],
    limitations: ["Only English corpora"],
    key_terms: [{ term: "Saturation", definition: "The point where scaling stops helping." }],
  },
  error_code: null,
  error_message: null,
  created_at: "2026-09-06T00:00:00Z",
  updated_at: "2026-09-06T00:00:00Z",
};

const pendingSummary: PaperSummary = {
  paper_id: "paper-1",
  status: "pending",
  language: null,
  content: null,
  error_code: null,
  error_message: null,
  created_at: null,
  updated_at: null,
};

beforeEach(() => {
  mockedGet.mockReset();
  mockedGenerate.mockReset();
});

describe("BriefingCard", () => {
  it("renders a ready briefing with sections and key terms", async () => {
    mockedGet.mockResolvedValue(readySummary);
    render(<BriefingCard paperId="paper-1" />);
    expect(await screen.findByText("The paper studies attention scaling.")).toBeInTheDocument();
    expect(screen.getByText("Contributions")).toBeInTheDocument();
    expect(screen.getByText("A new attention variant")).toBeInTheDocument();
    expect(screen.getByText("Saturation")).toBeInTheDocument();
    expect(mockedGenerate).not.toHaveBeenCalled();
  });

  it("auto-generates a briefing when none exists yet", async () => {
    mockedGet.mockResolvedValue(pendingSummary);
    mockedGenerate.mockResolvedValue(readySummary);
    render(<BriefingCard paperId="paper-1" />);
    await waitFor(() => expect(mockedGenerate).toHaveBeenCalledWith("paper-1", { language: "en", refresh: false }));
    expect(await screen.findByText("The paper studies attention scaling.")).toBeInTheDocument();
  });

  it("collapses and expands the card", async () => {
    mockedGet.mockResolvedValue(readySummary);
    render(<BriefingCard paperId="paper-1" />);
    await screen.findByText("The paper studies attention scaling.");
    fireEvent.click(screen.getByRole("button", { name: /paper briefing/i }));
    expect(screen.queryByText("The paper studies attention scaling.")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /paper briefing/i }));
    expect(screen.getByText("The paper studies attention scaling.")).toBeInTheDocument();
  });

  it("offers retry after a failed generation without faking success", async () => {
    mockedGet.mockResolvedValue({
      ...pendingSummary,
      status: "failed",
      error_code: "briefing_generation_failed",
      error_message: "The model stream was interrupted.",
    });
    mockedGenerate.mockResolvedValue(readySummary);
    render(<BriefingCard paperId="paper-1" />);
    expect(await screen.findByText("The model stream was interrupted.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    await waitFor(() =>
      expect(mockedGenerate).toHaveBeenCalledWith("paper-1", { language: "en", refresh: true }),
    );
    expect(await screen.findByText("The paper studies attention scaling.")).toBeInTheDocument();
  });
});
