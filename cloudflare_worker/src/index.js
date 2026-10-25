const BINANCE_ORIGIN = "https://data-api.binance.vision";
const BINANCE_WS_ORIGIN = "https://data-stream.binance.vision";
const BTCTURK_ORIGIN = "https://api.btcturk.com";
const REST_WINDOW_MS = 60_000;
const REST_LIMIT_PER_IP = 1_200;
const WS_LIMIT_PER_IP = 16;
const REST_BUCKETS = new Map();
const REST_RESPONSE_CACHE = new Map();
const ACTIVE_WS = new Map();
const BINANCE_REST_ORIGINS = [
  BINANCE_ORIGIN,
  "https://api.binance.com",
  "https://api-gcp.binance.com",
  "https://api1.binance.com",
  "https://api2.binance.com",
  "https://api3.binance.com",
  "https://api4.binance.com",
];

const ROUTES = new Map([
  ["/binance/api/v3/exchangeInfo", { exchange: "binance", path: "/api/v3/exchangeInfo", origin: BINANCE_ORIGIN }],
  ["/binance/api/v3/klines", { exchange: "binance", path: "/api/v3/klines", origin: BINANCE_ORIGIN }],
  ["/binance/api/v3/ticker/24hr", { exchange: "binance", path: "/api/v3/ticker/24hr", origin: BINANCE_ORIGIN }],
  ["/binance/api/v3/depth", { exchange: "binance", path: "/api/v3/depth", origin: BINANCE_ORIGIN }],
  ["/btcturk/api/v2/server/exchangeinfo", { exchange: "btcturk", path: "/api/v2/server/exchangeinfo", origin: BTCTURK_ORIGIN }],
  ["/btcturk/api/v2/ticker/currency", { exchange: "btcturk", path: "/api/v2/ticker/currency", origin: BTCTURK_ORIGIN }],
  ["/btcturk/api/v2/ticker", { exchange: "btcturk", path: "/api/v2/ticker", origin: BTCTURK_ORIGIN }],
]);

function jsonResponse(value, status = 200, extraHeaders = {}) {
  const headers = new Headers({
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
  });
  for (const [key, valueHeader] of Object.entries(extraHeaders)) headers.set(key, valueHeader);
  return new Response(JSON.stringify(value), { status, headers });
}

function getClientIp(request) {
  return request.headers.get("CF-Connecting-IP") || "unknown-client";
}

function checkRestRateLimit(ip, now = Date.now()) {
  let bucket = REST_BUCKETS.get(ip);
  if (!bucket || now - bucket.startedAt >= REST_WINDOW_MS) {
    bucket = { startedAt: now, count: 0 };
    REST_BUCKETS.set(ip, bucket);
  }
  bucket.count += 1;
  if (bucket.count > REST_LIMIT_PER_IP) {
    return Math.max(1, Math.ceil((REST_WINDOW_MS - (now - bucket.startedAt)) / 1000));
  }
  if (REST_BUCKETS.size > 5_000) {
    for (const [key, value] of REST_BUCKETS.entries()) {
      if (now - value.startedAt >= REST_WINDOW_MS) REST_BUCKETS.delete(key);
    }
  }
  return 0;
}

function resolveRestRoute(pathname) {
  return ROUTES.get(pathname) || null;
}

function isSafeSymbol(value) {
  return typeof value === "string" && /^[A-Z0-9]{3,30}$/.test(value);
}

