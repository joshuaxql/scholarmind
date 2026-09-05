"use client";

import Link from "next/link";
import { AlertTriangle, ArrowLeft, CalendarDays, ExternalLink, LoaderCircle, RotateCcw } from "lucide-react";
import { ProgressRail } from "@/components/paper/ProgressRail";
import { ReaderWorkspace } from "@/components/paper/ReaderWorkspace";
import { retryPaper } from "@/lib/api";
import { usePaper } from "@/hooks/usePaper";
import { useState } from "react";
import { useI18n } from "@/components/i18n/I18nProvider";
import type { PaperStatus } from "@/types/api";

export function PaperScreen({ paperId }: { paperId: string }) {
  const { language, tr } = useI18n();
  const { paper, error, loading, refresh } = usePaper(paperId);
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);

  async function retry() {
    setRetrying(true);
    setRetryError(null);
    try {
      await retryPaper(paperId);
      await refresh();
    } catch (cause) {
      setRetryError(cause instanceof Error ? cause.message : tr("The retry could not be queued", "无法提交重试任务"));
    } finally {
      setRetrying(false);
    }
  }

  if (loading) return <div className="screen-state"><LoaderCircle className="spin" /><p>{tr("Opening the reading desk…", "正在打开阅读工作台…")}</p></div>;
  if (error || !paper) return (
    <div className="screen-state screen-error"><AlertTriangle /><h1>{tr("We could not open this paper.", "无法打开这篇论文。")}</h1><p>{error}</p><Link href="/">{tr("Return to the library", "返回论文库")}</Link></div>
  );

  const processing = !["ready", "failed"].includes(paper.status);
  return (
    <main className={`paper-screen ${paper.status === "ready" ? "paper-ready" : ""}`}>
      <header className="paper-header">
        <Link href="/" className="back-link" aria-label={tr("Back to library", "返回论文库")}><ArrowLeft size={17} /></Link>
        <div className="paper-identity">
          <div className="paper-meta-line">
            <span>arXiv:{paper.arxiv_id}</span>
            {paper.published_at && <span><CalendarDays size={12} /> {new Intl.DateTimeFormat(language === "zh" ? "zh-CN" : "en", { year: "numeric", month: "short" }).format(new Date(paper.published_at))}</span>}
            <span className={`status-dot status-${paper.status}`}>{paperStatusLabel(paper.status, language)}</span>
          </div>
          <h1>{paper.title ?? (processing ? tr("Preparing paper metadata…", "正在准备论文元数据…") : `arXiv:${paper.arxiv_id}`)}</h1>
          {paper.authors.length > 0 && <p>{paper.authors.join(" · ")}</p>}
        </div>
        <a className="arxiv-link" href={paper.abstract_url} target="_blank" rel="noreferrer"><span>arXiv</span><ExternalLink size={14} /></a>
      </header>

      {processing && <div className="processing-wrap"><ProgressRail paper={paper} /></div>}
      {paper.status === "failed" && (
        <section className="failed-card">
          <AlertTriangle size={30} />
          <div><span className="eyebrow">{tr("Ingestion stopped", "摄取已停止")}</span><h2>{tr("The paper could not be prepared.", "无法完成论文处理。")}</h2><p>{retryError ?? paper.error_message ?? tr("An upstream service rejected the job.", "上游服务拒绝了任务。")}</p></div>
          <button onClick={() => void retry()} disabled={retrying}><RotateCcw className={retrying ? "spin" : ""} size={16} /> {tr("Try again", "重试")}</button>
        </section>
      )}
      {paper.status === "ready" && <ReaderWorkspace paper={paper} />}
    </main>
  );
}

function paperStatusLabel(status: PaperStatus, language: "en" | "zh"): string {
  if (language === "en") return status;
  return {
    queued: "排队中",
    downloading: "下载中",
    parsing: "解析中",
    indexing: "索引中",
    ready: "已就绪",
    failed: "失败",
  }[status];
}
