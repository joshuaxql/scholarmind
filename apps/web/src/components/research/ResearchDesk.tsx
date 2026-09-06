"use client";

import { FormEvent, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowUp,
  BookOpenCheck,
  ExternalLink,
  LoaderCircle,
  Search,
  SlidersHorizontal,
  Square,
  Telescope,
  TriangleAlert,
} from "lucide-react";
import { ModeSwitch } from "@/components/layout/ModeSwitch";
import { useWorkspace } from "@/components/layout/WorkspaceShell";
import { useI18n } from "@/components/i18n/I18nProvider";
import { analyzeResearch, createPaper, getResearch, searchResearch } from "@/lib/api";
import { researchPreview } from "@/lib/research-preview";
import type {
  ArxivSearchPaper,
  ResearchReport,
  ResearchSearch,
  ResearchSort,
} from "@/types/api";

const CATEGORY_OPTIONS = ["cs.AI", "cs.CL", "cs.CV", "cs.LG", "cs.RO", "stat.ML"];

export function ResearchDesk({ searchId }: { searchId?: string }) {
  const router = useRouter();
  const { refreshHistory, setActiveResearchId } = useWorkspace();
  const { tr } = useI18n();
  const abortRef = useRef<AbortController | null>(null);
  const [topic, setTopic] = useState("");
  const [categories, setCategories] = useState<string[]>([]);
  const [publishedFrom, setPublishedFrom] = useState("");
  const [publishedTo, setPublishedTo] = useState("");
  const [sort, setSort] = useState<ResearchSort>("relevance");
  const [limit, setLimit] = useState(20);
  const [research, setResearch] = useState<ResearchSearch | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [restoring, setRestoring] = useState(Boolean(searchId));
  const [restoreFailed, setRestoreFailed] = useState(false);
  const [searching, setSearching] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [openingPaper, setOpeningPaper] = useState<string | null>(null);
  const [planningOutput, setPlanningOutput] = useState("");
  const [reportOutput, setReportOutput] = useState("");
  const [searchStage, setSearchStage] = useState("planning");
  const [stopped, setStopped] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setActiveResearchId(research?.id ?? null);
    return () => setActiveResearchId(null);
  }, [research?.id, setActiveResearchId]);

  function toggleCategory(category: string) {
    setCategories((current) =>
      current.includes(category)
        ? current.filter((item) => item !== category)
        : [...current, category],
    );
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!topic.trim() || searching || analyzing) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setPlanningOutput("");
    setReportOutput("");
    setSearchStage("planning");
    setStopped(false);
    setSearching(true);
    setAnalyzing(false);
    setResearch(null);
    setError(null);
    setRestoreFailed(false);
    try {
      const result = await searchResearch({
        topic: topic.trim(),
        categories,
        published_from: publishedFrom || null,
        published_to: publishedTo || null,
        sort,
        limit,
      }, controller.signal, (progress) => {
        if (controller.signal.aborted) return;
        if (progress.data.stage) setSearchStage(progress.data.stage);
        if (progress.event === "token" && progress.data.text) {
          setPlanningOutput((current) => current + progress.data.text);
        }
      });
      if (controller.signal.aborted) return;
      setResearch(result);
      refreshHistory();
      setSearching(false);
      if (!result.report) {
        await generateReport(result, controller);
      }
      refreshHistory();
    } catch (cause) {
      if (controller.signal.aborted) return;
      setError(cause instanceof Error ? cause.message : tr("The field scan could not be completed", "无法完成领域检索"));
      setSearching(false);
      setAnalyzing(false);
    }
  }

  async function generateReport(result: ResearchSearch, controller: AbortController) {
    setAnalyzing(true);
    setStopped(false);
    setReportOutput("");
    try {
      for await (const event of analyzeResearch(result.id, controller.signal)) {
        if (controller.signal.aborted) return;
        if (event.event === "token" && event.data.text) {
          setReportOutput((current) => current + event.data.text);
        }
        if (event.event === "done" && event.data.report) {
          setResearch((current) =>
            current ? { ...current, report: event.data.report ?? null, status: "complete" } : current,
          );
          refreshHistory();
        }
        if (event.event === "error") {
          throw new Error(event.data.code === "model_output_limit"
            ? tr("The model exhausted its output budget. Increase LLM_MAX_OUTPUT_TOKENS in Settings and retry.", "模型输出预算已耗尽，请在设置中调高 LLM_MAX_OUTPUT_TOKENS 后重试。推理模型可能在输出正文前用完预算。")
            : event.data.message ?? tr("The research report could not be generated", "无法生成研究报告"));
        }
      }
    } finally {
      if (!controller.signal.aborted) setAnalyzing(false);
    }
  }

  const restoreResearch = useCallback((item: ResearchSearch) => {
    abortRef.current?.abort();
    setPlanningOutput("");
    setReportOutput("");
    setStopped(false);
    setResearch(item);
    setTopic(item.topic);
    setCategories(item.filters.categories ?? []);
    setPublishedFrom(item.filters.published_from ?? "");
    setPublishedTo(item.filters.published_to ?? "");
    setSort(item.filters.sort ?? "relevance");
    setLimit(item.filters.limit ?? 20);
    setSearching(false);
    setAnalyzing(false);
    setError(null);
  }, []);

  useEffect(() => {
    let active = true;
    if (searchId) {
      void getResearch(searchId).then((item) => {
        if (active) restoreResearch(item);
      }).catch((cause: unknown) => {
        if (active) {
          setRestoreFailed(true);
          if (cause instanceof Error) setError(cause.message);
        }
      }).finally(() => { if (active) setRestoring(false); });
    }
    return () => { active = false; abortRef.current?.abort(); };
  }, [searchId, restoreResearch]);

  async function retryReport() {
    if (!research || analyzing) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setError(null);
    try { await generateReport(research, controller); }
    catch (cause) {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : tr("Could not generate report", "无法生成报告"));
    }
  }

  function stopGeneration() {
    abortRef.current?.abort();
    setSearching(false);
    setAnalyzing(false);
    setStopped(true);
    refreshHistory();
  }

  async function openPaper(paper: ArxivSearchPaper) {
    if (openingPaper) return;
    setOpeningPaper(paper.source_id);
    setError(null);
    try {
      const created = await createPaper(paper.arxiv_id);
      router.push(`/papers/${created.paper.id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : tr("The paper could not be opened", "无法打开这篇论文"));
      setOpeningPaper(null);
    }
  }

  return (
    <div className={`research-page${research ? " has-results" : ""}`}>
      <main className="research-main">
        {!restoring && <section className="research-intro">
          {!research && <div className="welcome-icon"><Search size={29} strokeWidth={1.5} /></div>}
          <h1>{research ? research.topic : tr("What would you like to explore?", "今天想探索什么话题？")}</h1>
          <p className="welcome-description">{research
            ? tr("Your research brief, with every source a click away.", "你的研究简报，每个结论都有来源可循。")
            : tr("Explore a field through its papers, ideas, and open questions.", "从一个话题出发，梳理研究脉络，发现值得深入的问题。")}</p>
          {!research && <ModeSwitch mode="research" />}
        </section>}

        <form className="research-form" hidden={restoring} onSubmit={handleSubmit}>
          <div className="research-query-row">
            <label className="sr-only" htmlFor="research-topic">{tr("Research topic", "研究话题")}</label>
            <input
              id="research-topic"
              value={topic}
              onChange={(event) => setTopic(event.target.value)}
              placeholder={tr("e.g. multimodal RAG, embodied planning", "例如：多模态 RAG、具身智能规划")}
              autoComplete="off"
              disabled={searching || analyzing}
            />
          </div>
          <div className="research-composer-tools">
            <span className="composer-source"><Search size={15} /> arXiv <span>{tr("Abstracts", "摘要探索")}</span></span>
            <button className={`filter-toggle${filtersOpen ? " active" : ""}`} type="button" aria-expanded={filtersOpen} aria-controls="research-filters" onClick={() => setFiltersOpen((value) => !value)}><SlidersHorizontal size={14} />{tr("Filters", "筛选")}<span>{limit}</span></button>
            {searching || analyzing
              ? <button key="stop" className="send-button" type="button" onClick={(event) => { event.preventDefault(); stopGeneration(); }} aria-label={tr("Stop generation", "停止生成")}><Square size={15} fill="currentColor" /></button>
              : <button key="submit" className="send-button" type="submit" disabled={!topic.trim()} aria-label={tr("Explore topic", "探索话题")}><ArrowUp size={18} /></button>}

          </div>
          <fieldset className="filter-fieldset" id="research-filters" hidden={!filtersOpen} disabled={searching || analyzing}>
          <div className="research-filter-row">
            <fieldset>
              <legend>{tr("Collections", "分类")}</legend>
              <div className="category-chips">
                {CATEGORY_OPTIONS.map((category) => (
                  <button
                    key={category}
                    type="button"
                    aria-pressed={categories.includes(category)}
                    className={categories.includes(category) ? "active" : ""}
                    onClick={() => toggleCategory(category)}
                  >
                    {category}
                  </button>
                ))}
              </div>
            </fieldset>
            <label>
              <span>{tr("From", "起始日期")}</span>
              <input type="date" value={publishedFrom} onChange={(e) => setPublishedFrom(e.target.value)} />
            </label>
            <label>
              <span>{tr("To", "结束日期")}</span>
              <input type="date" value={publishedTo} onChange={(e) => setPublishedTo(e.target.value)} />
            </label>
            <label>
              <span>{tr("Order", "排序")}</span>
              <select value={sort} onChange={(e) => setSort(e.target.value as ResearchSort)}>
                <option value="relevance">{tr("Relevance", "相关度")}</option>
                <option value="submitted_date">{tr("Newest", "最新发布")}</option>
                <option value="updated_date">{tr("Recently updated", "最近更新")}</option>
              </select>
            </label>
            <label>
              <span>{tr("Papers", "论文数")}</span>
              <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
                <option value={10}>10</option>
                <option value={20}>20</option>
                <option value={30}>30</option>
                <option value={50}>50</option>
              </select>
            </label>
          </div>
          </fieldset>
        </form>

        {(error || restoreFailed) && <div className="research-error" role="alert"><TriangleAlert size={17} /> {error ?? tr("Could not load this exploration", "无法加载这次探索")}</div>}

        {!research && !searching && !restoring && !planningOutput && <div className="starter-suggestions topic-suggestions">
          <span>{tr("Try a topic", "试着探索")}</span>
          {[tr("Retrieval augmented generation", "检索增强生成"), tr("Embodied intelligence", "具身智能"), tr("Multimodal learning", "多模态学习")].map((suggestion) => <button key={suggestion} type="button" onClick={() => { setTopic(suggestion); document.getElementById("research-topic")?.focus(); }}>{suggestion}<span>↗</span></button>)}
        </div>}
        {restoring && <ResearchLoading label={tr("Opening your saved exploration", "正在打开已保存的探索")} />}

        {stopped && <p className="stream-notice" role="status">{tr("Generation stopped. The draft has not been saved as a report.", "已停止生成，当前草稿未保存为正式报告。")}</p>}
        {searching && <ResearchLoading label={searchStage === "searching"
          ? tr("Collecting matching papers from arXiv", "正在从 arXiv 收集匹配论文")
          : tr("Preparing search phrases; text will appear as it arrives", "正在准备检索词，收到内容后会实时显示")} />}
        {!research && planningOutput && <div className="stream-search-terms" aria-label={tr("Generated search phrases", "生成的检索词")}>
          {researchPreview(planningOutput, true).map((part, index) => <span key={index}>{part.text}</span>)}
        </div>}

        {research && (
          <section className="research-workspace">
            <div className="research-corpus">
              <div className="research-section-head">
                <div><span>{tr("Corpus", "语料")} / {String(research.results.length).padStart(2, "0")}</span><h2>{tr("Source papers", "来源论文")}</h2></div>
                {research.cached && <small>{tr("Cached scan", "缓存结果")}</small>}
              </div>
              <div className="query-receipt">
                <span>{tr("SEARCH TERMS", "检索词")}</span>
                <p>{research.filters.terms?.join(" · ") ?? research.topic}</p>
              </div>
              <div className="research-paper-list">
                {research.results.map((paper) => (
                  <article className="research-paper" id={`paper-${paper.source_id}`} key={paper.source_id}>
                    <div className="paper-source-tag">{paper.source_id}</div>
                    <div className="research-paper-body">
                      <div className="research-paper-meta">
                        <span>{new Date(paper.published_at).getFullYear()}</span>
                        <span>{paper.primary_category ?? paper.categories[0] ?? "arXiv"}</span>
                        <span>arXiv:{paper.arxiv_id}</span>
                      </div>
                      <h3>{paper.title}</h3>
                      <p className="research-authors">{formatAuthors(paper.authors, tr("Authors unavailable", "作者信息不可用"))}</p>
                      <details>
                        <summary>{tr("Read abstract", "查看摘要")}</summary>
                        <p>{paper.abstract}</p>
                      </details>
                      <div className="research-paper-actions">
                        <a href={paper.abstract_url} target="_blank" rel="noreferrer">
                          {tr("arXiv record", "arXiv 记录")} <ExternalLink size={12} />
                        </a>
                        <button type="button" onClick={() => void openPaper(paper)} disabled={Boolean(openingPaper)}>
                          {openingPaper === paper.source_id ? <LoaderCircle className="spin" size={12} /> : <BookOpenCheck size={12} />}
                          {tr("Read closely", "精读论文")}
                        </button>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            </div>

            <aside className="research-report">
              <div className="research-section-head report-head">
                <div><span>{tr("Synthesis", "综合分析")} / AI</span><h2>{tr("Field brief", "领域简报")}</h2></div>
                <i className={analyzing ? "active" : ""} />
              </div>
              {analyzing && !reportOutput && <ResearchLoading compact label={tr("Waiting for the model; the report will appear here as it arrives", "正在等待模型输出，报告将逐步显示在这里")} />}
              {!research.report && reportOutput && <div className="report-content report-draft" aria-label={tr("Report draft", "报告草稿")}>
                <p className="stream-notice" role="status">{analyzing
                  ? tr("Generating · draft, awaiting validation", "正在生成 · 草稿待校验")
                  : tr("Incomplete draft · generate again to finish", "未完成草稿 · 可重新生成")}</p>
                {researchPreview(reportOutput).map((part, index) => ["name", "title", "period"].includes(part.key)
                  ? <h3 key={index}>{part.text}</h3>
                  : <p key={index}>{part.text}</p>)}
              </div>}
              {research.report && <ReportView report={research.report} />}
              {!research.report && !analyzing && <div className="report-pending"><p>{tr("Your source papers are ready. Generate a report to explore the findings.", "来源论文已就绪，生成报告以查看研究结论。")}</p><button type="button" onClick={() => void retryReport()}>{tr("Generate report", "生成报告")}</button></div>}
            </aside>
          </section>
        )}
      </main>
      <p className="workspace-note">{tr("Reports use paper abstracts. Open a paper for a closer reading.", "探索报告基于论文摘要，选择精读可进一步阅读原文。")}</p>
    </div>
  );
}

function ResearchLoading({ label, compact = false }: { label: string; compact?: boolean }) {
  const { tr } = useI18n();
  return (
    <div className={compact ? "research-loading compact" : "research-loading"}>
      <div className="scan-orbit"><i /><i /><Telescope size={22} /></div>
      <div><span>{tr("WORKING SET", "处理中")}</span><p>{label}</p><small>{tr("This can take a moment with live model analysis.", "真实模型分析可能需要一点时间。")}</small></div>
    </div>
  );
}

function ReportView({ report }: { report: ResearchReport }) {
  const { tr } = useI18n();
  return (
    <div className="report-content">
      <section className="report-overview">
        <span>{tr("EXECUTIVE SIGNAL", "核心结论")}</span>
        <p>{report.overview}</p>
      </section>

      <ReportSection number="01" title={tr("Research currents", "研究主线")}>
        <div className="theme-list">
          {report.themes.map((theme) => (
            <article key={theme.name}>
              <h3>{theme.name}</h3><p>{theme.summary}</p><CitationLinks ids={theme.paper_ids} />
            </article>
          ))}
        </div>
      </ReportSection>

      <ReportSection number="02" title={tr("Progress line", "进展时间线")}>
        <div className="timeline-list">
          {report.timeline.map((item, index) => (
            <article key={`${item.period}-${index}`}>
              <time>{item.period}</time><div><p>{item.development}</p><CitationLinks ids={item.paper_ids} /></div>
            </article>
          ))}
        </div>
      </ReportSection>

      <ReportSection number="03" title={tr("Bottlenecks", "研究瓶颈")}>
        <div className="bottleneck-list">
          {report.bottlenecks.map((item) => (
            <article key={item.title}>
              <span className={`evidence-${item.evidence_type}`}>{item.evidence_type === "explicit" ? tr("explicit", "明确") : tr("inferred", "推断")}</span>
              <h3>{item.title}</h3><p>{item.description}</p><CitationLinks ids={item.paper_ids} />
            </article>
          ))}
        </div>
      </ReportSection>

      <ReportSection number="04" title={tr("Openings", "研究机会")}>
        <div className="opportunity-list">
          {report.opportunities.map((item, index) => (
            <article key={item.title}><b>{String(index + 1).padStart(2, "0")}</b><div><h3>{item.title}</h3><p>{item.rationale}</p><CitationLinks ids={item.paper_ids} /></div></article>
          ))}
        </div>
      </ReportSection>

      <p className="report-method"><TriangleAlert size={13} /> {report.methodology}</p>
    </div>
  );
}

function ReportSection({ number, title, children }: { number: string; title: string; children: ReactNode }) {
  return <section className="report-section"><header><span>{number}</span><h2>{title}</h2></header>{children}</section>;
}

function CitationLinks({ ids }: { ids: string[] }) {
  return <div className="paper-citations">{ids.map((id) => <a key={id} href={`#paper-${id}`}>[{id}]</a>)}</div>;
}

function formatAuthors(authors: string[], unavailable: string): string {
  if (!authors.length) return unavailable;
  if (authors.length <= 4) return authors.join(", ");
  return `${authors.slice(0, 4).join(", ")} +${authors.length - 4}`;
}
