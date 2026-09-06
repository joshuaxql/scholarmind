import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ResearchDesk } from "@/components/research/ResearchDesk";
import { I18nProvider, LanguageToggle } from "@/components/i18n/I18nProvider";
import { analyzeResearch, createPaper, getResearch, searchResearch } from "@/lib/api";
import type { ResearchSearch } from "@/types/api";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/api", () => ({
  searchResearch: vi.fn(),
  createPaper: vi.fn(),
  analyzeResearch: vi.fn(),
  getResearch: vi.fn(),
}));

const mockedSearch = vi.mocked(searchResearch);
const mockedGetResearch = vi.mocked(getResearch);

const result: ResearchSearch = {
  id: "research-1",
  topic: "multimodal RAG",
  query_expression: '(all:"multimodal RAG")',
  filters: { terms: ["multimodal RAG"], categories: ["cs.AI"], limit: 20 },
  results: [
    {
      source_id: "P1",
      arxiv_id: "2501.06713v1",
      title: "A grounded multimodal system",
      authors: ["Ada Researcher"],
      abstract: "We study grounded multimodal retrieval.",
      published_at: "2025-01-12T00:00:00Z",
      updated_at: "2025-01-13T00:00:00Z",
      categories: ["cs.AI"],
      primary_category: "cs.AI",
      abstract_url: "https://arxiv.org/abs/2501.06713v1",
      pdf_url: "https://arxiv.org/pdf/2501.06713v1.pdf",
    },
  ],
  report: {
    overview: "The field is moving toward grounded multimodal evidence.",
    methodology: "This review uses one arXiv abstract.",
    themes: [{ name: "Grounding", summary: "Evidence alignment is central.", paper_ids: ["P1"] }],
    timeline: [{ period: "2025", development: "Grounded systems emerged.", paper_ids: ["P1"] }],
    bottlenecks: [{ title: "Evaluation", description: "Benchmarks remain narrow.", evidence_type: "inferred", paper_ids: ["P1"] }],
    opportunities: [{ title: "Better evidence", rationale: "Broader evaluation is needed.", paper_ids: ["P1"] }],
  },
  status: "complete",
  error_code: null,
  error_message: null,
  created_at: "2025-01-14T00:00:00Z",
  updated_at: "2025-01-14T00:00:00Z",
  cached: false,
};

