import type { Metadata } from "next";
import { ResearchDesk } from "@/components/research/ResearchDesk";

export const metadata: Metadata = {
  title: "Topic exploration",
  description: "Search arXiv by topic and map a field's progress, bottlenecks, and open questions.",
};

export default function ResearchPage() {
  return <ResearchDesk />;
}
