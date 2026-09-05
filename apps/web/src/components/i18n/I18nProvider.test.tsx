import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider, LanguageToggle, useI18n } from "@/components/i18n/I18nProvider";

function Copy() {
  const { tr } = useI18n();
  return <p>{tr("Research history", "研究历史")}</p>;
}

describe("I18nProvider", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.lang = "en";
    vi.restoreAllMocks();
  });

  it("detects Chinese on the first visit", async () => {
    vi.spyOn(window.navigator, "language", "get").mockReturnValue("zh-CN");
    render(<I18nProvider><LanguageToggle /><Copy /></I18nProvider>);

    expect(await screen.findByText("研究历史")).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("zh-CN");
  });

  it("persists a manual language choice", async () => {
    window.localStorage.setItem("scholarmind-language", "zh");
    render(<I18nProvider><LanguageToggle /><Copy /></I18nProvider>);
    await screen.findByText("研究历史");

    fireEvent.click(screen.getByRole("button", { name: "EN" }));

    await waitFor(() => expect(screen.getByText("Research history")).toBeInTheDocument());
    expect(window.localStorage.getItem("scholarmind-language")).toBe("en");
    expect(document.documentElement.lang).toBe("en");
  });
});
