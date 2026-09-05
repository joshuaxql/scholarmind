"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { deleteConversation, listConversations, getConversation } from "@/lib/api";
import { readServerEvents } from "@/lib/sse";
import type { ChatMessage, Citation, Conversation } from "@/types/api";

interface MetaEvent {
  conversation_id: string;
  citations: Citation[];
}

export function usePaperChat(paperId: string) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const deletedIds = useRef(new Set<string>());
  const deletingRef = useRef(false);
  const [deleting, setDeleting] = useState(false);
  const conversationId = useRef<string | null>(null);
  const abortController = useRef<AbortController | null>(null);

  const refreshHistory = useCallback(async (restoreLatest = false) => {
    try {
      const collection = await listConversations(paperId);
      const items = collection.items.filter((item) => !deletedIds.current.has(item.id));
      setConversations(items);
      if (restoreLatest && !conversationId.current && items[0]) {
        const latest = items[0];
        conversationId.current = latest.id;
        setActiveConversationId(latest.id);
        setMessages(latest.messages);
      }
    } catch (cause) {
      if (restoreLatest) {
        setError(cause instanceof Error ? cause.message : "Unable to load conversation history");
      }
    } finally {
      setHistoryLoading(false);
    }
  }, [paperId]);

  useEffect(() => {
    conversationId.current = null;
    const timer = window.setTimeout(() => {
      setMessages([]);
      setConversations([]);
      setActiveConversationId(null);
      setHistoryLoading(true);
      void refreshHistory(true);
    }, 0);
    return () => {
      window.clearTimeout(timer);
      abortController.current?.abort();
    };
  }, [paperId, refreshHistory]);

  const selectConversation = useCallback(async (nextId: string) => {
    if (streaming || deletingRef.current || nextId === conversationId.current) return;
    setHistoryLoading(true);
    setError(null);
    try {
      const conversation = await getConversation(paperId, nextId);
      if (deletedIds.current.has(conversation.id)) return;
      conversationId.current = conversation.id;
      setActiveConversationId(conversation.id);
      setMessages(conversation.messages);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to restore this conversation");
    } finally {
      setHistoryLoading(false);
    }
  }, [paperId, streaming]);

  const newConversation = useCallback(() => {
    if (streaming || deletingRef.current) return;
    conversationId.current = null;
    setActiveConversationId(null);
    setMessages([]);
    setError(null);
  }, [streaming]);

  const send = useCallback(
    async (query: string) => {
      const trimmed = query.trim();
      if (!trimmed || streaming || deletingRef.current) return;
      const userId = crypto.randomUUID();
      const assistantId = crypto.randomUUID();
      setMessages((current) => [
        ...current,
        { id: userId, role: "user", content: trimmed },
        { id: assistantId, role: "assistant", content: "", pending: true },
      ]);
      setStreaming(true);
      setError(null);
      abortController.current = new AbortController();

      try {
        const response = await fetch(`/api/backend/api/v1/papers/${encodeURIComponent(paperId)}/chat/stream`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
          body: JSON.stringify({ query: trimmed, conversation_id: conversationId.current }),
          signal: abortController.current.signal,
        });
        for await (const event of readServerEvents(response)) {
          if (event.event === "meta") {
            const meta = event.data as MetaEvent;
            conversationId.current = meta.conversation_id;
            setActiveConversationId(meta.conversation_id);
            setMessages((current) =>
              current.map((message) =>
                message.id === assistantId ? { ...message, citations: meta.citations } : message,
              ),
            );
          }
          if (event.event === "token") {
            const token = event.data as { text: string };
            setMessages((current) =>
              current.map((message) =>
                message.id === assistantId
                  ? { ...message, content: message.content + token.text }
                  : message,
              ),
            );
          }
          if (event.event === "error") {
            const streamError = event.data as { message: string };
            throw new Error(streamError.message);
          }
        }
        setMessages((current) =>
          current.map((message) =>
            message.id === assistantId ? { ...message, pending: false } : message,
          ),
        );
      } catch (cause) {
        if ((cause as Error).name === "AbortError") {
          setMessages((current) =>
            current.flatMap((item) => {
              if (item.id !== assistantId) return [item];
              return item.content ? [{ ...item, pending: false }] : [];
            }),
          );
        } else {
          const message = cause instanceof Error ? cause.message : "The answer stream stopped";
          setError(message);
          setMessages((current) =>
            current.map((item) =>
              item.id === assistantId
                ? { ...item, content: item.content || message, pending: false }
                : item,
            ),
          );
        }
      } finally {
        setStreaming(false);
        abortController.current = null;
        await refreshHistory(false);
      }
    },
    [paperId, refreshHistory, streaming],
  );

  const removeConversation = useCallback(async (id: string) => {
    if (streaming || deletingRef.current) return;
    deletingRef.current = true;
    setDeleting(true);
    try {
      await deleteConversation(paperId, id);
      deletedIds.current.add(id);
      setConversations((items) => items.filter((item) => item.id !== id));
      if (conversationId.current === id) {
        conversationId.current = null;
        setActiveConversationId(null);
        setMessages([]);
        setError(null);
      }
    } finally {
      deletingRef.current = false;
      setDeleting(false);
    }
  }, [paperId, streaming]);

  const stop = useCallback(() => abortController.current?.abort(), []);
  return {
    messages,
    conversations,
    activeConversationId,
    streaming,
    historyLoading,
    deleting,
    removeConversation,
    error,
    send,
    stop,
    selectConversation,
    newConversation,
  };
}
