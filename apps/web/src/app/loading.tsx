"use client";

import { useI18n } from "@/components/i18n/I18nProvider";

export default function Loading() {
  const { tr } = useI18n();
  return <div className="screen-state"><span className="loading-glyph" aria-hidden="true">S/M</span><p>{tr("Arranging the desk…", "正在整理工作台…")}</p></div>;
}
