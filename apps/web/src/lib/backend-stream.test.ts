// @vitest-environment node
import { afterEach, expect, it, vi } from "vitest";
import { fetchBackend } from "./backend-stream";

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

function provider() {
  let stream!: ReadableStreamDefaultController<Uint8Array>;
  let signal!: AbortSignal;
  const cancel = vi.fn();
  vi.stubGlobal("fetch", vi.fn(async (_url, init) => {
    signal = init.signal;
    return new Response(new ReadableStream<Uint8Array>({ start(c) { stream = c; }, cancel }), {
      headers: { "content-type": "text/event-stream" },
    });
  }));
  return { chunk: () => stream.enqueue(new TextEncoder().encode(": keep-alive\n\n")), signal: () => signal, cancel };
}

it("keeps an active SSE stream alive beyond the old 130 second deadline", async () => {
  vi.useFakeTimers();
  const upstream = provider();
  const response = await fetchBackend(new URL("http://backend"), {});
  const reader = response.body!.getReader();
  for (let i = 0; i < 5; i++) {
    await vi.advanceTimersByTimeAsync(60_000);
    upstream.chunk();
    expect((await reader.read()).done).toBe(false);
    expect(upstream.signal().aborted).toBe(false);
  }
  await reader.cancel();
  expect(upstream.signal().aborted).toBe(true);
  expect(upstream.cancel).toHaveBeenCalled();
  expect(vi.getTimerCount()).toBe(0);
});

it("stops an idle stream and propagates browser cancellation", async () => {
  vi.useFakeTimers();
  const upstream = provider();
  const browser = new AbortController();
  const response = await fetchBackend(new URL("http://backend"), { signal: browser.signal });
  const reading = response.body!.getReader().read();
  const failed = expect(reading).rejects.toThrow();
  browser.abort();
  await failed;
  expect(upstream.signal().aborted).toBe(true);
  expect(vi.getTimerCount()).toBe(0);
});

it("fails a stalled connection after the SSE idle deadline", async () => {
  vi.useFakeTimers();
  const upstream = provider();
  const response = await fetchBackend(new URL("http://backend"), {});
  const failed = expect(response.body!.getReader().read()).rejects.toThrow("timed out");
  await vi.advanceTimersByTimeAsync(180_001);
  await failed;
  expect(upstream.signal().aborted).toBe(true);
});
