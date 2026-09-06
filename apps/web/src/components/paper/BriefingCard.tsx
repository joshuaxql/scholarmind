"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ChevronDown,
  Lightbulb,
  LoaderCircle,
  MessageCircleQuestion,
  RotateCcw,
  Sparkles,
} from "lucide-react";
import { getPaperSummary, streamPaperSummary } from "@/lib/api";
import { useI18n } from "@/components/i18n/I18nProvider";
import { MarkdownContent } from "@/components/content/MarkdownContent";
import { ResizeHandle, useResizablePanel } from "@/components/layout/ResizeHandle";
import type { PaperSummary as PaperSummaryData } from "@/types/api";

interface BriefingSection {
  key: "contributions" | "key_findings" | "limitations";
  title: [string, string];
  question: [string, string];
}

const SECTIONS: BriefingSection[] = [
  {
    key: "contributions",
    title: ["Contributions", "主要贡献"],
    question: [
      "Explain each main contribution of this paper in detail.",
      "请逐条详细解释这篇论文的主要贡献。",
    ],
  },
  {
    key: "key_findings",
    title: ["Key findings", "关键发现"],
    question: [
      "What are the key findings of this paper and why do they matter?",
      "这篇论文的关键发现是什么？它们为什么重要？",
    ],
  },
  {
    key: "limitations",
    title: ["Limitations", "局限性"],
    question: [
      "Discuss the limitations of this paper and how they could be addressed.",
      "请讨论这篇论文的局限性以及可能的改进方向。",
    ],
  },
];

const TLDR_QUESTION: [string, string] = [
  "Expand on the summary and walk me through this paper in more detail.",
  "展开这个摘要，更详细地带我过一遍这篇论文。",
];
const BACKGROUND_QUESTION: [string, string] = [
  "What problem does this paper address, and why does it matter?",
  "这篇论文解决的是什么问题？为什么重要？",
];
const METHODOLOGY_QUESTION: [string, string] = [
  "Walk me through the methodology of this paper step by step.",
  "请一步步讲解这篇论文的方法。",
];

function AskButton({ onAsk, question, label }: { onAsk: (question: string) => void; question: [string, string]; label: [string, string] }) {
  const { tr } = useI18n();
  return (
    <button
      type="button"
      className="briefing-ask"
      onClick={() => onAsk(tr(question[0], question[1]))}
      aria-label={tr(label[0], label[1])}
      title={tr(question[0], question[1])}
    >
      <MessageCircleQuestion size={12} />
    </button>
  );
}

