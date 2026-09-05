"use client";

import { Check, CircleDashed, Download, FileScan, Network, Search } from "lucide-react";
import type { Paper } from "@/types/api";
import { useI18n } from "@/components/i18n/I18nProvider";

const ORDER = ["queued", "metadata", "download", "parse", "store", "index", "complete"];

export function ProgressRail({ paper }: { paper: Paper }) {
  const { tr } = useI18n();
  const steps = [
    { stage: "metadata", label: tr("Resolve", "解析"), note: tr("Reading arXiv metadata", "读取 arXiv 元数据"), icon: Search },
    { stage: "download", label: tr("Acquire", "获取"), note: tr("Securing the source PDF", "安全获取源 PDF"), icon: Download },
    { stage: "parse", label: tr("Extract", "提取"), note: tr("Mapping text to pages", "建立正文与页码映射"), icon: FileScan },
    { stage: "index", label: tr("Connect", "索引"), note: tr("Building paper-scoped memory", "构建论文独立记忆"), icon: Network },
  ] as const;
  const currentStage = paper.latest_job?.stage ?? "queued";
  const currentIndex = ORDER.indexOf(currentStage);
  const progress = Math.max(3, paper.latest_job?.progress ?? 3);

  return (
    <section className="processing-card" aria-live="polite">
      <div className="processing-topline">
        <span className="eyebrow">{tr("Preparing your reading desk", "正在准备阅读工作台")}</span>
        <strong>{progress}%</strong>
      </div>
      <div className="progress-track"><i style={{ width: `${progress}%` }} /></div>
      <div className="processing-title">
        <CircleDashed className="spin-slow" size={29} aria-hidden="true" />
        <div>
          <h2>{paper.title ?? `${tr("Resolving", "正在解析")} arXiv:${paper.arxiv_id}`}</h2>
          <p>{tr("This page updates itself. You can leave it open while the paper is indexed.", "页面会自动更新，论文索引期间可以保持此页面打开。")}</p>
        </div>
      </div>
      <ol className="pipeline-steps">
        {steps.map((step) => {
          const index = ORDER.indexOf(step.stage);
          const done = currentIndex > index;
          const active = currentStage === step.stage || (step.stage === "parse" && currentStage === "store");
          const Icon = step.icon;
          return (
            <li key={step.stage} className={done ? "done" : active ? "active" : ""}>
              <span className="pipeline-icon">{done ? <Check size={16} /> : <Icon size={16} />}</span>
              <div><strong>{step.label}</strong><small>{active ? step.note : done ? tr("Complete", "完成") : tr("Waiting", "等待中")}</small></div>
            </li>
          );
        })}
      </ol>
      <p className="processing-footnote">{tr("Each paper receives an isolated retrieval namespace before chat is enabled.", "启用问答前，每篇论文都会获得隔离的检索命名空间。")}</p>
    </section>
  );
}