function validateRestQuery(route, params) {
  const allowedByPath = {
    "/api/v3/exchangeInfo": new Set(),
    "/api/v3/klines": new Set(["symbol", "interval", "limit", "startTime", "endTime", "timeZone"]),
    "/api/v3/ticker/24hr": new Set(["symbol", "symbols", "type", "windowSize"]),
    "/api/v3/depth": new Set(["symbol", "limit"]),
    "/api/v2/server/exchangeinfo": new Set(),
    "/api/v2/ticker/currency": new Set(["symbol"]),
    "/api/v2/ticker": new Set(),
  };
  const allowed = allowedByPath[route.path];
  if (!allowed) return "Endpoint izin listesinde değil.";
  for (const key of params.keys()) {
    if (!allowed.has(key)) return "İzin verilmeyen sorgu parametresi.";
    if (params.getAll(key).length !== 1) return "Tekrarlanan sorgu parametresi kabul edilmiyor.";
  }

  if (route.exchange === "binance") {
    const symbol = params.get("symbol");
    if (symbol !== null && !isSafeSymbol(symbol)) return "Geçersiz parite kodu.";
    const symbols = params.get("symbols");
    if (symbols !== null) {
      if (symbol !== null) return "symbol ve symbols birlikte kullanılamaz.";
      let list;
      try {
        list = JSON.parse(symbols);
      } catch {
        return "symbols JSON dizisi olmalı.";
      }
      if (!Array.isArray(list) || list.length < 1 || list.length > 100 || !list.every(isSafeSymbol)) {
        return "symbols listesi geçersiz veya çok büyük.";
      }
    }
    if (route.path === "/api/v3/klines") {
      const interval = params.get("interval");
      const intervals = new Set(["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"]);
      if (interval !== null && !intervals.has(interval)) return "İzin verilmeyen mum aralığı.";
      if (symbol === null || interval === null) return "Kline için symbol ve interval zorunludur.";
    }
    const limit = params.get("limit");
    if (limit !== null && (!/^\d+$/.test(limit) || Number(limit) < 1 || Number(limit) > 1000)) {
      return "limit değeri izin verilen aralıkta değil.";
    }
    for (const key of ["startTime", "endTime"]) {
      const value = params.get(key);
      if (value !== null && (!/^\d+$/.test(value) || !Number.isSafeInteger(Number(value)))) {
        return "Zaman parametresi geçersiz.";
      }
    }
    const timeZone = params.get("timeZone");
    if (timeZone !== null && !/^(?:-?\d{1,2}(?::[0-5]\d)?|[+-]\d{1,2}:[0-5]\d)$/.test(timeZone)) {
      return "timeZone parametresi geçersiz.";
    }
  } else if (route.path === "/api/v2/ticker/currency") {
    if ((params.get("symbol") || "").toLowerCase() !== "usdt") return "Yalnızca USDT ticker sorgusu kabul edilir.";
  }
  return null;
}

function cacheTtlSeconds(route, params) {
  if (route.path === "/api/v3/exchangeInfo") return 300;
  if (route.path === "/api/v2/server/exchangeinfo") return 60;
  if (route.path === "/api/v2/ticker/currency") return 3;
  if (route.path === "/api/v2/ticker") return 2;
  if (route.path === "/api/v3/depth") return 1;
  if (route.path === "/api/v3/ticker/24hr") return 2;
  if (route.path === "/api/v3/klines") {
    return params.has("startTime") || params.has("endTime") ? 60 : 5;
  }
  return 0;
}

