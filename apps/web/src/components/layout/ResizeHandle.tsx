"use client";

import { useCallback, useEffect, useRef, useState, type CSSProperties, type PointerEvent } from "react";
import { useI18n } from "@/components/i18n/I18nProvider";

interface PanelOptions {
  storageKey: string;
  initial: number;
  min: number;
  max: number;
  axis?: "x" | "y";
  unit?: "px" | "%";
  property?: `--${string}`;
}

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

/** Store only layout preferences, with a deterministic first render for hydration. */
export function useResizablePanel({ storageKey, initial, min, max, axis = "x", unit = "px", property = "--panel-size" }: PanelOptions) {
  const [size, setSize] = useState(initial);
  const key = `scholarmind-layout-${storageKey}`;

  useEffect(() => {
    const timer = window.setTimeout(() => {
      try {
        const stored = window.localStorage.getItem(key);
        if (stored !== null && stored.trim() && Number.isFinite(Number(stored))) {
          setSize(clamp(Number(stored), min, max));
        }
      } catch { /* Layout remains usable when browser storage is disabled. */ }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [key, min, max]);

  const onChange = useCallback((value: number) => {
    const next = clamp(value, min, max);
    setSize(next);
    try { window.localStorage.setItem(key, String(next)); } catch { /* Optional persistence. */ }
  }, [key, min, max]);

  return {
    style: { [property]: `${size}${unit}` } as CSSProperties,
    handleProps: { value: size, onChange, initial, min, max, axis, unit },
  };
}

interface ResizeHandleProps {
  label: string;
  value: number;
  initial: number;
  min: number;
  max: number;
  axis: "x" | "y";
  unit: "px" | "%";
  onChange: (value: number) => void;
  className?: string;
  /** An edge on a centered panel moves half as far as its total width. */
  factor?: number;
  controls: string;
}

export function ResizeHandle({ label, value, initial, min, max, axis, unit, onChange, className = "", factor = 1, controls }: ResizeHandleProps) {
  const { tr } = useI18n();
  const drag = useRef<{ pointerId: number; start: number; size: number; scale: number } | null>(null);
  const [dragging, setDragging] = useState(false);

  const finish = useCallback(() => {
    if (!drag.current) return;
    drag.current = null;
    setDragging(false);
    delete document.documentElement.dataset.resizing;
  }, []);

  useEffect(() => {
    window.addEventListener("blur", finish);
    window.addEventListener("resize", finish);
    return () => {
      window.removeEventListener("blur", finish);
      window.removeEventListener("resize", finish);
      if (drag.current) delete document.documentElement.dataset.resizing;
    };
  }, [finish]);

  function start(event: PointerEvent<HTMLDivElement>) {
    const target = document.getElementById(controls);
    if (event.button !== 0 || !target) return;
    const rect = target.getBoundingClientRect();
    const parent = target.parentElement?.getBoundingClientRect();
    const length = axis === "x" ? rect.width : rect.height;
    const available = axis === "x" ? parent?.width : parent?.height;
    const scale = unit === "%" ? 100 / (available || 1) : 1;
    drag.current = { pointerId: event.pointerId, start: axis === "x" ? event.clientX : event.clientY, size: length * scale, scale };
    event.currentTarget.setPointerCapture(event.pointerId);
    event.currentTarget.focus({ preventScroll: true });
    event.preventDefault();
    document.documentElement.dataset.resizing = axis;
    setDragging(true);
  }

  return <>
    <div
      role="separator"
      tabIndex={0}
      aria-label={label}
      aria-controls={controls}
      aria-orientation={axis === "x" ? "vertical" : "horizontal"}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={Math.round(value)}
      aria-valuetext={`${Math.round(value)}${unit}`}
      title={`${label} · ${tr("Drag or use arrow keys; double-click to reset", "拖拽或用方向键调整；双击恢复默认")}`}
      className={`resize-handle resize-${axis} ${className}${dragging ? " dragging" : ""}`}
      onPointerDown={start}
      onPointerMove={(event) => {
        const current = drag.current;
        if (!current || current.pointerId !== event.pointerId) return;
        const position = axis === "x" ? event.clientX : event.clientY;
        onChange(clamp(current.size + (position - current.start) * current.scale * factor, min, max));
      }}
      onPointerUp={finish}
      onPointerCancel={finish}
      onLostPointerCapture={finish}
      onDoubleClick={() => onChange(initial)}
      onKeyDown={(event) => {
        const backward = axis === "x" ? "ArrowLeft" : "ArrowUp";
        const forward = axis === "x" ? "ArrowRight" : "ArrowDown";
        const step = (unit === "%" ? 2 : 10) * (event.shiftKey ? 5 : 1);
        if (![backward, forward, "Home", "End", "Enter", "Escape"].includes(event.key)) return;
        event.preventDefault();
        if (event.key === "Escape") { finish(); return; }
        onChange(event.key === "Home" ? min : event.key === "End" ? max : event.key === "Enter" ? initial : value + (event.key === forward ? step : -step) * Math.sign(factor));
      }}
    ><span aria-hidden="true" /></div>
    {dragging && <div className={`resize-shield resize-shield-${axis}`} aria-hidden="true" />}
  </>;
}
