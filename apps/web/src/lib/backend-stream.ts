// The header deadline protects ordinary requests; SSE uses an idle deadline
// renewed by each chunk (including API heartbeats), not a total 130s deadline.
export async function fetchBackend(url: URL, init: RequestInit): Promise<Response> {
  const abort = new AbortController();
  const cancel = () => abort.abort(init.signal?.reason);
  let timer: ReturnType<typeof setTimeout>;
  const deadline = (ms: number) => {
    clearTimeout(timer);
    timer = setTimeout(() => abort.abort(new Error("Backend stream timed out")), ms);
    timer.unref?.();
  };
  const cleanup = () => {
    clearTimeout(timer);
    init.signal?.removeEventListener("abort", cancel);
  };
  init.signal?.addEventListener("abort", cancel, { once: true });
  deadline(130_000);
  if (init.signal?.aborted) cancel();
  try {
    const upstream = await fetch(url, { ...init, signal: abort.signal });
    if (!upstream.body) {
      cleanup();
      return upstream;
    }
    const streaming = upstream.headers.get("content-type")?.includes("text/event-stream");
    if (streaming) deadline(180_000);
    const reader = upstream.body.getReader();
    let closed = false;
    let onAbort: () => void;
    const finish = () => {
      closed = true;
      cleanup();
      abort.signal.removeEventListener("abort", onAbort);
    };
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        onAbort = () => {
          if (closed) return;
          finish();
          controller.error(abort.signal.reason);
          void reader.cancel(abort.signal.reason).catch(() => {});
        };
        abort.signal.addEventListener("abort", onAbort, { once: true });
        if (abort.signal.aborted) onAbort();
      },
      async pull(controller) {
        try {
          const { value, done } = await reader.read();
          if (closed) return;
          if (done) {
            finish();
            reader.releaseLock();
            controller.close();
          } else {
            if (streaming) deadline(180_000);
            controller.enqueue(value);
          }
        } catch (error) {
          if (closed) return;
          finish();
          controller.error(error);
          abort.abort(error);
        }
      },
      async cancel(reason) {
        finish();
        abort.abort(reason);
        await reader.cancel(reason).catch(() => {});
      },
    });
    return new Response(body, { status: upstream.status, headers: upstream.headers });
  } catch (error) {
    cleanup();
    throw error;
  }
}
