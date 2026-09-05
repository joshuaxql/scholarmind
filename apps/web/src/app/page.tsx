"use client";

import { BookOpen } from "lucide-react";
import { ModeSwitch } from "@/components/layout/ModeSwitch";
import { PaperSubmit } from "@/components/paper/PaperSubmit";
import { RecentPapers } from "@/components/paper/RecentPapers";
import { useI18n } from "@/components/i18n/I18nProvider";

export default function HomePage() {
  const { tr } = useI18n();
  return <main className="start-page">
    <section className="start-workspace" aria-labelledby="welcome-heading">
      <div className="welcome-icon"><BookOpen size={29} strokeWidth={1.5} /></div>
      <h1 id="welcome-heading">{tr("What would you like to read?", "今天想读哪篇论文？")}</h1>
      <p className="welcome-description">{tr("Start with a paper. Ask questions, follow the evidence.", "从一篇论文开始，提问、理解，让每个答案有据可循。")}</p>
      <ModeSwitch mode="paper" />
      <PaperSubmit />
      <RecentPapers />
    </section>
    <p className="workspace-note">{tr("Answers include sources. Check the original paper for context.", "回答附带来源引用，阅读原文可以获得完整语境。")}</p>
  </main>;
}