export function BriefingCard({ paperId, onAsk }: { paperId: string; onAsk?: (question: string) => void }) {
  const { language, tr } = useI18n();
  const height = useResizablePanel({ storageKey: "briefing", initial: 240, min: 80, max: 700, axis: "y" });
  const [summary, setSummary] = useState<PaperSummaryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(true);
  const busyRef = useRef(false);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const next = await getPaperSummary(paperId, signal);
        setSummary(next);
        setError(null);
      } catch (cause) {
        if (signal?.aborted) return;
        setError(cause instanceof Error ? cause.message : "Failed to load briefing");
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [paperId],
  );

  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => void load(controller.signal), 0);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [load]);

  const generate = useCallback(
    async (refresh: boolean) => {
      if (busyRef.current) return;
      busyRef.current = true;
      setBusy(true);
      setError(null);
      setProgress("");
      try {
        for await (const event of streamPaperSummary(paperId, { language, refresh })) {
          if (event.event === "token" && event.data.text) {
            setProgress((current) => (current + event.data.text!).slice(-120));
          } else if (event.event === "done" && event.data.summary) {
            setSummary(event.data.summary);
          } else if (event.event === "error") {
            throw new Error(event.data.message ?? tr("The briefing could not be generated", "无法生成速览"));
          }
        }
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : tr("The briefing could not be generated", "无法生成速览"));
      } finally {
        busyRef.current = false;
        setBusy(false);
        setProgress("");
      }
    },
    [language, paperId, tr],
  );

  // First visit of a ready paper without a briefing: generate one automatically.
  useEffect(() => {
    if (loading || busyRef.current || summary?.status !== "pending") return;
    const timer = setTimeout(() => void generate(false), 0);
    return () => clearTimeout(timer);
  }, [loading, summary, generate]);

  return (
    <section className="briefing-card" aria-label={tr("Paper briefing", "论文速览")}>
      <header className="briefing-header">
        <button className="briefing-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
          <Sparkles size={15} />
          <span className="briefing-title">{tr("Paper briefing", "论文速览")}</span>
          <ChevronDown size={15} className={`briefing-chevron ${open ? "open" : ""}`} />
        </button>
        {summary?.status === "ready" && (
          <button className="briefing-regenerate" onClick={() => void generate(true)} disabled={busy}>
            <RotateCcw size={13} className={busy ? "spin" : ""} />
            {tr("Regenerate", "重新生成")}
          </button>
        )}
      </header>
      {open && (
        <div style={height.style} className="briefing-body" id="briefing-content">
          {loading && (
            <p className="briefing-hint"><LoaderCircle className="spin" size={14} /> {tr("Loading briefing…", "正在加载速览…")}</p>
          )}
          {!loading && summary?.status === "pending" && busy && (
            <div className="briefing-progress">
              <LoaderCircle className="spin" size={14} />
              <span className="briefing-progress-text">
                {tr("Generating briefing… ", "正在生成速览… ")}{progress && <code>{progress}</code>}
              </span>
            </div>
          )}
          {!loading && summary?.status === "failed" && (
            <div className="briefing-error">
              <p>{summary.error_message ?? tr("The briefing could not be generated.", "速览生成失败。")}</p>
              <button onClick={() => void generate(true)} disabled={busy}>
                <RotateCcw size={13} className={busy ? "spin" : ""} /> {tr("Try again", "重试")}
              </button>
            </div>
          )}
          {error && <p className="briefing-error-text">{error}</p>}
          {summary?.content && (
            <>
              <p className="briefing-tldr">
                <MarkdownContent inline>{summary.content.tldr}</MarkdownContent>
                {onAsk && (
                  <AskButton onAsk={onAsk} question={TLDR_QUESTION} label={["Ask about the summary", "就摘要提问"]} />
                )}
              </p>
              <div className="briefing-grid">
                <div className="briefing-block">
                  <h4>
                    {tr("Background", "研究背景")}
                    {onAsk && (
                      <AskButton onAsk={onAsk} question={BACKGROUND_QUESTION} label={["Ask about the background", "就研究背景提问"]} />
                    )}
                  </h4>
                  <p><MarkdownContent inline>{summary.content.background}</MarkdownContent></p>
                </div>
                <div className="briefing-block">
                  <h4>
                    {tr("Methodology", "方法概述")}
                    {onAsk && (
                      <AskButton onAsk={onAsk} question={METHODOLOGY_QUESTION} label={["Ask about the methodology", "就方法提问"]} />
                    )}
                  </h4>
                  <p><MarkdownContent inline>{summary.content.methodology}</MarkdownContent></p>
                </div>
              </div>
              {SECTIONS.map(({ key, title, question }) => {
                const items = summary.content?.[key] ?? [];
                if (items.length === 0) return null;
                return (
                  <div className="briefing-block" key={key}>
                    <h4>
                      {tr(title[0], title[1])}
                      {onAsk && <AskButton onAsk={onAsk} question={question} label={[`Ask about ${title[0].toLowerCase()}`, `就${title[1]}提问`]} />}
                    </h4>
                    <ul>
                      {items.map((item, index) => <li key={index}><MarkdownContent inline>{item}</MarkdownContent></li>)}
                    </ul>
                  </div>
                );
              })}
              {summary.content.key_terms.length > 0 && (
                <div className="briefing-block">
                  <h4><Lightbulb size={13} /> {tr("Key terms", "关键术语")}</h4>
                  <dl className="briefing-terms">
                    {summary.content.key_terms.map((term) => (
                      <div className="briefing-term" key={term.term}>
                        <dt>
                          <MarkdownContent inline>{term.term}</MarkdownContent>
                          {onAsk && (
                            <AskButton
                              onAsk={onAsk}
                              question={[`Explain the term "${term.term}" in detail.`, `请详细解释术语「${term.term}」。`]} 
                              label={[`Ask about ${term.term}`, `就术语 ${term.term} 提问`]} 
                            />
                          )}
                        </dt>
                        <dd><MarkdownContent inline>{term.definition}</MarkdownContent></dd>
                      </div>
                    ))}
                  </dl>
                </div>
              )}
            </>
          )}
        </div>
      )}
      {open && <ResizeHandle {...height.handleProps} label={tr("Resize briefing and PDF", "调整速览与 PDF 高度")} controls="briefing-content" />}
    </section>
  );
}
