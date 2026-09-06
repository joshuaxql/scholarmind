export interface ServerEvent<T = unknown> {
  event: string;
  data: T;
}

export async function* readServerEvents(response: Response): AsyncGenerator<ServerEvent> {
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { error?: { message?: string } } | null;
    throw new Error(payload?.error?.message ?? "Unable to start the answer stream");
  }
  if (!response.body) throw new Error("The browser did not provide a response stream");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer = (buffer + decoder.decode(value, { stream: !done })).replaceAll("\r\n", "\n");
      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const parsed = parseBlock(block);
        if (parsed) yield parsed;
        boundary = buffer.indexOf("\n\n");
      }
      if (done) break;
    }
    const trailing = parseBlock(buffer.trim());
    if (trailing) yield trailing;
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

function parseBlock(block: string): ServerEvent | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
  if (!dataLines.length) return null;
  const raw = dataLines.join("\n");
  return { event, data: JSON.parse(raw) as unknown };
}
