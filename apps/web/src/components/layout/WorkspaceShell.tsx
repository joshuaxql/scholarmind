"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { BookOpen, ChevronRight, FileText, FolderOpen, PanelLeft, Search, Settings, SquarePen, X } from "lucide-react";
import { Wordmark } from "@/components/brand/Wordmark";
import { LanguageToggle, useI18n } from "@/components/i18n/I18nProvider";
import { deleteResearch, listPapers, listResearch, removePaperHistory } from "@/lib/api";
import { HistoryActions } from "@/components/history/HistoryActions";
import { ResizeHandle, useResizablePanel } from "@/components/layout/ResizeHandle";
import type { Paper, ResearchSearch } from "@/types/api";

const HistoryContext = createContext({
  refreshHistory: () => {},
  historyRevision: 0,
  setActiveResearchId: (id: string | null) => { void id; },
});
export const useWorkspace = () => useContext(HistoryContext);

export function WorkspaceShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [activeResearchId, setActiveResearchId] = useState<string | null>(null);
  const [historyRevision, setHistoryRevision] = useState(0);
  const removedPapers = useRef(new Set<string>());
  const removedResearch = useRef(new Set<string>());
  const { tr } = useI18n();
  const sidebar = useResizablePanel({ storageKey: "sidebar", initial: 248, min: 200, max: 420 });
  const researchMode = pathname.startsWith("/research");
  const settingsMode = pathname === "/settings";
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const [taskVersion, setTaskVersion] = useState(0);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [research, setResearch] = useState<ResearchSearch[]>([]);
  const [historyFailed, setHistoryFailed] = useState(false);
  const refreshHistory = useCallback(() => {
    void Promise.allSettled([listPapers(8), listResearch(8)]).then(([paperList, researchList]) => {
      if (paperList.status === "fulfilled") setPapers(paperList.value.items.filter((item) => !removedPapers.current.has(item.id)));
      if (researchList.status === "fulfilled") setResearch(researchList.value.items.filter((item) => !removedResearch.current.has(item.id)));
      setHistoryFailed(paperList.status === "rejected" || researchList.status === "rejected");
    });
  }, []);

  useEffect(() => { removedPapers.current.clear(); refreshHistory(); }, [pathname, refreshHistory]);
  useEffect(() => {
    if (!mobileOpen) return;
    const returnFocus = menuButton.current;
    closeButton.current?.focus();
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setMobileOpen(false);
    }
    function closeOnDesktop() {
      if (window.innerWidth > 760) setMobileOpen(false);
    }
    document.addEventListener("keydown", closeOnEscape);
    window.addEventListener("resize", closeOnDesktop);
    return () => {
      document.removeEventListener("keydown", closeOnEscape);
      window.removeEventListener("resize", closeOnDesktop);
      returnFocus?.focus();
    };
  }, [mobileOpen]);

  async function removePaper(id: string) {
    await removePaperHistory(id);
    removedPapers.current.add(id);
    setPapers((items) => items.filter((item) => item.id !== id));
    setHistoryRevision((value) => value + 1);
    if (pathname === `/papers/${id}`) router.replace("/");
    refreshHistory();
  }

  async function removeResearch(id: string) {
    await deleteResearch(id);
    removedResearch.current.add(id);
    setResearch((items) => items.filter((item) => item.id !== id));
    if (pathname === `/research/${id}` || activeResearchId === id) {
      setTaskVersion((value) => value + 1);
      router.replace("/research");
    }
    refreshHistory();
  }

  return (
    <HistoryContext.Provider value={{ refreshHistory, historyRevision, setActiveResearchId }}>
      <div style={sidebar.style} className={`app-shell${collapsed ? " sidebar-collapsed" : ""}${mobileOpen ? " mobile-open" : ""}`}>
        <a className="skip-link" href="#workspace-content">{tr("Skip to content", "跳转到内容")}</a>
        {mobileOpen && <button className="sidebar-backdrop" aria-label={tr("Close sidebar", "关闭侧栏")} onClick={() => setMobileOpen(false)} />}
        <aside className="app-sidebar" id="workspace-sidebar" aria-label={tr("Workspace navigation", "工作区导航")}>
          <div className="sidebar-brand"><Wordmark /><button ref={closeButton} className="icon-button mobile-only" aria-label={tr("Close navigation", "关闭导航")} onClick={() => setMobileOpen(false)}><X size={18} /></button></div>
          <Link className="new-task" href={researchMode ? "/research" : "/"} onClick={() => { setTaskVersion((value) => value + 1); setMobileOpen(false); }}><SquarePen size={17} />{tr("New task", "新建任务")}</Link>
          <nav className="mode-nav" aria-label={tr("Work mode", "工作模式")} onClick={() => setMobileOpen(false)}>
            <span className="sidebar-label">{tr("Work mode", "工作模式")}</span>
            <Link href="/" className={!researchMode && !settingsMode ? "active" : ""} aria-current={!researchMode && !settingsMode ? "page" : undefined}><BookOpen size={17} /><span>{tr("Paper reading", "单篇论文阅读")}</span></Link>
            <Link href="/research" className={researchMode ? "active" : ""} aria-current={researchMode ? "page" : undefined}><Search size={17} /><span>{tr("Topic exploration", "话题探索")}</span></Link>
          </nav>
          <div className="sidebar-history">
            <section><h2 className="sidebar-label">{tr("Recent papers", "最近阅读")}</h2>
              {papers.map((paper) => <HistoryActions key={paper.id} title={paper.title ?? `arXiv:${paper.arxiv_id}`} label={tr("Remove from recent papers", "从最近阅读中移除")} onDelete={() => removePaper(paper.id)}><Link onClick={() => setMobileOpen(false)} href={`/papers/${paper.id}`} className={`history-link${pathname === `/papers/${paper.id}` ? " active" : ""}`} aria-current={pathname === `/papers/${paper.id}` ? "page" : undefined} title={paper.title ?? paper.arxiv_id}><FileText size={15} /><span>{paper.title ?? `arXiv:${paper.arxiv_id}`}</span>{paper.status !== "ready" && <i className={`history-status status-${paper.status}`} />}</Link></HistoryActions>)}
              {!papers.length && <p className="sidebar-empty">{tr("Your papers will appear here", "读过的论文会显示在这里")}</p>}
            </section>
            <section><h2 className="sidebar-label">{tr("Recent explorations", "最近探索")}</h2>
              {research.map((item) => <HistoryActions key={item.id} title={item.topic} onDelete={() => removeResearch(item.id)}><Link onClick={() => setMobileOpen(false)} href={`/research/${item.id}`} className={`history-link${pathname === `/research/${item.id}` ? " active" : ""}`} aria-current={pathname === `/research/${item.id}` ? "page" : undefined} title={item.topic}><Search size={15} /><span>{item.topic}</span></Link></HistoryActions>)}
              {!research.length && <p className="sidebar-empty">{tr("Your topics will appear here", "探索过的话题会显示在这里")}</p>}
            </section>
            {historyFailed && <button className="history-retry" onClick={refreshHistory}>{tr("History unavailable · Retry", "历史加载失败 · 重试")}</button>}
          </div>
          <div className="sidebar-footer"><span className="workspace-avatar"><FolderOpen size={18} /></span><div><strong>{tr("Local workspace", "本地工作区")}</strong><span>ScholarMind</span></div><Link href="/settings" className={`icon-button settings-entry${settingsMode ? " active" : ""}`} aria-label={tr("Settings", "设置")} aria-current={settingsMode ? "page" : undefined} onClick={() => setMobileOpen(false)}><Settings size={18} /></Link></div>
          <ResizeHandle {...sidebar.handleProps} label={tr("Resize sidebar", "调整侧栏宽度")} controls="workspace-sidebar" className="resize-edge-right sidebar-resize" />
        </aside>
        <div className="app-main" inert={mobileOpen}>
          <header className="workspace-topbar">
            <button className="icon-button desktop-only" aria-label={tr("Toggle sidebar", "切换侧栏")} aria-expanded={!collapsed} aria-controls="workspace-sidebar" onClick={() => setCollapsed((value) => !value)}><PanelLeft size={18} /></button>
            <button ref={menuButton} className="icon-button mobile-only" aria-label={tr("Open navigation", "打开导航")} aria-expanded={mobileOpen} aria-controls="workspace-sidebar" onClick={() => setMobileOpen(true)}><PanelLeft size={18} /></button>
            <span className="topbar-project">ScholarMind</span><ChevronRight size={13} className="topbar-divider" /><span>{settingsMode ? tr("Settings", "设置") : researchMode ? tr("Topic exploration", "话题探索") : tr("Paper reading", "单篇论文阅读")}</span>
            <LanguageToggle compact />
          </header>
          <div className="workspace-content" id="workspace-content" tabIndex={-1} key={taskVersion}>{children}</div>
        </div>
      </div>
    </HistoryContext.Provider>
  );
}
