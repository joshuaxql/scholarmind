"use client";

import { memo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { normalizeMathDelimiters } from "@/lib/math-markdown";

// Structured summary fields can live inside existing paragraphs and headings.
const inlineElement: Components["p"] = ({ children }) => <span>{children}</span>;
const inlineComponents: Components = Object.fromEntries(
  ["p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td", "hr"].map((tag) => [tag, inlineElement]),
);

export const MarkdownContent = memo(function MarkdownContent({ children, inline = false }: { children: string; inline?: boolean }) {
  const content = <ReactMarkdown
    remarkPlugins={[remarkGfm, remarkMath]}
    rehypePlugins={[[rehypeKatex, { trust: false, strict: "ignore", maxExpand: 1000, maxSize: 20 }]]}
    skipHtml
    components={inline ? inlineComponents : undefined}
  >{normalizeMathDelimiters(children)}</ReactMarkdown>;
  return inline ? <span className="markdown-content markdown-inline">{content}</span> : <div className="markdown-content">{content}</div>;
});
