"use client";

import Link from "next/link";
import { useI18n } from "@/components/i18n/I18nProvider";

export default function NotFound() {
  const { tr } = useI18n();
  return <main className="screen-state screen-error"><span className="error-number">404</span><h1>{tr("This note is not in the archive.", "档案中没有这条记录。")}</h1><p>{tr("The page may have moved, or the paper is no longer available.", "页面可能已移动，或论文已不可用。")}</p><Link href="/">{tr("Return to ScholarMind", "返回 ScholarMind")}</Link></main>;
}