describe("ResearchDesk", () => {
  beforeEach(() => {
    push.mockReset();
    mockedSearch.mockReset();
    mockedGetResearch.mockReset();
    vi.mocked(createPaper).mockReset();
    vi.mocked(analyzeResearch).mockReset();
    window.localStorage.clear();
  });

  it("restores a previous field map", async () => {
    mockedGetResearch.mockResolvedValue(result);
    render(<ResearchDesk searchId="research-1" />);

    expect(await screen.findByText("A grounded multimodal system")).toBeInTheDocument();
    expect(mockedGetResearch).toHaveBeenCalledWith("research-1");
    expect(screen.getByLabelText("Research topic")).toHaveValue("multimodal RAG");
    expect(mockedSearch).not.toHaveBeenCalled();
  });

  it("searches a topic and renders a cited field report", async () => {
    mockedSearch.mockResolvedValue(result);
    render(<ResearchDesk />);

    fireEvent.change(screen.getByLabelText("Research topic"), { target: { value: "multimodal RAG" } });
    fireEvent.click(screen.getByRole("button", { name: /Filters/ }));
    fireEvent.click(screen.getByRole("button", { name: "cs.AI" }));
    fireEvent.click(screen.getByRole("button", { name: "Explore topic" }));

    await waitFor(() => expect(mockedSearch).toHaveBeenCalledWith(
      expect.objectContaining({ topic: "multimodal RAG", categories: ["cs.AI"], limit: 20 }),
      expect.any(AbortSignal), expect.any(Function),
    ));
    expect(await screen.findByText("A grounded multimodal system")).toBeInTheDocument();
    expect(screen.getByText("The field is moving toward grounded multimodal evidence.")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "[P1]" }).length).toBeGreaterThan(0);
  });

  it("opens a source paper in reading mode", async () => {
    mockedGetResearch.mockResolvedValue(result);
    vi.mocked(createPaper).mockResolvedValue({ created: true, paper: { id: "paper-1" } } as Awaited<ReturnType<typeof createPaper>>);
    render(<ResearchDesk searchId="research-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Read closely" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/papers/paper-1"));
    expect(createPaper).toHaveBeenCalledWith("2501.06713v1");
  });

  it("can finish a saved exploration that has no report", async () => {
    mockedGetResearch.mockResolvedValue({ ...result, report: null, status: "failed" });
    vi.mocked(analyzeResearch).mockImplementation(async function* () {
      yield { event: "done", data: { report: result.report! } };
    });
    render(<ResearchDesk searchId="research-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Generate report" }));
    expect(await screen.findByText(result.report!.overview)).toBeInTheDocument();
    expect(analyzeResearch).toHaveBeenCalledWith("research-1", expect.any(AbortSignal));
    expect(mockedSearch).not.toHaveBeenCalled();
  });

  it("renders model text before completion and preserves an interrupted draft", async () => {
    mockedGetResearch.mockResolvedValue({ ...result, report: null, status: "searched" });
    vi.mocked(analyzeResearch).mockImplementation(async function* (_id, signal) {
      yield { event: "token", data: { text: '{"overview":"Visible before completion' } };
      await new Promise<void>((resolve) => signal!.addEventListener("abort", () => resolve(), { once: true }));
    });
    render(<ResearchDesk searchId="research-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Generate report" }));
    expect(await screen.findByText("Visible before completion")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "[P1]" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stop generation" }));
    expect(vi.mocked(analyzeResearch).mock.calls[0][1]!.aborted).toBe(true);
    expect(await screen.findByRole("button", { name: "Generate report" })).toBeEnabled();
    expect(screen.getByText("Visible before completion")).toBeInTheDocument();
    expect(screen.getByText(/Incomplete draft/)).toBeInTheDocument();
    expect(mockedSearch).not.toHaveBeenCalled();
  });

  it("streams search phrases and cancels topic preparation", async () => {
    mockedSearch.mockImplementation(async (_input, signal, progress) => {
      progress?.({ event: "token", data: { stage: "planning", text: '{"terms":["embodied planning' } });
      return new Promise((_resolve, reject) => signal!.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError"))));
    });
    render(<ResearchDesk />);
    fireEvent.change(screen.getByLabelText("Research topic"), { target: { value: "Embodied" } });
    fireEvent.click(screen.getByRole("button", { name: "Explore topic" }));
    expect(await screen.findByText("embodied planning")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stop generation" }));
    expect(mockedSearch.mock.calls[0][1]!.aborted).toBe(true);
    expect(screen.getByRole("button", { name: "Explore topic" })).toBeEnabled();
  });

  it("explains an exhausted model budget without treating it as a completed report", async () => {
    mockedGetResearch.mockResolvedValue({ ...result, report: null, status: "searched" });
    vi.mocked(analyzeResearch).mockImplementation(async function* () {
      yield { event: "error", data: { code: "model_output_limit", message: "Length limit" } };
    });
    render(<ResearchDesk searchId="research-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Generate report" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("LLM_MAX_OUTPUT_TOKENS");
    expect(screen.getByRole("button", { name: "Generate report" })).toBeEnabled();
    expect(screen.queryByText(result.report!.overview)).not.toBeInTheDocument();
  });

  it("keeps a changed topic when switching interface language", async () => {
    mockedGetResearch.mockResolvedValue(result);
    render(<I18nProvider><LanguageToggle /><ResearchDesk searchId="research-1" /></I18nProvider>);
    await screen.findByText(result.report!.overview);
    fireEvent.change(screen.getByLabelText("Research topic"), { target: { value: "New topic" } });
    fireEvent.click(screen.getByRole("button", { name: "中" }));
    expect(await screen.findByLabelText("研究话题")).toHaveValue("New topic");
    expect(mockedGetResearch).toHaveBeenCalledTimes(1);
  });

  it("shows a history loading error without starting a new search", async () => {
    mockedGetResearch.mockRejectedValue(new Error("Exploration not found"));
    render(<ResearchDesk searchId="missing" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Exploration not found");
    expect(screen.getByLabelText("Research topic")).toBeEnabled();
    expect(mockedSearch).not.toHaveBeenCalled();
  });
});
