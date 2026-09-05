"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type Language = "en" | "zh";

interface I18nContextValue {
  language: Language;
  setLanguage: (language: Language) => void;
  tr: (english: string, chinese: string) => string;
}

const STORAGE_KEY = "scholarmind-language";
const I18nContext = createContext<I18nContextValue>({
  language: "en",
  setLanguage: () => undefined,
  tr: (english) => english,
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>("en");

  const applyLanguage = useCallback((next: Language, persist: boolean) => {
    setLanguageState(next);
    document.documentElement.lang = next === "zh" ? "zh-CN" : "en";
    if (persist) window.localStorage.setItem(STORAGE_KEY, next);
  }, []);

  useEffect(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    const detected: Language = stored === "zh" || stored === "en"
      ? stored
      : window.navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en";
    const timer = window.setTimeout(() => applyLanguage(detected, false), 0);
    return () => window.clearTimeout(timer);
  }, [applyLanguage]);

  const setLanguage = useCallback((next: Language) => applyLanguage(next, true), [applyLanguage]);
  const value = useMemo<I18nContextValue>(() => ({
    language,
    setLanguage,
    tr: (english, chinese) => language === "zh" ? chinese : english,
  }), [language, setLanguage]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  return useContext(I18nContext);
}

export function LanguageToggle({ compact = false }: { compact?: boolean }) {
  const { language, setLanguage, tr } = useI18n();
  return (
    <div className={`language-toggle ${compact ? "compact" : ""}`} aria-label={tr("Interface language", "界面语言")}>
      <button type="button" className={language === "zh" ? "active" : ""} onClick={() => setLanguage("zh")} aria-pressed={language === "zh"}>中</button>
      <button type="button" className={language === "en" ? "active" : ""} onClick={() => setLanguage("en")} aria-pressed={language === "en"}>EN</button>
    </div>
  );
}