async function handleRest(request, url, context) {
  if (request.method !== "GET") {
    return jsonResponse({ error: "Yalnızca GET kabul edilir." }, 405, { Allow: "GET" });
  }
  const route = resolveRestRoute(url.pathname);
  if (!route) return jsonResponse({ error: "Endpoint izin listesinde değil." }, 404);

  const waitSeconds = checkRestRateLimit(getClientIp(request));
  if (waitSeconds > 0) {
    return jsonResponse({ error: "İstek sınırına ulaşıldı; sonra tekrar deneyin." }, 429, { "Retry-After": String(waitSeconds) });
  }

  const invalidQuery = validateRestQuery(route, url.searchParams);
  if (invalidQuery) return jsonResponse({ error: invalidQuery }, 400);

  const ttl = cacheTtlSeconds(route, url.searchParams);
  const cacheKey = route.exchange + ":" + route.path + "?" + url.searchParams.toString();
  const now = Date.now();
  const cached = REST_RESPONSE_CACHE.get(cacheKey);
  if (cached && cached.expiresAt > now) {
    return new Response(cached.body, {
      status: cached.status,
      headers: { ...cached.headers, "X-Firsat-Relay-Cache": "HIT" },
    });
  }
  if (cached) REST_RESPONSE_CACHE.delete(cacheKey);

  const origins = route.exchange === "binance" ? BINANCE_REST_ORIGINS : [route.origin];
  let upstream = null;
  let chosenOrigin = "";
  const errors = [];
  for (const origin of origins) {
    const target = new URL(route.path, origin);
    target.search = url.search;
    try {
      const candidate = await fetch(target.toString(), {
        method: "GET",
        redirect: "manual",
        headers: {
          "Accept": "application/json",
          "User-Agent": "FirsatKontrolMarketRelay/1.0",
        },
      });
      if (candidate.status >= 300 && candidate.status < 400) {
        errors.push(origin + ":redirect_" + candidate.status);
        console.warn("Exchange relay rejected upstream redirect", route.exchange, route.path, origin, candidate.status);
        break;
      }
      if (candidate.status === 429 || candidate.status === 418) {
        upstream = candidate;
        chosenOrigin = origin;
        break;
      }
      if (candidate.status === 403 || candidate.status === 451 || candidate.status >= 500) {
        errors.push(origin + ":http_" + candidate.status);
        console.warn("Exchange REST origin failed; trying approved fallback", route.exchange, route.path, origin, candidate.status);
        upstream = candidate;
        chosenOrigin = origin;
        continue;
      }
      upstream = candidate;
      chosenOrigin = origin;
      break;
    } catch (error) {
      errors.push(origin + ":" + (error instanceof Error ? error.name : "fetch_error"));
      console.warn("Exchange REST origin fetch failed; trying approved fallback", route.exchange, route.path, origin);
    }
  }

  if (!upstream || (!upstream.ok && (upstream.status === 403 || upstream.status === 451 || upstream.status >= 500))) {
    return jsonResponse({
      error: "Resmî piyasa verisi kaynaklarına bağlantı kurulamadı.",
      attempted: errors.length,
    }, 502);
  }
  if (upstream.status >= 300 && upstream.status < 400) {
    return jsonResponse({ error: "Beklenmeyen upstream yönlendirmesi reddedildi." }, 502);
  }

  const bodyText = await upstream.text();
  const responseHeaders = {
    "Content-Type": upstream.headers.get("Content-Type") || "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Firsat-Relay-Cache": "MISS",
    "X-Firsat-Relay-Upstream": chosenOrigin.replace(/^https:\/\//, ""),
  };
  if (upstream.ok && ttl > 0) {
    REST_RESPONSE_CACHE.set(cacheKey, {
      body: bodyText,
      status: upstream.status,
      headers: {
        "Content-Type": responseHeaders["Content-Type"],
        "Cache-Control": responseHeaders["Cache-Control"],
        "X-Content-Type-Options": responseHeaders["X-Content-Type-Options"],
        "X-Firsat-Relay-Upstream": responseHeaders["X-Firsat-Relay-Upstream"],
      },
      expiresAt: Date.now() + ttl * 1000,
    });
    while (REST_RESPONSE_CACHE.size > 400) {
      REST_RESPONSE_CACHE.delete(REST_RESPONSE_CACHE.keys().next().value);
    }
  }
  return new Response(bodyText, { status: upstream.status, headers: responseHeaders });
}

function validateStreams(value) {
  if (typeof value !== "string" || value.length < 1 || value.length > 12_000) return null;
  const streams = value.split("/");
  if (streams.length < 1 || streams.length > 200) return null;
  const pattern = /^[a-z0-9]{2,30}@kline_(?:1m|3m|5m|15m|30m|1h|2h|4h|6h|8h|12h|1d|3d|1w|1M)$/;
  if (!streams.every((stream) => pattern.test(stream))) return null;
  if (new Set(streams).size !== streams.length) return null;
  return streams;
}

function reserveWebSocket(ip) {
  const current = ACTIVE_WS.get(ip) || 0;
  if (current >= WS_LIMIT_PER_IP) return false;
  ACTIVE_WS.set(ip, current + 1);
  return true;
}

function releaseWebSocket(ip) {
  const current = ACTIVE_WS.get(ip) || 0;
  if (current <= 1) ACTIVE_WS.delete(ip);
  else ACTIVE_WS.set(ip, current - 1);
}

function safeCloseCode(code) {
  return code === 1000 || (Number.isInteger(code) && code >= 3000 && code <= 4999) ? code : 1000;
}

async function handleBinanceWebSocket(request, url) {
  if (request.method !== "GET" || (request.headers.get("Upgrade") || "").toLowerCase() !== "websocket") {
    return new Response("WebSocket Upgrade gerekli.", { status: 426, headers: { "Upgrade": "websocket", "Cache-Control": "no-store" } });
  }
  const values = url.searchParams.getAll("streams");
  if (values.length !== 1 || !validateStreams(values[0])) {
    return new Response("Yalnızca izin verilen Binance kline akışları kabul edilir.", { status: 400, headers: { "Cache-Control": "no-store" } });
  }

  const ip = getClientIp(request);
  if (!reserveWebSocket(ip)) {
    return new Response("Bu IP için çok fazla açık veri bağlantısı var.", { status: 429, headers: { "Retry-After": "10", "Cache-Control": "no-store" } });
  }
  let released = false;
  const release = () => {
    if (!released) {
      released = true;
      releaseWebSocket(ip);
    }
  };

  try {
    const target = new URL("/stream", BINANCE_WS_ORIGIN);
    target.searchParams.set("streams", values[0]);
    const upstreamResponse = await fetch(target.toString(), { headers: { Upgrade: "websocket" } });
    const remote = upstreamResponse.webSocket;
    if (!remote) {
      release();
      return new Response("Binance WebSocket bağlantısı kabul edilmedi.", { status: 502, headers: { "Cache-Control": "no-store" } });
    }

    const pair = new WebSocketPair();
    const pairValues = Object.values(pair);
    const client = pairValues[0];
    const server = pairValues[1];
    server.accept({ allowHalfOpen: true });
    remote.accept({ allowHalfOpen: true });

    server.addEventListener("message", (event) => {
      try {
        if (remote.readyState === WebSocket.OPEN) remote.send(event.data);
      } catch {
        try { server.close(1011, "Upstream send failed"); } catch {}
      }
    });
    remote.addEventListener("message", (event) => {
      try {
        if (server.readyState === WebSocket.OPEN) server.send(event.data);
      } catch {
        try { remote.close(1011, "Downstream send failed"); } catch {}
      }
    });
    const handleClose = (event, other) => {
      try {
        const code = safeCloseCode(event.code);
        const reason = typeof event.reason === "string" ? event.reason.slice(0, 100) : "";
        if (other.readyState === WebSocket.OPEN || other.readyState === WebSocket.CONNECTING) other.close(code, reason);
      } catch {}
      release();
    };
    server.addEventListener("close", (event) => handleClose(event, remote));
    remote.addEventListener("close", (event) => handleClose(event, server));
    server.addEventListener("error", () => {
      try { remote.close(1011, "Downstream socket error"); } catch {}
      release();
    });
    remote.addEventListener("error", () => {
      try { server.close(1011, "Upstream socket error"); } catch {}
      release();
    });

    return new Response(null, { status: 101, webSocket: client });
  } catch {
    release();
    return new Response("Binance WebSocket geçidi bağlantı hatası.", { status: 502, headers: { "Cache-Control": "no-store" } });
  }
}

export const __test = { resolveRestRoute, validateRestQuery, validateStreams, cacheTtlSeconds };

export default {
  async fetch(request, _env, context) {
    const url = new URL(request.url);
    if (url.pathname === "/healthz" && request.method === "GET") {
      return jsonResponse({ ok: true, service: "firsat-kontrol-market-relay", version: 1 });
    }
    if (url.pathname === "/ws/binance/stream") {
      return handleBinanceWebSocket(request, url);
    }
    if (url.pathname.startsWith("/binance/") || url.pathname.startsWith("/btcturk/")) {
      return handleRest(request, url, context);
    }
    return jsonResponse({ error: "Bulunamadı." }, 404);
  },
};
