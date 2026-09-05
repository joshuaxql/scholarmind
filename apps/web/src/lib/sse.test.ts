import { describe, expect, it } from "vitest";
import { readServerEvents } from "@/lib/sse";

function streamedResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    }),
    { status: 200, headers: { "content-type": "text/event-stream" } },
  );
}

describe("readServerEvents", () => {
  it("parses events split across network chunks", async () => {
    const response = streamedResponse([
      "event: meta\r\ndata: {\"conversation_id\":\"c1\"}\r\n",
      "\r\nevent: token\ndata: {\"text\":\"hel",
      "lo\"}\n\nevent: done\ndata: {\"characters\":5}\n\n",
    ]);
    const events = [];
    for await (const event of readServerEvents(response)) events.push(event);
    expect(events).toEqual([
      { event: "meta", data: { conversation_id: "c1" } },
      { event: "token", data: { text: "hello" } },
      { event: "done", data: { characters: 5 } },
    ]);
  });

  it("flushes a final event without a trailing blank line", async () => {
    const response = streamedResponse(["event: token\ndata: {\"text\":\"last\"}"]);
    const events = [];
    for await (const event of readServerEvents(response)) events.push(event);
    expect(events).toEqual([{ event: "token", data: { text: "last" } }]);
  });

  it("surfaces a stable upstream error", async () => {
    const response = Response.json(
      { error: { message: "Paper is not ready" } },
      { status: 409 },
    );
    const consume = async () => {
      for await (const event of readServerEvents(response)) void event;
    };
    await expect(consume()).rejects.toThrow("Paper is not ready");
  });
});
