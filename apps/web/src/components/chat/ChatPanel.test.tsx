import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { usePaperChat } from "@/hooks/usePaperChat";

vi.mock("@/hooks/usePaperChat", () => ({ usePaperChat: vi.fn() }));
const mockedUsePaperChat = vi.mocked(usePaperChat);
const send = vi.fn();
const stop = vi.fn();
const historyState = {
  conversations: [],
  activeConversationId: null,
  historyLoading: false,
  deleting: false,
  removeConversation: vi.fn(async () => undefined),
  selectConversation: vi.fn(async () => undefined),
  newConversation: vi.fn(),
};

beforeEach(() => {
  send.mockReset();
  stop.mockReset();
});

describe("ChatPanel", () => {
  it("renders formulas from saved answers alongside page citations", () => {
    const citation = { source_id: "S1", chunk_id: "c1", page_number: 3, section: "Theory", score: 1, excerpt: "Formula" };
    const onCitation = vi.fn();
    mockedUsePaperChat.mockReturnValue({ ...historyState, messages: [{ id: "a", role: "assistant", content: String.raw`\[E=mc^2\] [S1]`, citations: [citation] }], streaming: false, error: null, send, stop });
    const { container } = render(<ChatPanel paperId="paper" title="The Paper" onCitation={onCitation} />);
    expect(container.querySelector(".message-content .katex-display")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /p\. 3/ }));
    expect(onCitation).toHaveBeenCalledWith(citation);
  });

  it("offers evidence-oriented starter questions", () => {
    mockedUsePaperChat.mockReturnValue({ ...historyState, messages: [], streaming: false, error: null, send, stop });
    render(<ChatPanel paperId="paper" title="The Paper" onCitation={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /central contribution/i }));
    expect(send).toHaveBeenCalledWith("What is the central contribution?");
    expect(screen.getByText(/Follow each citation back to the original page/i)).toBeInTheDocument();
  });

  it("renders source chips and navigates to a cited page", () => {
    const citation = {
      source_id: "S1",
      chunk_id: "chunk-1",
      page_number: 7,
      section: "Methods",
      score: 0.91,
      excerpt: "Evidence",
    };
    const onCitation = vi.fn();
    mockedUsePaperChat.mockReturnValue({
      ...historyState,
      messages: [
        { id: "u", role: "user", content: "What changed?" },
        { id: "a", role: "assistant", content: "The method changed [S1].", citations: [citation] },
      ],
      streaming: false,
      error: null,
      send,
      stop,
    });
    render(<ChatPanel paperId="paper" title="The Paper" onCitation={onCitation} />);
    fireEvent.click(screen.getByRole("button", { name: /p\. 7/i }));
    expect(onCitation).toHaveBeenCalledWith(citation);
    expect(screen.getByText("The method changed [S1].")).toBeInTheDocument();
  });

  it("restores a saved conversation from history", () => {
    const selectConversation = vi.fn(async () => undefined);
    mockedUsePaperChat.mockReturnValue({
      ...historyState,
      conversations: [{
        id: "conversation-1",
        paper_id: "paper",
        title: "Explain the proof",
        messages: [{ id: "m1", role: "user", content: "Explain the proof" }],
        created_at: "2025-01-01T00:00:00Z",
        updated_at: "2025-01-02T00:00:00Z",
      }],
      messages: [],
      streaming: false,
      error: null,
      send,
      stop,
      selectConversation,
    });
    render(<ChatPanel paperId="paper" title="The Paper" onCitation={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Conversation history" }));
    fireEvent.keyDown(screen.getByRole("separator", { name: "Resize conversation history width" }), { key: "ArrowLeft" });
    expect(screen.getByRole("separator", { name: "Resize conversation history width" })).toHaveAttribute("aria-valuenow", "350");
    fireEvent.keyDown(screen.getByRole("separator", { name: "Resize conversation history height" }), { key: "ArrowDown" });
    expect(screen.getByRole("separator", { name: "Resize conversation history height" })).toHaveAttribute("aria-valuenow", "370");
    fireEvent.click(screen.getByRole("button", { name: /^Explain the proof/i }));

    expect(selectConversation).toHaveBeenCalledWith("conversation-1");
  });

  it("submits on Enter and preserves Shift+Enter", () => {
    mockedUsePaperChat.mockReturnValue({ ...historyState, messages: [], streaming: false, error: null, send, stop });
    render(<ChatPanel paperId="paper" title="The Paper" onCitation={vi.fn()} />);
    const textarea = screen.getByLabelText("Question about this paper");
    fireEvent.change(textarea, { target: { value: "Explain the proof" } });
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });
    expect(send).toHaveBeenCalledWith("Explain the proof");
  });

  it("sends a question handed over from the briefing card", async () => {
    mockedUsePaperChat.mockReturnValue({ ...historyState, messages: [], streaming: false, error: null, send, stop });
    const { rerender } = render(
      <ChatPanel paperId="paper" title="The Paper" onCitation={vi.fn()} askRequest={null} />,
    );
    rerender(
      <ChatPanel
        paperId="paper"
        title="The Paper"
        onCitation={vi.fn()}
        askRequest={{ text: "Walk me through the methodology.", nonce: 1 }}
      />,
    );
    await waitFor(() =>
      expect(send).toHaveBeenCalledWith("Walk me through the methodology."),
    );
  });
});
