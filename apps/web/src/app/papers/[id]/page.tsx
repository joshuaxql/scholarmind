import type { Metadata } from "next";
import { PaperScreen } from "@/components/paper/PaperScreen";

export const metadata: Metadata = { title: "Reading desk" };

export default async function PaperPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <div className="reader-page"><PaperScreen paperId={id} /></div>;
}
