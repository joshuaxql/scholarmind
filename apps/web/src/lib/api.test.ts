import { afterEach, describe, expect, it, vi } from "vitest";
import { createPaper, deleteConversation, deleteResearch, paperPdfUrl, removePaperHistory } from "@/lib/api";

afterEach(() => vi.unstubAllGlobals());

describe("web API client", () => {
  it("deletes history through the BFF and accepts empty 204 responses", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(deleteResearch("topic id")).resolves.toBeUndefined();
    await expect(removePaperHistory("paper id")).resolves.toBeUndefined();
    await expect(deleteConversation("paper id", "chat id")).resolves.toBeUndefined();
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/backend/api/v1/research/topic%20id",
      "/api/backend/api/v1/papers/paper%20id/history",
      "/api/backend/api/v1/papers/paper%20id/conversations/chat%20id",
    ]);
    for (const [, options] of fetchMock.mock.calls) expect(options.method).toBe("DELETE");
  });
  it("uses the same-origin BFF instead of exposing backend URLs", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      Response.json({ created: true, paper: { id: "p1" } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await createPaper("2501.06713");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/backend/api/v1/papers",
      expect.objectContaining({ method: "POST", cache: "no-store" }),
    );
    expect(paperPdfUrl("paper id", 4)).toBe(
      "/api/backend/api/v1/papers/paper%20id/pdf#page=4&view=FitH",
    );
  });

  it("preserves structured API errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        Response.json(
          { error: { code: "paper_not_ready", message: "Wait for indexing", request_id: "r1" } },
          { status: 409 },
        ),
      ),
    );
    await expect(createPaper("2501.06713")).rejects.toEqual(
      expect.objectContaining({
        name: "ApiError",
        code: "paper_not_ready",
        status: 409,
        requestId: "r1",
      }),
    );
  });
});
