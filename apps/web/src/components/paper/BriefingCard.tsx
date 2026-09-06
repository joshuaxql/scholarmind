"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronDown, Lightbulb, LoaderCircle, RotateCcw, Sparkles } from "lucide-react";
import { generatePaperSummary, getPaperSummary } from "@/lib/api";
import { useI18n } from "@/components/i18n/I18nProvider";
import type { PaperSummary as PaperSummaryData } from "@/types/api";

interface BriefingSection {
  key: "contributions" | "key_findings" | "limitations";
  title: [string, string];
}

const SECTIONS: BriefingSection[] = [
  { key: "contributions", title: ["Contributions", "主要贡献"] },
  { key: "key_findings", title: ["Key findings", "关键发现"] },
  { key: "limitations", title: ["Limitations", "局限性"] },
];

export function BriefingCard({ paperId }: { paperId: string }) {
  const { language, tr } = useI18n();
  const [summary, setSummary] = useState<PaperSummaryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(true);

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
      setBusy(true);
      setError(null);
      try {
        setSummary(await generatePaperSummary(paperId, { language, refresh }));
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : tr("The briefing could not be generated", "无法生成速览"));
      } finally {
        setBusy(false);
      }
    },
    [language, paperId, tr],
  );

  // First visit of a ready paper without a briefing: generate one automatically.
  useEffect(() => {
    if (loading || busy || summary?.status !== "pending") return;
    const timer = setTimeout(() => void generate(false), 0);
    return () => clearTimeout(timer);
  }, [loading, summary, busy, generate]);

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
        <div className="briefing-body">
          {loading && (
            <p className="briefing-hint"><LoaderCircle className="spin" size={14} /> {tr("Loading briefing…", "正在加载速览…")}</p>
          )}
          {!loading && summary?.status === "pending" && busy && (
            <p className="briefing-hint"><LoaderCircle className="spin" size={14} /> {tr("Generating briefing…", "正在生成速览…")}</p>
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
              <p className="briefing-tldr">{summary.content.tldr}</p>
              <div className="briefing-grid">
                <div className="briefing-block">
                  <h4>{tr("Background", "研究背景")}</h4>
                  <p>{summary.content.background}</p>
                </div>
                <div className="briefing-block">
                  <h4>{tr("Methodology", "方法概述")}</h4>
                  <p>{summary.content.methodology}</p>
                </div>
              </div>
              {SECTIONS.map(({ key, title }) => {
                const items = summary.content?.[key] ?? [];
                if (items.length === 0) return null;
                return (
                  <div className="briefing-block" key={key}>
                    <h4>{tr(title[0], title[1])}</h4>
                    <ul>
                      {items.map((item, index) => <li key={index}>{item}</li>)}
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
                        <dt>{term.term}</dt>
                        <dd>{term.definition}</dd>
                      </div>
                    ))}
                  </dl>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}
