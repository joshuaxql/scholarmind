"use client";

import { FormEvent, useState } from "react";
import { ArrowUp, FileText, LoaderCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { createPaper } from "@/lib/api";
import { useI18n } from "@/components/i18n/I18nProvider";

export function PaperSubmit() {
  const router = useRouter();
  const { tr } = useI18n();
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!value.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await createPaper(value.trim());
      router.push(`/papers/${result.paper.id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : tr("We could not add this paper", "无法添加这篇论文"));
      setSubmitting(false);
    }
  }

  return (
    <><form className="paper-submit" onSubmit={handleSubmit}>
      <div className="paper-submit-row">
        <label className="sr-only" htmlFor="arxiv-input">{tr("arXiv ID or URL", "arXiv 编号或链接")}</label>
        <input
          id="arxiv-input"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder={tr("Paste an arXiv link or enter a paper ID…", "粘贴 arXiv 链接，或输入论文编号…")}
          autoComplete="off"
          spellCheck={false}
          disabled={submitting}
          aria-describedby={error ? "paper-submit-error" : "paper-submit-hint"}
        />
      </div>
      <div className="paper-submit-foot">
        <span className="composer-source"><FileText size={15} /> arXiv <span id="paper-submit-hint">{tr("Full-paper reading", "全文阅读")}</span></span>
        <button className="send-button" type="submit" disabled={!value.trim() || submitting} aria-label={submitting ? tr("Opening", "正在打开") : tr("Read paper", "精读论文")}>
          {submitting ? <LoaderCircle className="spin" size={18} /> : <ArrowUp size={18} />}
        </button>
      </div>
      {error && <p className="form-error" id="paper-submit-error" role="alert">{error}</p>}
    </form>
    <div className="starter-suggestions"><span>{tr("Try a paper", "试着读一篇")}</span><button type="button" disabled={submitting} onClick={() => { setValue("1706.03762"); document.getElementById("arxiv-input")?.focus(); }}>Attention Is All You Need <span>↗</span></button></div></>
  );
}
