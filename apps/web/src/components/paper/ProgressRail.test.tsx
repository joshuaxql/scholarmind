import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ProgressRail } from "@/components/paper/ProgressRail";
import type { Paper } from "@/types/api";

const paper = {
  id: "paper",
  arxiv_id: "2501.06713",
  abstract_url: "https://arxiv.org/abs/2501.06713",
  title: "A grounded paper",
  authors: [],
  abstract: null,
  published_at: null,
  status: "parsing",
  error_code: null,
  error_message: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  ready_at: null,
  latest_job: {
    id: "job",
    status: "running",
    stage: "parse",
    progress: 48,
    attempt: 1,
    max_attempts: 3,
    error_code: null,
    error_message: null,
    created_at: "2026-01-01T00:00:00Z",
    started_at: "2026-01-01T00:00:00Z",
    finished_at: null,
  },
} satisfies Paper;

describe("ProgressRail", () => {
  it("renders real backend stage and progress", () => {
    render(<ProgressRail paper={paper} />);
    expect(screen.getByText("48%")).toBeInTheDocument();
    expect(screen.getByText("Mapping text to pages")).toBeInTheDocument();
    expect(screen.getAllByText("Complete")).toHaveLength(2);
    expect(screen.getByText(/isolated retrieval namespace/i)).toBeInTheDocument();
  });
});
