"use client";

import { ExternalLink, FileText, RotateCw } from "lucide-react";
import { useMemo, useState } from "react";
import { paperPdfUrl } from "@/lib/api";
import { useI18n } from "@/components/i18n/I18nProvider";

interface PdfPaneProps {
  paperId: string;
  title: string;
  page: number | null;
}

export function PdfPane({ paperId, title, page }: PdfPaneProps) {
  const { tr } = useI18n();
  const [reload, setReload] = useState(0);
  const src = useMemo(() => `${paperPdfUrl(paperId, page ?? undefined)}&r=${reload}`, [paperId, page, reload]);

  return (
    <section className="pdf-pane" aria-label={tr("Paper document", "论文文档")}>
      <div className="pane-toolbar">
        <div className="pane-label"><FileText size={15} /><span>{tr("Document", "文档")}</span>{page && <b>p. {page}</b>}</div>
        <div className="toolbar-actions">
          <button type="button" title={tr("Reload document", "重新加载文档")} onClick={() => setReload((value) => value + 1)} aria-label={tr("Reload document", "重新加载文档")}><RotateCw size={15} /></button>
          <a href={paperPdfUrl(paperId, page ?? undefined)} target="_blank" rel="noreferrer" aria-label={tr("Open PDF in new tab", "在新标签页打开 PDF")}><ExternalLink size={15} /></a>
        </div>
      </div>
      <div className="pdf-frame-wrap">
        <iframe key={`${page}-${reload}`} src={src} title={`${title} PDF`} className="pdf-frame" />
      </div>
    </section>
  );
}
