import type { Metadata } from "next";
import { ResearchDesk } from "@/components/research/ResearchDesk";

export const metadata: Metadata = { title: "Topic exploration" };

export default async function ResearchHistoryPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ResearchDesk key={id} searchId={id} />;
}
