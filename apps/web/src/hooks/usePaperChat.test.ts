import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { deleteConversation, getConversation, listConversations } from "@/lib/api";
import { usePaperChat } from "@/hooks/usePaperChat";
import type { Conversation, ConversationCollection } from "@/types/api";

vi.mock("@/lib/api", () => ({ deleteConversation: vi.fn(), getConversation: vi.fn(), listConversations: vi.fn() }));
const conversation: Conversation = { id: "chat-1", paper_id: "paper-1", title: "Question", messages: [{ id: "message-1", role: "user", content: "Question" }], created_at: "2026-09-05", updated_at: "2026-09-05" };
const collection: ConversationCollection = { items: [conversation], total: 1, limit: 50, offset: 0 };

afterEach(() => vi.unstubAllGlobals());

describe("conversation deletion", () => {
  beforeEach(() => {
    vi.mocked(listConversations).mockReset().mockResolvedValue(collection);
    vi.mocked(deleteConversation).mockReset().mockResolvedValue(undefined);
    vi.mocked(getConversation).mockReset();
  });

  it("clears the active conversation after successful deletion", async () => {
    const { result } = renderHook(() => usePaperChat("paper-1"));
    await waitFor(() => expect(result.current.activeConversationId).toBe("chat-1"));
    await act(() => result.current.removeConversation("chat-1"));
    expect(deleteConversation).toHaveBeenCalledWith("paper-1", "chat-1");
    expect(result.current.messages).toEqual([]);
    expect(result.current.conversations).toEqual([]);
    expect(result.current.activeConversationId).toBeNull();
  });

  it("preserves the active conversation when deletion fails", async () => {
    vi.mocked(deleteConversation).mockRejectedValue(new Error("Offline"));
    const { result } = renderHook(() => usePaperChat("paper-1"));
    await waitFor(() => expect(result.current.activeConversationId).toBe("chat-1"));
    await act(async () => { await expect(result.current.removeConversation("chat-1")).rejects.toThrow("Offline"); });
    expect(result.current.messages).toEqual(conversation.messages);
    expect(result.current.conversations).toEqual([conversation]);
    expect(result.current.deleting).toBe(false);
  });

  it("does not restore deleted history from a late list response", async () => {
    let resolve!: (value: ConversationCollection) => void;
    vi.mocked(listConversations).mockReturnValue(new Promise((done) => { resolve = done; }));
    const { result } = renderHook(() => usePaperChat("paper-1"));
    await waitFor(() => expect(listConversations).toHaveBeenCalled());
    await act(() => result.current.removeConversation("chat-1"));
    await act(async () => resolve({ ...collection, items: [conversation] }));
    expect(result.current.conversations).toEqual([]);
    expect(result.current.messages).toEqual([]);
    expect(result.current.activeConversationId).toBeNull();
  });
  it("reports abrupt EOF while retaining the visible answer", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('event: token\ndata: {"text":"Partial answer"}\n\n')));
    const { result } = renderHook(() => usePaperChat("paper-1"));
    await waitFor(() => expect(result.current.historyLoading).toBe(false));
    await act(() => result.current.send("Question"));
    expect(result.current.error).toContain("before completion");
    expect(result.current.messages.at(-1)?.content).toBe("Partial answer");
    expect(result.current.streaming).toBe(false);
  });

});
