import type { Metadata } from "next";
import { I18nProvider } from "@/components/i18n/I18nProvider";
import { WorkspaceShell } from "@/components/layout/WorkspaceShell";
import "katex/dist/katex.min.css";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "ScholarMind — Research workspace", template: "%s · ScholarMind" },
  description: "A research workspace for paper reading, page-aware questions, and topic exploration.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en" suppressHydrationWarning><body><I18nProvider><WorkspaceShell>{children}</WorkspaceShell></I18nProvider></body></html>;
}
