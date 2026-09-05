// @vitest-environment node

import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GET, POST } from "./route";

const context = (path: string[]) => ({ params: Promise.resolve({ path }) });
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

describe("backend BFF boundary", () => {
  it.each([
    ["http://localhost", {}, "127.0.0.1"],
    ["http://attacker.example", { "x-scholarmind-settings": "1" }, "127.0.0.1"],
    ["http://localhost", { "x-scholarmind-settings": "1", origin: "https://attacker.example" }, "127.0.0.1"],
    ["http://localhost", { "x-scholarmind-settings": "1", "sec-fetch-site": "cross-site" }, "127.0.0.1"],
    ["http://localhost", { "x-scholarmind-settings": "1" }, "0.0.0.0"],
  ])("rejects unsafe settings access before contacting the API", async (origin, headers, host) => {
    const upstream = vi.fn();
    vi.stubGlobal("fetch", upstream);
    vi.stubEnv("WEB_HOST", host);
    const response = await GET(new NextRequest(`${origin}/api/backend/api/v1/settings`, { headers: headers as HeadersInit }), context(["api", "v1", "settings"]));
    expect(response.status).toBe(403);
    expect(upstream).not.toHaveBeenCalled();
  });

  it("forwards authorized local settings requests with server credentials only", async () => {
    vi.stubEnv("WEB_HOST", "127.0.0.1");
    vi.stubEnv("API_INTERNAL_BEARER_TOKEN", "server-only-token");
    const upstream = vi.fn().mockResolvedValue(Response.json({ fields: [] }, { headers: { "cache-control": "no-store" } }));
    vi.stubGlobal("fetch", upstream);
    const request = new NextRequest("http://localhost:3000/api/backend/api/v1/settings", {
      method: "POST", headers: { "x-scholarmind-settings": "1", "content-type": "application/json", host: "127.0.0.1:3000", origin: "http://127.0.0.1:3000" }, body: "{}",
    });
    const response = await POST(request, context(["api", "v1", "settings"]));
    expect(response.status).toBe(200);
    expect(upstream.mock.calls[0][1].headers.get("authorization")).toBe("Bearer server-only-token");
    expect(upstream.mock.calls[0][1].headers.get("x-scholarmind-settings")).toBe("1");
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(await response.text()).not.toContain("server-only-token");
  });
  it("rejects path traversal segments before contacting the API", async () => {
    const request = new NextRequest("http://localhost/api/backend/../secret");
    const response = await GET(request, context(["..", "secret"]));
    expect(response.status).toBe(400);
    expect(await response.json()).toMatchObject({ error: { code: "invalid_path" } });
  });

  it("rejects oversized browser request bodies", async () => {
    const request = new NextRequest("http://localhost/api/backend/api/v1/papers", {
      method: "POST",
      headers: { "content-length": String(200 * 1024), "content-type": "application/json" },
      body: "{}",
    });
    const response = await POST(request, context(["api", "v1", "papers"]));
    expect(response.status).toBe(413);
    expect(await response.json()).toMatchObject({ error: { code: "request_too_large" } });
  });
});
