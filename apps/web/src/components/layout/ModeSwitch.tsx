"use client";

import Link from "next/link";
import { BookOpen, Search } from "lucide-react";
import { useI18n } from "@/components/i18n/I18nProvider";

export function ModeSwitch({ mode }: { mode: "paper" | "research" }) {
  const { tr } = useI18n();
  return <nav className="mode-switch" aria-label={tr("Choose a work mode", "选择工作模式")}>
    <Link href="/" className={mode === "paper" ? "active" : ""} aria-current={mode === "paper" ? "page" : undefined}><BookOpen size={15} />{tr("Paper reading", "单篇论文阅读")}</Link>
    <Link href="/research" className={mode === "research" ? "active" : ""} aria-current={mode === "research" ? "page" : undefined}><Search size={15} />{tr("Topic exploration", "话题探索")}</Link>
  </nav>;
}
