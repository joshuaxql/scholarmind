import { readServerEvents } from "@/lib/sse";
import type {
  ApiErrorPayload,
  Conversation,
  ConversationCollection,
  EnvironmentSettings,
  Paper,
  PaperCollection,
  PaperCreateResponse,
  ResearchAnalysisEvent,
  ResearchCollection,
  ResearchSearch,
  ResearchSearchInput,
} from "@/types/api";

const API_ROOT = "/api/backend/api/v1";

export function getEnvironmentSettings(signal?: AbortSignal): Promise<EnvironmentSettings> {
  return request("/settings", { headers: { "X-ScholarMind-Settings": "1" }, signal });
}

export function saveEnvironmentSettings(revision: string, updates: Record<string, string>): Promise<EnvironmentSettings> {
  return request("/settings", { method: "POST", headers: { "X-ScholarMind-Settings": "1" }, body: JSON.stringify({ revision, updates }) });
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code: string,
    public readonly requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function createPaper(arxiv: string): Promise<PaperCreateResponse> {
  return request<PaperCreateResponse>("/papers", {
    method: "POST",
    body: JSON.stringify({ arxiv }),
  });
}

export async function listPapers(limit = 6): Promise<PaperCollection> {
  return request<PaperCollection>(`/papers?limit=${limit}&offset=0`);
}

export async function getPaper(id: string): Promise<Paper> {
  return request<Paper>(`/papers/${encodeURIComponent(id)}`);
}

export async function retryPaper(id: string): Promise<PaperCreateResponse> {
  return request<PaperCreateResponse>(`/papers/${encodeURIComponent(id)}/retry`, { method: "POST" });
}

export async function listConversations(
  paperId: string,
  limit = 50,
): Promise<ConversationCollection> {
  return request<ConversationCollection>(
    `/papers/${encodeURIComponent(paperId)}/conversations?limit=${limit}&offset=0`,
  );
}

export async function getConversation(
  paperId: string,
  conversationId: string,
): Promise<Conversation> {
  return request<Conversation>(
    `/papers/${encodeURIComponent(paperId)}/conversations/${encodeURIComponent(conversationId)}`,
  );
}

export async function searchResearch(input: ResearchSearchInput): Promise<ResearchSearch> {
  return request<ResearchSearch>("/research/search", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function getResearch(id: string): Promise<ResearchSearch> {
  return request<ResearchSearch>(`/research/${encodeURIComponent(id)}`);
}

export async function deleteResearch(id: string): Promise<void> {
  return request<void>(`/research/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function removePaperHistory(id: string): Promise<void> {
  return request<void>(`/papers/${encodeURIComponent(id)}/history`, { method: "DELETE" });
}

export async function deleteConversation(paperId: string, conversationId: string): Promise<void> {
  return request<void>(`/papers/${encodeURIComponent(paperId)}/conversations/${encodeURIComponent(conversationId)}`, { method: "DELETE" });
}

export async function listResearch(limit = 12): Promise<ResearchCollection> {
  return request<ResearchCollection>(`/research?limit=${limit}&offset=0`);
}

export async function* analyzeResearch(
  id: string,
  signal?: AbortSignal,
): AsyncGenerator<ResearchAnalysisEvent> {
  const response = await fetch(
    `${API_ROOT}/research/${encodeURIComponent(id)}/analyze/stream`,
    {
      method: "POST",
      headers: { Accept: "text/event-stream" },
      cache: "no-store",
      signal,
    },
  );
  for await (const event of readServerEvents(response)) {
    yield event as ResearchAnalysisEvent;
  }
}

export function paperPdfUrl(id: string, page?: number): string {
  const base = `${API_ROOT}/papers/${encodeURIComponent(id)}/pdf`;
  return page ? `${base}#page=${page}&view=FitH` : `${base}#view=FitH`;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      Accept: "application/json",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    let payload: ApiErrorPayload = {};
    try {
      payload = (await response.json()) as ApiErrorPayload;
    } catch {
      // Preserve a stable fallback for non-JSON upstream errors.
    }
    throw new ApiError(
      payload.error?.message ?? "The request could not be completed",
      response.status,
      payload.error?.code ?? "request_failed",
      payload.error?.request_id,
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
