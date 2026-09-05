"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, FileText } from "lucide-react";
import { useWorkspace } from "@/components/layout/WorkspaceShell";
import { listPapers } from "@/lib/api";
import type { Paper, PaperStatus } from "@/types/api";
import { useI18n } from "@/components/i18n/I18nProvider";

export function RecentPapers() {
  const { historyRevision } = useWorkspace();
  const { language, tr } = useI18n();
  const [papers, setPapers] = useState<Paper[]>([]);

  useEffect(() => {
    let active = true;
    void listPapers(4)
      .then((collection) => {
        if (active) setPapers(collection.items);
      })
      .catch(() => undefined);
    return () => { active = false; };
  }, [historyRevision]);

  if (!papers.length) return null;

  return (
    <section className="recent-papers" aria-labelledby="recent-heading">
      <div className="section-kicker">
        <h2 id="recent-heading">{tr("Continue reading", "继续阅读")}</h2>
      </div>
      <div className="recent-list">
        {papers.map((paper) => (
          <Link key={paper.id} className="recent-row" href={`/papers/${paper.id}`}>
            <FileText size={17} aria-hidden="true" />
            <span className="recent-copy">
              <strong>{paper.title ?? `arXiv:${paper.arxiv_id}`}</strong>
              <small>arXiv:{paper.arxiv_id}</small>
            </span>
            <span className={`status-dot status-${paper.status}`}>{paperStatusLabel(paper.status, language)}</span>
            <ArrowRight size={16} aria-hidden="true" />
          </Link>
        ))}
      </div>
    </section>
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
