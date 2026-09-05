"use client";

import { useEffect, useRef, useState, type ReactNode, type MouseEvent } from "react";
import { createPortal } from "react-dom";
import { Ellipsis, LoaderCircle, Trash2 } from "lucide-react";
import { useI18n } from "@/components/i18n/I18nProvider";

interface HistoryActionsProps {
  title: string;
  children: ReactNode;
  onDelete: () => Promise<void>;
  label?: string;
  disabled?: boolean;
}

export function HistoryActions({ title, children, onDelete, label, disabled = false }: HistoryActionsProps) {
  const { tr } = useI18n();
  const [position, setPosition] = useState<{ x: number; y: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const action = useRef<HTMLButtonElement>(null);
  const pending = useRef(false);

  useEffect(() => {
    if (!position) return;
    action.current?.focus();
    function dismiss(event: PointerEvent) {
      if (!menu.current?.contains(event.target as Node) && !trigger.current?.contains(event.target as Node)) setPosition(null);
    }
    function close() { setPosition(null); }
    document.addEventListener("pointerdown", dismiss);
    window.addEventListener("resize", close);
    window.addEventListener("scroll", close, true);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      window.removeEventListener("resize", close);
      window.removeEventListener("scroll", close, true);
    };
  }, [position]);

  function open(x: number, y: number) {
    if (disabled) return;
    setError(null);
    setPosition({ x: Math.max(8, Math.min(x, window.innerWidth - 232)), y: Math.max(8, Math.min(y, window.innerHeight - 176)) });
  }

  function contextMenu(event: MouseEvent) {
    event.preventDefault();
    event.stopPropagation();
    open(event.clientX, event.clientY);
  }

  async function remove() {
    if (pending.current || disabled) return;
    pending.current = true;
    setBusy(true);
    setError(null);
    try {
      await onDelete();
      setPosition(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : tr("Could not delete. Please retry.", "删除失败，请重试。"));
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }

  return <div className="history-item" onContextMenu={contextMenu} onKeyDown={(event) => {
    if (event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) {
      event.preventDefault();
      const rect = event.currentTarget.getBoundingClientRect();
      open(rect.left + 20, rect.bottom);
    }
  }}>
    {children}
    <button ref={trigger} type="button" className="history-more" disabled={disabled} aria-haspopup="menu" aria-expanded={Boolean(position)} aria-label={`${tr("More actions", "更多操作")} · ${title}`} onClick={(event) => {
      event.stopPropagation();
      if (position) { setPosition(null); return; }
      const rect = event.currentTarget.getBoundingClientRect();
      open(rect.left, rect.bottom + 4);
    }}><Ellipsis size={16} /></button>
    {position && createPortal(<div ref={menu} className="history-context-menu" role="menu" aria-label={tr("History actions", "历史记录操作")} style={{ left: position.x, top: position.y }} onClick={(event) => event.stopPropagation()} onContextMenu={(event) => event.preventDefault()} onKeyDown={(event) => {
      if (event.key === "Escape" || event.key === "Tab") {
        event.preventDefault();
        setPosition(null);
        trigger.current?.focus();
      }
      if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) { event.preventDefault(); action.current?.focus(); }
    }}>
      <p className="history-menu-title" title={title}>{title}</p>
      <button ref={action} role="menuitem" type="button" disabled={busy || disabled} onClick={() => void remove()}>
        {busy ? <LoaderCircle size={15} className="spin" /> : <Trash2 size={15} />}
        {busy ? tr("Deleting…", "正在删除…") : label ?? tr("Delete", "删除")}
      </button>
      {error && <p className="history-menu-error" role="alert">{error}</p>}
    </div>, document.body)}
  </div>;
}
