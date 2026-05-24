/**
 * Cloudflare Worker — F1 SignalR proxy
 *
 * Forwards requests to livetiming.formula1.com so the OCI server's
 * datacenter IP never touches F1's CDN directly.
 *
 * Deploy:
 *   1. Install Wrangler:  npm install -g wrangler
 *   2. Login:             wrangler login
 *   3. Deploy:            wrangler deploy
 *
 * Then set in .env on the OCI server:
 *   F1_SIGNALR_PROXY_HOST=your-worker-name.your-account.workers.dev
 */

const F1_HOST   = "livetiming.formula1.com";
const F1_ORIGIN = "https://www.formula1.com";

// Headers that MUST reach F1 looking like a browser.
// Applied last so they always override whatever the Python client sent.
// No "Host" — Cloudflare sets that automatically from the fetch() URL.
const SPOOF_HEADERS = {
  "Origin":          F1_ORIGIN,
  "Referer":         F1_ORIGIN + "/",
  "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
  "Accept-Language": "en-US,en;q=0.9",
};

export default {
  async fetch(request, env, ctx) {
    const url      = new URL(request.url);
    const f1Url    = `https://${F1_HOST}${url.pathname}${url.search}`;
    const upgrade  = (request.headers.get("Upgrade") || "").toLowerCase();

    // ── WebSocket proxy ──────────────────────────────────────────────────────
    if (upgrade === "websocket") {
      // Open a WebSocket connection to F1 on behalf of the caller.
      const f1Resp = await fetch(f1Url, {
        headers: buildHeaders(request.headers, true),
      });

      const f1Ws = f1Resp.webSocket;
      if (!f1Ws) {
        return new Response("F1 upstream did not upgrade to WebSocket", { status: 502 });
      }

      const [client, server] = Object.values(new WebSocketPair());
      f1Ws.accept();
      server.accept();

      // Pipe server → f1
      server.addEventListener("message", ({ data }) => {
        try { f1Ws.send(data); } catch (_) {}
      });
      server.addEventListener("close", ({ code, reason }) => {
        try { f1Ws.close(code, reason); } catch (_) {}
      });

      // Pipe f1 → server
      f1Ws.addEventListener("message", ({ data }) => {
        try { server.send(data); } catch (_) {}
      });
      f1Ws.addEventListener("close", ({ code, reason }) => {
        try { server.close(code, reason); } catch (_) {}
      });

      return new Response(null, { status: 101, webSocket: client });
    }

    // ── Plain HTTP proxy (negotiate POST, etc.) ───────────────────────────────
    const f1Resp = await fetch(f1Url, {
      method:  request.method,
      headers: buildHeaders(request.headers, false),
      body:    request.method !== "GET" && request.method !== "HEAD"
                 ? request.body
                 : undefined,
    });

    // Pass the response back, preserving Set-Cookie (needed for AWSALBCORS).
    return new Response(f1Resp.body, {
      status:  f1Resp.status,
      headers: f1Resp.headers,
    });
  },
};

/**
 * Build headers for the outbound F1 request.
 * Strips hop-by-hop headers, then applies SPOOF_HEADERS last so they
 * always override whatever the Python client sent (e.g. python-urllib UA).
 */
function buildHeaders(incoming, isWs) {
  const skip = new Set([
    "host", "cf-connecting-ip", "cf-ipcountry", "cf-ray", "cf-visitor",
    "x-forwarded-for", "x-forwarded-proto", "x-real-ip",
    "connection", "keep-alive", "transfer-encoding", "upgrade",
    "sec-websocket-key", "sec-websocket-version", "sec-websocket-extensions",
  ]);

  const out = {};
  for (const [k, v] of incoming.entries()) {
    if (!skip.has(k.toLowerCase())) {
      out[k] = v;
    }
  }

  // Spoof headers applied last — always win over client-supplied values.
  Object.assign(out, SPOOF_HEADERS);

  if (isWs) {
    out["Upgrade"] = "websocket";
  }

  return out;
}
