"use client";

import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import {
  ArrowUp,
  BookOpenText,
  CircleStop,
  History,
  MessageSquareText,
  Plus,
  Sparkles,
  X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { HistoryActions } from "@/components/history/HistoryActions";
import { usePaperChat } from "@/hooks/usePaperChat";
import { useI18n } from "@/components/i18n/I18nProvider";
import type { Citation } from "@/types/api";

const SUGGESTIONS = [
  ["What is the central contribution?", "这篇论文的核心贡献是什么？"],
  ["Walk me through the methodology.", "请详细解释论文的方法。"],
  ["Which limitations do the authors report?", "作者报告了哪些局限？"],
] as const;

interface ChatPanelProps {
  paperId: string;
  title: string;
  onCitation: (citation: Citation) => void;
  /** Question handed over from the briefing card; the nonce marks each new request. */
  askRequest?: { text: string; nonce: number } | null;
}

export function ChatPanel({ paperId, title, onCitation, askRequest }: ChatPanelProps) {
  const { tr } = useI18n();
  const chat = usePaperChat(paperId);
  const { messages, streaming, error, send, stop } = chat;
  const conversations = chat.conversations ?? [];
  const activeConversationId = chat.activeConversationId ?? null;
  const historyLoading = chat.historyLoading ?? false;
  const selectConversation = chat.selectConversation ?? (() => Promise.resolve());
  const newConversation = chat.newConversation ?? (() => undefined);
  const [query, setQuery] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const handledAskNonce = useRef(0);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (!askRequest || askRequest.nonce === handledAskNonce.current) return;
    const timer = setTimeout(() => {
      handledAskNonce.current = askRequest.nonce;
      if (!streaming && !chat.deleting) void send(askRequest.text);
    }, 0);
    return () => clearTimeout(timer);
  }, [askRequest, streaming, chat.deleting, send]);

  function submit(event?: FormEvent) {
    event?.preventDefault();
    const next = query.trim();
    if (!next || streaming || chat.deleting) return;
    setQuery("");
    void send(next);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <section className="chat-pane" aria-label={tr("Ask this paper", "向论文提问")}>
      <div className="pane-toolbar chat-toolbar">
        <div className="pane-label"><MessageSquareText size={15} /><span>{tr("Conversation", "论文对话")}</span></div>
        <div className="chat-toolbar-actions">
          <button type="button" onClick={() => setHistoryOpen((value) => !value)} aria-label={tr("Conversation history", "历史会话")}>
            <History size={14} /><span>{tr("History", "历史")}</span>
          </button>
          <span className="grounded-indicator"><i /> {tr("Grounded", "基于证据")}</span>
        </div>
      </div>
      {historyOpen && (
        <aside className="chat-history" aria-label={tr("Conversation history", "历史会话")}>
          <header>
            <div><span>{tr("Saved notebook", "已保存笔记")}</span><strong>{conversations.length} {tr("conversations", "个会话")}</strong></div>
            <button type="button" onClick={() => setHistoryOpen(false)} aria-label={tr("Close history", "关闭历史")}><X size={15} /></button>
          </header>
          <button className="new-conversation" type="button" disabled={streaming || chat.deleting} onClick={() => { newConversation(); setHistoryOpen(false); }}>
            <Plus size={14} /> {tr("New conversation", "新建会话")}
          </button>
          <div className="chat-history-list">
            {historyLoading && <p>{tr("Loading history…", "正在加载历史…")}</p>}
            {!historyLoading && conversations.length === 0 && <p>{tr("No saved conversations yet.", "暂无历史会话。")}</p>}
            {conversations.map((conversation) => (
              <HistoryActions key={conversation.id} title={conversation.title ?? tr("Untitled conversation", "未命名会话")} onDelete={() => chat.removeConversation(conversation.id)} disabled={streaming || historyLoading || chat.deleting}>
              <button
                disabled={streaming || chat.deleting}
                type="button"
                className={conversation.id === activeConversationId ? "active" : ""}
                onClick={() => { void selectConversation(conversation.id); setHistoryOpen(false); }}
              >
                <span>{conversation.title ?? tr("Untitled conversation", "未命名会话")}</span>
                <small>{conversation.messages.length} {tr("messages", "条消息")} · {formatConversationDate(conversation.updated_at)}</small>
              </button>
              </HistoryActions>
            ))}
          </div>
        </aside>
      )}
      <div className="chat-scroll" ref={scrollRef}>
        {!messages.length ? (
          <div className="chat-empty">
            <span className="chat-orbit" aria-hidden="true"><BookOpenText size={28} /></span>
            <h2>{tr("Let’s understand this paper", "一起读懂这篇论文")}</h2>
            <p>{tr("Ask about", "围绕")} <em>{title}</em>{tr(". Follow each citation back to the original page.", "提问，点击引用即可查看原文页码。")}</p>
            <div className="suggestion-list">
              {SUGGESTIONS.map(([english, chinese], index) => {
                const suggestion = tr(english, chinese);
                return (
                <button key={english} type="button" disabled={chat.deleting} onClick={() => void send(suggestion)}>
                  <span>0{index + 1}</span>{suggestion}
                </button>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="message-list">
            {messages.map((message) => (
              <article key={message.id} className={`message message-${message.role}`}>
                <div className="message-author">
                  {message.role === "assistant" ? <Sparkles size={14} /> : null}
                  {message.role === "assistant" ? "ScholarMind" : tr("You", "你")}
                </div>
                <div className="message-content">
                  {message.content ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown> : <span className="thinking-line">{tr("Reading the relevant passages", "正在阅读相关段落")}</span>}
                  {message.pending && message.content && <i className="stream-caret" />}
                </div>
                {message.citations && message.citations.length > 0 && (
                  <div className="citation-strip" aria-label={tr("Answer sources", "回答来源")}>
                    {message.citations.map((citation) => (
                      <button key={citation.chunk_id} type="button" onClick={() => onCitation(citation)} title={citation.excerpt}>
                        <span>{citation.source_id}</span>
                        {citation.page_number ? `p. ${citation.page_number}` : citation.section ?? tr("source", "来源")}
                      </button>
                    ))}
                  </div>
                )}
              </article>
            ))}
            {error && <p className="chat-error" role="alert">{error}</p>}
          </div>
        )}
      </div>
      <form className="chat-composer" onSubmit={submit}>
        <textarea
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={handleKeyDown}
          rows={2}
          maxLength={4000}
          placeholder={tr("Ask about methods, findings, or a specific claim…", "询问方法、发现或具体论点…")}
          aria-label={tr("Question about this paper", "关于这篇论文的问题")}
        />
        <div className="composer-foot">
          <span>{tr("Answers cite retrieved passages", "回答将引用检索到的段落")}</span>
          {streaming ? (
            <button className="send-button stop-button" type="button" onClick={stop} aria-label={tr("Stop answer", "停止回答")}><CircleStop size={17} /></button>
          ) : (
            <button className="send-button" type="submit" disabled={!query.trim() || chat.deleting} aria-label={tr("Send question", "发送问题")}><ArrowUp size={18} /></button>
          )}
        </div>
      </form>
    </section>
  );
}

function formatConversationDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(
    new Date(value),
  );
}
