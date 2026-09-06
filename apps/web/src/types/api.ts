export type PaperStatus = "queued" | "downloading" | "parsing" | "indexing" | "ready" | "failed";

export interface EnvironmentField {
  key: string;
  group: string;
  kind: string;
  options: string[];
  minimum: number | null;
  maximum: number | null;
  exclusive_minimum: boolean;
  sensitive: boolean;
  configured: boolean;
  value: string | null;
  in_file: boolean;
}

export interface EnvironmentSettings {
  revision: string;
  restart_required: boolean;
  fields: EnvironmentField[];
}
export type JobStatus = "queued" | "running" | "retrying" | "succeeded" | "failed";
export type JobStage = "queued" | "metadata" | "download" | "parse" | "store" | "index" | "complete";

export interface IngestionJob {
  id: string;
  status: JobStatus;
  stage: JobStage;
  progress: number;
  attempt: number;
  max_attempts: number;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface Paper {
  id: string;
  arxiv_id: string;
  abstract_url: string;
  title: string | null;
  authors: string[];
  abstract: string | null;
  published_at: string | null;
  status: PaperStatus;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  ready_at: string | null;
  latest_job: IngestionJob | null;
}

export interface PaperCreateResponse {
  paper: Paper;
  created: boolean;
}

export interface PaperCollection {
  items: Paper[];
  total: number;
  limit: number;
  offset: number;
}

export interface Citation {
  source_id: string;
  chunk_id: string;
  page_number: number | null;
  section: string | null;
  score: number;
  excerpt: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  pending?: boolean;
  latency_ms?: number | null;
  created_at?: string;
}

export interface Conversation {
  id: string;
  paper_id: string;
  title: string | null;
  messages: ChatMessage[];
  created_at: string;
  updated_at: string;
}

export interface ConversationCollection {
  items: Conversation[];
  total: number;
  limit: number;
  offset: number;
}

export type ResearchStatus = "searched" | "analyzing" | "complete" | "failed";
export type ResearchSort = "relevance" | "submitted_date" | "updated_date";

export interface ResearchSearchInput {
  topic: string;
  categories: string[];
  published_from: string | null;
  published_to: string | null;
  sort: ResearchSort;
  limit: number;
}

export interface ArxivSearchPaper {
  source_id: string;
  arxiv_id: string;
  title: string;
  authors: string[];
  abstract: string;
  published_at: string;
  updated_at: string;
  categories: string[];
  primary_category: string | null;
  abstract_url: string;
  pdf_url: string;
}

export interface ResearchTheme {
  name: string;
  summary: string;
  paper_ids: string[];
}

export interface ResearchTimelineItem {
  period: string;
  development: string;
  paper_ids: string[];
}

export interface ResearchBottleneck {
  title: string;
  description: string;
  evidence_type: "explicit" | "inferred";
  paper_ids: string[];
}

export interface ResearchOpportunity {
  title: string;
  rationale: string;
  paper_ids: string[];
}

export interface ResearchReport {
  overview: string;
  methodology: string;
  themes: ResearchTheme[];
  timeline: ResearchTimelineItem[];
  bottlenecks: ResearchBottleneck[];
  opportunities: ResearchOpportunity[];
}

export interface ResearchSearch {
  id: string;
  topic: string;
  query_expression: string;
  filters: {
    categories?: string[];
    published_from?: string | null;
    published_to?: string | null;
    sort?: ResearchSort;
    limit?: number;
    terms?: string[];
  };
  results: ArxivSearchPaper[];
  report: ResearchReport | null;
  status: ResearchStatus;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  cached: boolean;
}

export interface ResearchCollection {
  items: ResearchSearch[];
  total: number;
  limit: number;
  offset: number;
}

export interface ResearchAnalysisEvent {
  event: "meta" | "token" | "done" | "error";
  data: {
    search_id?: string;
    text?: string;
    terms?: string[];
    search?: ResearchSearch;
    stage?: string;
    report?: ResearchReport;
    code?: string;
    message?: string;
  };
}

export interface ApiErrorPayload {
  error?: {
    code?: string;
    message?: string;
    request_id?: string;
  };
}
