"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Check, LoaderCircle, LockKeyhole, RotateCcw, Search, X } from "lucide-react";
import { useI18n } from "@/components/i18n/I18nProvider";
import { ResizeHandle, useResizablePanel } from "@/components/layout/ResizeHandle";
import { ApiError, getEnvironmentSettings, saveEnvironmentSettings } from "@/lib/api";
import type { EnvironmentField, EnvironmentSettings } from "@/types/api";
import { fieldLabels, settingsGroups } from "./catalog";

export function SettingsPanel() {
  const { tr } = useI18n();
  const categories = useResizablePanel({ storageKey: "settings", initial: 178, min: 140, max: 320 });
  const [settings, setSettings] = useState<EnvironmentSettings | null>(null);
  const [updates, setUpdates] = useState<Record<string, string>>({});
  const [group, setGroup] = useState<string>("llm");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const [error, setError] = useState<Error | null>(null);
  const [saved, setSaved] = useState(false);
  const changedCount = Object.keys(updates).length;
  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const result = await getEnvironmentSettings(signal);
      if (signal?.aborted) return;
      setSettings(result);
      setUpdates({});
      setSaved(false);
    } catch (cause) {
      if (!signal?.aborted) setError(cause instanceof Error ? cause : new Error("Request failed"));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void Promise.resolve().then(() => { if (!controller.signal.aborted) return load(controller.signal); });
    return () => controller.abort();
  }, [load]);

  useEffect(() => {
    if (!changedCount) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [changedCount]);

  function edit(field: EnvironmentField, value: string, clearSecret = false) {
    setSaved(false);
    setUpdates((previous) => {
      const next = { ...previous };
      if (field.sensitive ? value === "" && !clearSecret : value === field.value) delete next[field.key];
      else next[field.key] = value;
      return next;
    });
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!settings || !changedCount || savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const result = await saveEnvironmentSettings(settings.revision, updates);
      setSettings(result);
      setUpdates({}); // Do not retain newly entered credentials after saving.
      setSaved(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error("Request failed"));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  const search = query.trim().toLowerCase();
  const visibleGroups = settingsGroups.map((item) => ({ ...item, fields: (settings?.fields ?? []).filter((field) =>
    field.group === item.id && (!search || `${field.key} ${fieldLabels[field.key]?.join(" ") ?? ""}`.toLowerCase().includes(search)),
  ) })).filter((item) => (search || item.id === group) && item.fields.length > 0);

  return (
    <div className="settings-page">
      <div className="settings-heading"><div><h1>{tr("Settings", "设置")}</h1><p>{tr("Make this workspace yours.", "按你的习惯配置工作区。")}</p></div><span className="settings-file">.env</span></div>
      <div style={categories.style} className="settings-layout">
        <nav id="settings-categories" className="settings-nav" aria-label={tr("Settings categories", "设置分类")}>
          {settingsGroups.map(({ id, en, zh, icon: Icon }) => <button key={id} type="button" className={!search && group === id ? "active" : ""} aria-current={!search && group === id ? "page" : undefined} onClick={() => { setGroup(id); setQuery(""); }}><Icon size={16} /><span>{tr(en, zh)}</span>{settings?.fields.some((field) => field.group === id && field.key in updates) && <i aria-label={tr("Unsaved changes", "未保存")} />}</button>)}
          <p><LockKeyhole size={13} />{tr("Stored on this computer", "配置保存在本机")}</p>
        </nav>
        <ResizeHandle {...categories.handleProps} label={tr("Resize settings categories", "调整设置分类栏宽度")} controls="settings-categories" className="settings-resize" />
        <form className="settings-form" onSubmit={(event) => void save(event)} aria-busy={saving || loading}>
          <div className="settings-search"><Search size={16} /><input type="search" aria-label={tr("Search settings", "搜索设置")} placeholder={tr("Search by name or environment variable…", "搜索设置或环境变量…")} value={query} onChange={(event) => setQuery(event.target.value)} />{query && <button type="button" className="icon-button" aria-label={tr("Clear search", "清空搜索")} onClick={() => setQuery("")}><X size={14} /></button>}</div>
          {(settings?.restart_required || saved) && <div className="settings-notice" role="status"><Check size={16} /><div><strong>{tr("Saved to .env", "已保存到 .env")}</strong><p>{tr("Restart the API and web services to apply changes. Stop the startup script with Ctrl+C, then run your usual start command again.", "重启前后端服务后生效。在启动终端按 Ctrl+C 停止，再执行原来的启动命令。")}</p></div></div>}
          {error && <div className="settings-error" role="alert"><strong>{error instanceof ApiError && error.code === "settings_conflict" ? tr("Configuration changed elsewhere", "配置已被其他操作修改") : error instanceof ApiError && error.code === "settings_local_only" ? tr("Open settings on this computer using localhost", "请在本机通过 localhost 打开设置") : tr("Could not load or save settings", "配置读取或保存失败")}</strong><p>{error.message}</p>{(!settings || (error instanceof ApiError && error.code === "settings_conflict")) && <button type="button" disabled={loading} onClick={() => { setLoading(true); setError(null); void load(); }}>{settings ? tr("Discard edits and reload", "放弃本次修改并重新读取") : tr("Retry", "重试")}</button>}</div>}
          {loading ? <div className="settings-loading" role="status"><LoaderCircle size={18} className="settings-spinner" />{tr("Loading configuration…", "正在读取配置…")}</div> : settings && <>
            <fieldset disabled={saving} className="settings-fields">
              {visibleGroups.map(({ id, en, zh, description, fields }) => <section key={id} aria-label={tr(en, zh)}><div className="settings-section-heading"><h2>{tr(en, zh)}</h2><p>{tr(description[0], description[1])}</p></div>{fields.map((field) => <SettingField key={field.key} field={field} value={updates[field.key] ?? field.value ?? ""} changed={field.key in updates} onChange={(value, clearSecret) => edit(field, value, clearSecret)} onUndo={() => { setUpdates((previous) => { const next = { ...previous }; delete next[field.key]; return next; }); }} />)}</section>)}
              {!visibleGroups.length && <p className="settings-empty">{tr("No matching settings.", "没有找到匹配的设置。")}</p>}
            </fieldset>
            <div className="settings-savebar"><span>{changedCount ? tr(`${changedCount} unsaved changes`, `${changedCount} 项修改未保存`) : tr("Changes take effect after restarting", "修改将在重启后生效")}</span><div><button type="button" className="settings-secondary" disabled={!changedCount || saving} onClick={() => { setUpdates({}); setError(null); }}>{tr("Discard", "放弃修改")}</button><button type="submit" className="settings-primary" disabled={!changedCount || saving}>{saving && <LoaderCircle size={14} className="settings-spinner" />}{saving ? tr("Saving…", "保存中…") : tr("Save changes", "保存修改")}</button></div></div>
          </>}
        </form>
      </div>
    </div>
  );
}

function SettingField({ field, value, changed, onChange, onUndo }: {
  field: EnvironmentField;
  value: string;
  changed: boolean;
  onChange: (value: string, clearSecret?: boolean) => void;
  onUndo: () => void;
}) {
  const { tr } = useI18n();
  const names = fieldLabels[field.key] ?? [field.key, field.key];
  const label = tr(names[0], names[1]);
  const id = `setting-${field.key}`;
  const clearing = field.sensitive && changed && value === "";
  return (
    <div className={`setting-row${changed ? " changed" : ""}`}>
      <div className="setting-label"><label htmlFor={id}>{label}</label><code>{field.key}</code>{!field.in_file && <small>{tr("Default value", "默认值")}</small>}</div>
      <div className="setting-control">
        {field.sensitive ? <><div className="setting-secret"><input id={id} type="password" autoComplete="new-password" maxLength={8192} value={value} disabled={clearing} placeholder={clearing ? tr("Will clear on save", "保存后清除") : field.configured ? tr("Configured · enter to replace", "已配置 · 输入新值可替换") : tr("Not configured", "未配置")} onChange={(event) => onChange(event.target.value)} />{(changed || field.configured) && <button type="button" className="settings-text-button" onClick={changed ? onUndo : () => onChange("", true)}>{changed ? tr("Undo", "撤销") : tr("Clear", "清除")}</button>}</div><small className={clearing ? "setting-clearing" : ""}><LockKeyhole size={11} />{clearing ? tr("This value will be removed on save.", "保存时将清除该值。") : tr("Existing value is never sent to the browser.", "已有值不会传到浏览器。")}</small></>
        : field.kind === "boolean" ? <button id={id} type="button" role="switch" aria-checked={value === "true" || value === "1"} aria-label={label} className="setting-switch" onClick={() => onChange(value === "true" || value === "1" ? "false" : "true")}><span /></button>
        : field.options.length ? <select id={id} value={value} onChange={(event) => onChange(event.target.value)}>{field.options.map((option) => <option key={option} value={option}>{option}</option>)}</select>
        : field.kind === "array" ? <textarea id={id} rows={3} spellCheck={false} value={value} onChange={(event) => onChange(event.target.value)} placeholder='["http://localhost:3000"]' />
        : <input id={id} type={field.kind === "integer" || field.kind === "number" ? "number" : "text"} required={field.kind === "integer" || field.kind === "number"} step={field.kind === "integer" ? 1 : "any"} min={field.minimum ?? undefined} max={field.maximum ?? undefined} maxLength={8192} spellCheck={false} autoComplete="off" value={value} onChange={(event) => onChange(event.target.value)} />}
        {!field.sensitive && (field.minimum !== null || field.maximum !== null) && <small>{tr("Range", "范围")}: {field.exclusive_minimum ? "> " : ""}{field.minimum ?? "−∞"} – {field.maximum ?? "∞"}</small>}
      </div>
      {changed && !field.sensitive && <button type="button" className="icon-button setting-undo" aria-label={tr(`Undo ${label}`, `撤销${label}`)} onClick={onUndo}><RotateCcw size={13} /></button>}
    </div>
  );
}
