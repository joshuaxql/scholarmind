import { NextRequest } from "next/server";
import { fetchBackend } from "@/lib/backend-stream";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface RouteContext {
  params: Promise<{ path: string[] }>;
}

const ALLOWED_METHODS = new Set(["GET", "POST", "DELETE"]);
const MAX_REQUEST_BYTES = 128 * 1024;

async function proxy(request: NextRequest, context: RouteContext): Promise<Response> {
  if (!ALLOWED_METHODS.has(request.method)) {
    return Response.json({ error: { code: "method_not_allowed", message: "Method not allowed" } }, { status: 405 });
  }

  const { path } = await context.params;
  if (!path.length || path.some((segment) => !segment || segment === ".." || segment.includes("/"))) {
    return Response.json({ error: { code: "invalid_path", message: "Invalid API path" } }, { status: 400 });
  }

  const settingsRequest = path.join("/").replace(/\/+$/, "") === "api/v1/settings";
  if (settingsRequest) {
    const loopback = new Set(["localhost", "127.0.0.1", "::1", "[::1]"]);
    const origin = request.headers.get("origin");
    // Next normalizes loopback URLs to localhost; Host retains the browser's actual origin.
    const requestHost = request.headers.get("host") ?? request.nextUrl.host;
    let validOrigin = !origin;
    if (origin) {
      try {
        const source = new URL(origin);
        validOrigin = source.host === requestHost && source.protocol === request.nextUrl.protocol
          && loopback.has(source.hostname) && source.origin === origin;
      } catch { validOrigin = false; }
    }
    if (!loopback.has(request.nextUrl.hostname) || !loopback.has(process.env.WEB_HOST ?? "127.0.0.1")
      || request.headers.get("x-scholarmind-settings") !== "1"
      || request.headers.get("sec-fetch-site") === "cross-site"
      || !validOrigin
      || (request.method === "POST" && !request.headers.get("content-type")?.startsWith("application/json"))) {
      return Response.json({ error: { code: "settings_local_only", message: "Open settings from the local workspace" } }, { status: 403, headers: { "cache-control": "no-store" } });
    }
  }

  const baseUrl = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";
  const upstreamUrl = new URL(path.map(encodeURIComponent).join("/"), `${baseUrl.replace(/\/$/, "")}/`);
  upstreamUrl.search = request.nextUrl.search;

  const headers = new Headers();
  if (settingsRequest) headers.set("x-scholarmind-settings", "1");
  const contentType = request.headers.get("content-type");
  const accept = request.headers.get("accept");
  const requestId = request.headers.get("x-request-id");
  if (contentType) headers.set("content-type", contentType);
  if (accept) headers.set("accept", accept);
  if (requestId) headers.set("x-request-id", requestId);
  const token = process.env.API_INTERNAL_BEARER_TOKEN;
  if (token) headers.set("authorization", `Bearer ${token}`);

  let body: ArrayBuffer | undefined;
  if (request.method !== "GET") {
    const declaredLength = Number(request.headers.get("content-length") ?? 0);
    if (declaredLength > MAX_REQUEST_BYTES) {
      return Response.json({ error: { code: "request_too_large", message: "Request body is too large" } }, { status: 413 });
    }
    body = await request.arrayBuffer();
    if (body.byteLength > MAX_REQUEST_BYTES) {
      return Response.json({ error: { code: "request_too_large", message: "Request body is too large" } }, { status: 413 });
    }
  }

  try {
    const upstream = await fetchBackend(upstreamUrl, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      redirect: "follow",
      signal: request.signal,
    });
    const responseHeaders = new Headers();
    for (const name of ["content-type", "content-disposition", "cache-control", "x-request-id"]) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    if (responseHeaders.get("content-type")?.includes("text/event-stream")) {
      responseHeaders.set("x-accel-buffering", "no");
      responseHeaders.set("cache-control", "no-cache, no-transform");
    }
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
  } catch (error) {
    console.error("Backend proxy failed", error instanceof Error ? error.message : "unknown error");
    return Response.json(
      { error: { code: "backend_unavailable", message: "ScholarMind API is temporarily unavailable" } },
      { status: 503 },
    );
  }
}

export const GET = proxy;
export const POST = proxy;
export const DELETE = proxy;
