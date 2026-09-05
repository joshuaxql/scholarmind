"use client";

import { LockKeyhole, Sparkles } from "lucide-react";
import { Wordmark } from "@/components/brand/Wordmark";
import { LanguageToggle, useI18n } from "@/components/i18n/I18nProvider";

export function SiteHeader() {
  const { tr } = useI18n();
  return (
    <header className="site-header">
      <Wordmark />
      <div className="site-header-meta" aria-label={tr("Workspace status", "工作区状态")}>
        <span><LockKeyhole size={13} aria-hidden="true" /> {tr("Private workspace", "私有工作区")}</span>
        <span className="header-model"><Sparkles size={13} aria-hidden="true" /> {tr("Grounded answers", "基于证据回答")}</span>
        <LanguageToggle compact />
      </div>
    </header>
  );
}
