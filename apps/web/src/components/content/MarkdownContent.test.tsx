import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarkdownContent } from "./MarkdownContent";

describe("MarkdownContent", () => {
  it("renders inline and display TeX with accessible MathML", () => {
    const { container } = render(<MarkdownContent>{String.raw`Inline $E=mc^2$, also \(\alpha+\beta\).

$$\sum_{i=1}^{n} i = \frac{n(n+1)}{2}$$

\[\begin{pmatrix}a&b\\c&d\end{pmatrix}\]`}</MarkdownContent>);
    expect(container.querySelectorAll(".katex")).toHaveLength(4);
    expect(container.querySelectorAll(".katex-display")).toHaveLength(2);
    expect(container.querySelectorAll("math")).toHaveLength(4);
    expect(container.querySelector(".katex-error")).toBeNull();
  });

  it("preserves code examples and existing Markdown tables and links", () => {
    const content = "`\\(x\\)` and ``$y$``\n\n```latex\n\\[z\\]\n$$w$$\n```\n\n    \\(q\\)\n\n| Method | Score |\n| --- | --- |\n| **Ours** | 1 |\n\n[Source](https://arxiv.org/abs/1706.03762)";
    const { container } = render(<MarkdownContent>{content}</MarkdownContent>);
    expect(container.querySelector(".katex")).toBeNull();
    expect(screen.getByText("\\(x\\)", { selector: "code" })).toBeInTheDocument();
    expect(screen.getByText("$y$", { selector: "code" })).toBeInTheDocument();
    expect(container.querySelector("pre code")).toHaveTextContent("\\[z\\] $$w$$");
    expect(screen.getByRole("table")).toHaveTextContent("Ours");
    expect(screen.getByRole("link", { name: "Source" })).toHaveAttribute("href", "https://arxiv.org/abs/1706.03762");
  });

  it("can render structured fields inside paragraphs without nested block elements", () => {
    const { container } = render(<p><MarkdownContent inline>{String.raw`Formula \[a^2+b^2=c^2\]`}</MarkdownContent></p>);
    expect(container.querySelectorAll("p")).toHaveLength(1);
    expect(container.querySelector("p div")).toBeNull();
    expect(container.querySelector(".katex-display")).toBeInTheDocument();
  });

  it("recovers when a streamed formula completes and leaves invalid TeX readable", () => {
    const { container, rerender } = render(<MarkdownContent>{String.raw`Answer \(\frac{1`}</MarkdownContent>);
    expect(container).toHaveTextContent(String.raw`\(\frac{1`);
    rerender(<MarkdownContent>{String.raw`Answer \(\frac{1}{2}\) [S1]`}</MarkdownContent>);
    expect(container.querySelector(".katex")).toBeInTheDocument();
    expect(container).toHaveTextContent("[S1]");
    rerender(<MarkdownContent>{String.raw`$\unknowncommand{x}$ trailing text`}</MarkdownContent>);
    expect(container).toHaveTextContent("trailing text");
    expect(container).toHaveTextContent(String.raw`\unknowncommand`);
  });

  it("keeps raw HTML and unsafe TeX commands inert", () => {
    const { container } = render(<MarkdownContent>{String.raw`<img src=x onerror=alert(1)>

$\href{javascript:alert(1)}{click}$

$\includegraphics{https://example.com/tracker.png}$

[bad](javascript:alert%281%29)`}</MarkdownContent>);
    expect(container.querySelector("img,script,iframe")).toBeNull();
    expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
  });
});
