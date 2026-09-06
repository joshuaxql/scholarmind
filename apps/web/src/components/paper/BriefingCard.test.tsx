import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BriefingCard } from "@/components/paper/BriefingCard";
import { getPaperSummary, streamPaperSummary } from "@/lib/api";
import type { PaperSummary, PaperSummaryStreamEvent } from "@/types/api";

vi.mock("@/lib/api", () => ({
  getPaperSummary: vi.fn(),
  streamPaperSummary: vi.fn(),
}));
vi.mock("@/components/i18n/I18nProvider", () => ({
  useI18n: () => ({ language: "en", tr: (en: string) => en }),
}));

const mockedGet = vi.mocked(getPaperSummary);
const mockedStream = vi.mocked(streamPaperSummary);

async function* streamOf(events: PaperSummaryStreamEvent[]) {
  for (const event of events) yield event;
}

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
  mockedStream.mockReset();
});

describe("BriefingCard", () => {
  it("renders a ready briefing without regenerating", async () => {
    mockedGet.mockResolvedValue(readySummary);
    render(<BriefingCard paperId="paper-1" />);
    expect(await screen.findByText("The paper studies attention scaling.")).toBeInTheDocument();
    expect(screen.getByText("Contributions")).toBeInTheDocument();
    expect(screen.getByText("A new attention variant")).toBeInTheDocument();
    expect(screen.getByText("Saturation")).toBeInTheDocument();
    expect(mockedStream).not.toHaveBeenCalled();
  });

  it("auto-generates a briefing via stream when none exists yet", async () => {
    mockedGet.mockResolvedValue(pendingSummary);
    mockedStream.mockReturnValue(
      streamOf([
        { event: "meta", data: { stage: "generating" } },
        { event: "token", data: { text: '{"tldr":' } },
        { event: "done", data: { summary: readySummary } },
      ]),
    );
    render(<BriefingCard paperId="paper-1" />);
    await waitFor(() =>
      expect(mockedStream).toHaveBeenCalledWith("paper-1", { language: "en", refresh: false }),
    );
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
    mockedStream.mockReturnValue(
      streamOf([{ event: "done", data: { summary: readySummary } }]),
    );
    render(<BriefingCard paperId="paper-1" />);
    expect(await screen.findByText("The model stream was interrupted.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    await waitFor(() =>
      expect(mockedStream).toHaveBeenCalledWith("paper-1", { language: "en", refresh: true }),
    );
    expect(await screen.findByText("The paper studies attention scaling.")).toBeInTheDocument();
  });

  it("shows streamed progress tokens while generating", async () => {
    mockedGet.mockResolvedValue(pendingSummary);
    let releaseStream: (() => void) | undefined;
    async function* controlled(): AsyncGenerator<PaperSummaryStreamEvent> {
      yield { event: "meta", data: { stage: "generating" } };
      yield { event: "token", data: { text: "drafting the overview" } };
      // Hold the stream open so the busy state persists for assertion.
      await new Promise<void>((resolve) => {
        releaseStream = resolve;
      });
    }
    mockedStream.mockReturnValue(controlled());
    render(<BriefingCard paperId="paper-1" />);
    expect(await screen.findByText(/drafting the overview/)).toBeInTheDocument();
    releaseStream?.();
  });

  it("hands a section question over to the chat via onAsk", async () => {
    mockedGet.mockResolvedValue(readySummary);
    const onAsk = vi.fn();
    render(<BriefingCard paperId="paper-1" onAsk={onAsk} />);
    await screen.findByText("The paper studies attention scaling.");
    fireEvent.click(screen.getByRole("button", { name: /ask about the methodology/i }));
    expect(onAsk).toHaveBeenCalledWith(
      "Walk me through the methodology of this paper step by step.",
    );
  });

  it("hands a key term question over to the chat via onAsk", async () => {
    mockedGet.mockResolvedValue(readySummary);
    const onAsk = vi.fn();
    render(<BriefingCard paperId="paper-1" onAsk={onAsk} />);
    await screen.findByText("Saturation");
    fireEvent.click(screen.getByRole("button", { name: /ask about saturation/i }));
    expect(onAsk).toHaveBeenCalledWith('Explain the term "Saturation" in detail.');
  });
});
