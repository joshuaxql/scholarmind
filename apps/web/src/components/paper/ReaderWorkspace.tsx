"use client";

import { useState } from "react";
import { BookOpen, MessagesSquare } from "lucide-react";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { PdfPane } from "@/components/paper/PdfPane";
import type { Citation, Paper } from "@/types/api";
import { useI18n } from "@/components/i18n/I18nProvider";

export function ReaderWorkspace({ paper }: { paper: Paper }) {
  const { tr } = useI18n();
  const [page, setPage] = useState<number | null>(null);
  const [mobilePane, setMobilePane] = useState<"paper" | "chat">("chat");
  const title = paper.title ?? `arXiv:${paper.arxiv_id}`;

  function openCitation(citation: Citation) {
    if (citation.page_number) setPage(citation.page_number);
    setMobilePane("paper");
  }

  return (
    <div className="workspace-shell">
      <nav className="mobile-pane-switch" aria-label={tr("Workspace panel", "工作区面板")}>
        <button aria-pressed={mobilePane === "paper"} className={mobilePane === "paper" ? "active" : ""} onClick={() => setMobilePane("paper")}><BookOpen size={16} /> {tr("Paper", "论文")}</button>
        <button aria-pressed={mobilePane === "chat"} className={mobilePane === "chat" ? "active" : ""} onClick={() => setMobilePane("chat")}><MessagesSquare size={16} /> {tr("Conversation", "论文对话")}</button>
      </nav>
      <div className={`workspace-grid show-${mobilePane}`}>
        <PdfPane paperId={paper.id} title={title} page={page} />
        <ChatPanel paperId={paper.id} title={title} onCitation={openCitation} />
      </div>
    </div>
  );
}
