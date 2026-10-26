import http from "node:http";
import { randomUUID, timingSafeEqual } from "node:crypto";
import { pathToFileURL } from "node:url";
import { WebSocket, WebSocketServer } from "ws";

const PORT = Number.parseInt(process.env.PORT || "10000", 10);
const REST_WINDOW_MS = 60_000;
const REST_LIMIT_PER_IP = 1_200;
const MAX_WS_PER_IP = 128;
const MAX_WS_GLOBAL = 200;
const REPORT_WORKER_BASE_URL = "https://firsat-kontrol-analysis-report.erdaly1947.workers.dev";
const REPORT_MAX_BODY_BYTES = 8 * 1024 * 1024;
const REPORT_RATE_WINDOW_MS = 60_000;
const REPORT_RATE_LIMIT_PER_IP = 20;
const REPORT_RATE_BUCKETS = new Map();
const REPORT_UPLOAD_ROUTES = new Map([
  ["/api/report", { kind: "analysis", contentType: "application/json", workerPath: "/api/report", encoding: "gzip" }],
  ["/api/report/daily", { kind: "daily", contentType: "application/json", workerPath: "/api/report/daily", encoding: "gzip" }],
  ["/api/report/troubleshooting", { kind: "troubleshooting", contentType: "application/json", workerPath: "/api/report/troubleshooting", encoding: "gzip" }],
  ["/api/report/troubleshooting-zip", { kind: "troubleshooting_zip", contentType: "application/zip", workerPath: "/api/report/troubleshooting-zip", encoding: null }],
]);
const REST_BUCKETS = new Map();
const REST_CACHE = new Map();
const ACTIVE_WS_BY_IP = new Map();
let activeWebSocketCount = 0;

export const BINANCE_REST_ORIGINS = [
  "https://data-api.binance.vision",
  "https://api.binance.com",
  "https://api-gcp.binance.com",
  "https://api1.binance.com",
  "https://api2.binance.com",
  "https://api3.binance.com",
  "https://api4.binance.com",
];

const BINANCE_WS_ORIGINS = [
  "wss://data-stream.binance.vision:443",
  "wss://stream.binance.com:443",
  "wss://stream.binance.com:9443",
];

const ROUTES = [
  { prefix: "/binance", path: "/api/v3/exchangeInfo", exchange: "binance", allowedParams: [] },
  { prefix: "/binance", path: "/api/v3/klines", exchange: "binance", allowedParams: ["symbol", "interval", "limit", "startTime", "endTime", "timeZone"] },
  { prefix: "/binance", path: "/api/v3/ticker/24hr", exchange: "binance", allowedParams: ["symbol", "symbols", "type", "windowSize"] },
  { prefix: "/binance", path: "/api/v3/depth", exchange: "binance", allowedParams: ["symbol", "limit"] },
  { prefix: "/btcturk", path: "/api/v2/server/exchangeinfo", exchange: "btcturk", allowedParams: [] },
  { prefix: "/btcturk", path: "/api/v2/ticker/currency", exchange: "btcturk", allowedParams: ["symbol"] },
  { prefix: "/btcturk", path: "/api/v2/ticker", exchange: "btcturk", allowedParams: [] },
];

const ROUTE_BY_PATH = new Map(ROUTES.map((route) => [route.prefix + route.path, route]));
const UPSTREAMS = {
  binance: BINANCE_REST_ORIGINS,
  btcturk: ["https://api.btcturk.com"],
};

const CACHE_TTL_MS = {
  "/api/v3/exchangeInfo": 300_000,
  "/api/v2/server/exchangeinfo": 60_000,
  "/api/v2/ticker/currency": 3_000,
  "/api/v2/ticker": 2_000,
  "/api/v3/ticker/24hr": 2_000,
  "/api/v3/depth": 1_000,
  "/api/v3/klines": 5_000,
};

function jsonResponse(res, status, value, headers = {}) {
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Access-Control-Allow-Origin": "*",
    ...headers,
  });
  res.end(JSON.stringify(value));
}

function clientIp(request) {
  const forwarded = request.headers["x-forwarded-for"];
  if (typeof forwarded === "string" && forwarded.trim()) {
    return forwarded.split(",")[0].trim().slice(0, 80) || "unknown";
  }
  return request.socket.remoteAddress || "unknown";
}

function checkRestRateLimit(ip, now = Date.now()) {
  let bucket = REST_BUCKETS.get(ip);
  if (!bucket || now - bucket.startedAt >= REST_WINDOW_MS) {
    bucket = { startedAt: now, count: 0 };
    REST_BUCKETS.set(ip, bucket);
  }
  bucket.count += 1;
  if (bucket.count > REST_LIMIT_PER_IP) {
    return Math.max(1, Math.ceil((REST_WINDOW_MS - (now - bucket.startedAt)) / 1_000));
  }
  if (REST_BUCKETS.size > 5_000) {
    for (const [key, value] of REST_BUCKETS.entries()) {
      if (now - value.startedAt >= REST_WINDOW_MS) REST_BUCKETS.delete(key);
    }
  }
  return 0;
}

export function resolveRestRoute(pathname) {
  return ROUTE_BY_PATH.get(pathname) || null;
}

function isSafeSymbol(value) {
  return typeof value === "string" && /^[A-Z0-9]{3,30}$/.test(value);
}

export function validateRestQuery(route, params) {
  if (!route) return "Endpoint izin listesinde değil.";
  const allowed = new Set(route.allowedParams);
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
      const intervals = new Set([
        "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h",
        "6h", "8h", "12h", "1d", "3d", "1w", "1M",
      ]);
      if (symbol === null || interval === null) return "Kline için symbol ve interval zorunludur.";
      if (!intervals.has(interval)) return "İzin verilmeyen mum aralığı.";
    }

    const limit = params.get("limit");
    if (limit !== null && (!/^\d+$/.test(limit) || Number(limit) < 1 || Number(limit) > 1_000)) {
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
  } else if (
    route.path === "/api/v2/ticker/currency"
    && (params.get("symbol") || "").toLowerCase() !== "usdt"
  ) {
    return "Yalnızca USDT ticker sorgusu kabul edilir.";
  }

  return null;
}

export function validateWebSocketStreams(streams) {
  if (typeof streams !== "string" || streams.length === 0 || streams.length > 40_000) {
    return "streams parametresi eksik veya çok uzun.";
  }
  const names = streams.split("/");
  if (names.length < 1 || names.length > 200) return "Akış sayısı izin verilen aralıkta değil.";
  const valid = /^[a-z0-9]{3,30}@kline_(?:5m|15m|30m|1h|4h|1d|1w|1M)$/;
  if (!names.every((name) => valid.test(name))) {
    return "Yalnızca izin verilen genel Binance mum akışları kabul edilir.";
  }
  if (new Set(names).size !== names.length) return "Tekrarlanan akış adı kabul edilmiyor.";
  return null;
}

export function cacheTtlMs(route, params) {
  if (route.path === "/api/v3/klines" && (params.has("startTime") || params.has("endTime"))) {
    return 30_000;
  }
  return CACHE_TTL_MS[route.path] || 0;
}

function readCache(key, now = Date.now()) {
  const entry = REST_CACHE.get(key);
  if (!entry) return null;
  if (entry.expiresAt <= now) {
    REST_CACHE.delete(key);
    return null;
  }
  return entry;
}

function writeCache(key, entry) {
  if (REST_CACHE.size >= 2_000) {
    const firstKey = REST_CACHE.keys().next().value;
    if (firstKey !== undefined) REST_CACHE.delete(firstKey);
  }
  REST_CACHE.set(key, entry);
}

async function fetchPublicMarketData(route, url) {
  let lastFailure = { status: 502, message: "Piyasa veri kaynağına bağlanılamadı." };

  for (const origin of UPSTREAMS[route.exchange]) {
    const target = new URL(route.path, origin);
    target.search = url.search;
    try {
      const upstream = await fetch(target, {
        method: "GET",
        redirect: "manual",
        headers: {
          "Accept": "application/json",
          "User-Agent": "FirsatKontrolMarketRelay/1.0",
        },
        signal: AbortSignal.timeout(12_000),
      });
      const body = await upstream.text();
      const contentType = upstream.headers.get("content-type") || "application/json";

      if (upstream.ok) {
        if (!contentType.toLowerCase().includes("json")) {
          lastFailure = { status: 502, message: "Üst kaynak JSON olmayan yanıt verdi." };
          continue;
        }
        return {
          status: upstream.status,
          body,
          contentType,
          cacheControl: "public, max-age=0, must-revalidate",
          upstreamHost: new URL(origin).hostname,
        };
      }

      lastFailure = {
        status: upstream.status,
        message: "Üst kaynak HTTP " + upstream.status + " yanıtı verdi.",
      };
      if (![403, 451, 500, 502, 503, 504].includes(upstream.status)) break;
    } catch (error) {
      lastFailure = {
        status: 502,
        message: error?.name === "TimeoutError"
          ? "Üst kaynağın bağlantı zaman aşımı."
          : "Üst kaynağa HTTPS bağlantısı kurulamadı.",
      };
    }
  }

  return {
    status: lastFailure.status,
    body: JSON.stringify({ error: lastFailure.message, source: route.exchange }),
    contentType: "application/json; charset=utf-8",
    cacheControl: "no-store",
    upstreamHost: "unavailable",
  };
}


function checkReportRateLimit(ip, now = Date.now()) {
  let bucket = REPORT_RATE_BUCKETS.get(ip);
  if (!bucket || now - bucket.startedAt >= REPORT_RATE_WINDOW_MS) {
    bucket = { startedAt: now, count: 0 };
    REPORT_RATE_BUCKETS.set(ip, bucket);
  }
  bucket.count += 1;
  if (bucket.count > REPORT_RATE_LIMIT_PER_IP) {
    return Math.max(1, Math.ceil((REPORT_RATE_WINDOW_MS - (now - bucket.startedAt)) / 1_000));
  }
  if (REPORT_RATE_BUCKETS.size > 5_000) {
    for (const [key, value] of REPORT_RATE_BUCKETS.entries()) {
      if (now - value.startedAt >= REPORT_RATE_WINDOW_MS) REPORT_RATE_BUCKETS.delete(key);
    }
  }
  return 0;
}

async function readLimitedBody(request, maxBytes) {
  const chunks = [];
  let total = 0;
  for await (const chunk of request) {
    total += chunk.length;
    if (total > maxBytes) {
      const error = new Error("Rapor boyut sınırını aşıyor.");
      error.status = 413;
      throw error;
    }
    chunks.push(chunk);
  }
  if (total === 0) {
    const error = new Error("Rapor gövdesi boş.");
    error.status = 400;
    throw error;
  }
  return Buffer.concat(chunks, total);
}

function bearerToken(request) {
  const value = request.headers.authorization;
  if (typeof value !== "string" || value.length > 8_192) return "";
  const match = /^Bearer ([^\\s]+)$/.exec(value);
  return match?.[1] || "";
}

async function handleReportUpload(request, response, route) {
  if (request.method !== "POST") {
    jsonResponse(response, 405, { ok: false, error: "Yalnızca POST kabul edilir." }, { Allow: "POST" });
    request.resume();
    return;
  }

  const token = bearerToken(request);
  if (!token) {
    jsonResponse(response, 401, { ok: false, error: "Rapor aktarım kimliği doğrulanamadı." });
    request.resume();
    return;
  }

  const configuredRelayToken = process.env.REPORT_RELAY_TOKEN;
  if (
    configuredRelayToken
    && (
      configuredRelayToken.length > 8_192
      || Buffer.byteLength(token) !== Buffer.byteLength(configuredRelayToken)
      || !timingSafeEqual(Buffer.from(token), Buffer.from(configuredRelayToken))
    )
  ) {
    jsonResponse(response, 401, { ok: false, error: "Rapor aktarım kimliği doğrulanamadı." });
    request.resume();
    return;
  }

  const contentType = String(request.headers["content-type"] || "").split(";")[0].trim().toLowerCase();
  const contentEncoding = String(request.headers["content-encoding"] || "").trim().toLowerCase();
  if (contentType !== route.contentType) {
    jsonResponse(response, 415, { ok: false, error: "Rapor içerik türü beklenen biçimde değil." });
    request.resume();
    return;
  }
  if (contentEncoding !== (route.encoding || "")) {
    jsonResponse(response, 415, { ok: false, error: "Rapor sıkıştırma biçimi beklenen biçimde değil." });
    request.resume();
    return;
  }

  const declaredLength = request.headers["content-length"];
  if (declaredLength !== undefined && (!/^\\d+$/.test(String(declaredLength)) || Number(declaredLength) > REPORT_MAX_BODY_BYTES)) {
    jsonResponse(response, 413, { ok: false, error: "Rapor boyut sınırını aşıyor." });
    request.resume();
    return;
  }

  const retryAfter = checkReportRateLimit(clientIp(request));
  if (retryAfter > 0) {
    jsonResponse(response, 429, { ok: false, error: "Rapor aktarım istek sınırına ulaşıldı." }, {
      "Retry-After": String(retryAfter),
    });
    request.resume();
    return;
  }

  let body;
  try {
    body = await readLimitedBody(request, REPORT_MAX_BODY_BYTES);
  } catch (error) {
    request.resume();
    jsonResponse(response, error.status || 400, { ok: false, error: error.status === 413 ? error.message : "Rapor gövdesi okunamadı." });
    return;
  }

  const requestId = randomUUID();
  const upstreamToken = process.env.CLOUDFLARE_REPORT_TOKEN || token;
  const headers = {
    "Authorization": "Bearer " + upstreamToken,
    "Accept": "application/json",
    "Content-Type": route.contentType + (route.contentType === "application/json" ? "; charset=utf-8" : ""),
    "User-Agent": "FirsatKontrolReportRelay/1.0",
    "X-Request-ID": requestId,
  };
  if (route.encoding) headers["Content-Encoding"] = route.encoding;

  let upstream;
  let responseText;
  try {
    upstream = await fetch(REPORT_WORKER_BASE_URL + route.workerPath, {
      method: "POST",
      headers,
      body,
      redirect: "manual",
      signal: AbortSignal.timeout(25_000),
    });
    responseText = await upstream.text();
  } catch (error) {
    jsonResponse(response, 502, {
      ok: false,
      error: error?.name === "TimeoutError"
        ? "Cloudflare rapor deposuna iletim zaman aşımına uğradı."
        : "Cloudflare rapor deposuna iletim başarısız.",
      report_kind: route.kind,
      request_id: requestId,
    });
    return;
  }

  let result = {};
  try {
    result = responseText ? JSON.parse(responseText) : {};
  } catch {
    jsonResponse(response, 502, {
      ok: false,
      error: "Cloudflare rapor deposu beklenen JSON yanıtını vermedi.",
      report_kind: route.kind,
      request_id: requestId,
    });
    return;
  }

  if (!upstream.ok || result?.ok !== true) {
    const status = upstream.status >= 400 && upstream.status < 500 ? upstream.status : 502;
    jsonResponse(response, status, {
      ok: false,
      error: typeof result?.error === "string" ? result.error.slice(0, 400) : "Cloudflare rapor deposu yüklemeyi onaylamadı.",
      report_kind: route.kind,
      request_id: requestId,
    });
    return;
  }

  jsonResponse(response, 200, {
    ...result,
    ok: true,
    report_kind: route.kind,
    request_id: requestId,
    relay: "render",
    forwarded_at_utc: new Date().toISOString(),
  });
}

async function handleHttp(request, response) {
  let url;
  try {
    url = new URL(request.url || "/", "https://relay.invalid");
  } catch {
    jsonResponse(response, 400, { error: "Geçersiz URL." });
    return;
  }

  if (url.pathname === "/healthz") {
    if (request.method !== "GET") {
      jsonResponse(response, 405, { error: "Yalnızca GET kabul edilir." }, { Allow: "GET" });
      return;
    }
    jsonResponse(response, 200, {
      ok: true,
      service: "firsat-kontrol-market-relay",
      version: 2,
    });
    return;
  }

  if (url.pathname === "/ws/binance/stream") {
    jsonResponse(response, 426, { error: "Bu yol yalnızca WebSocket bağlantısı içindir." }, {
      Upgrade: "websocket",
    });
    return;
  }

  const reportRoute = REPORT_UPLOAD_ROUTES.get(url.pathname);
  if (reportRoute) {
    await handleReportUpload(request, response, reportRoute);
    return;
  }

  if (request.method !== "GET") {
    jsonResponse(response, 405, { error: "Yalnızca GET kabul edilir." }, { Allow: "GET" });
    return;
  }

  const route = resolveRestRoute(url.pathname);
  if (!route) {
    jsonResponse(response, 404, { error: "Endpoint izin listesinde değil." });
    return;
  }

  const retryAfter = checkRestRateLimit(clientIp(request));
  if (retryAfter > 0) {
    jsonResponse(response, 429, { error: "İstek sınırına ulaşıldı; sonra tekrar deneyin." }, {
      "Retry-After": String(retryAfter),
    });
    return;
  }

  const invalidQuery = validateRestQuery(route, url.searchParams);
  if (invalidQuery) {
    jsonResponse(response, 400, { error: invalidQuery });
    return;
  }

  const ttl = cacheTtlMs(route, url.searchParams);
  const cacheKey = route.exchange + ":" + route.path + "?" + url.searchParams.toString();
  if (ttl > 0) {
    const cached = readCache(cacheKey);
    if (cached) {
      response.writeHead(cached.status, {
        "Content-Type": cached.contentType,
        "Cache-Control": cached.cacheControl,
        "X-Content-Type-Options": "nosniff",
        "Access-Control-Allow-Origin": "*",
        "X-Firsat-Relay-Cache": "HIT",
        "X-Firsat-Relay-Upstream": cached.upstreamHost,
      });
      response.end(cached.body);
      return;
    }
  }

  const result = await fetchPublicMarketData(route, url);
  const headers = {
    "Content-Type": result.contentType,
    "Cache-Control": result.cacheControl,
    "X-Content-Type-Options": "nosniff",
    "Access-Control-Allow-Origin": "*",
    "X-Firsat-Relay-Cache": "MISS",
    "X-Firsat-Relay-Upstream": result.upstreamHost,
  };
  response.writeHead(result.status, headers);
  response.end(result.body);

  if (result.status >= 200 && result.status < 300 && ttl > 0) {
    writeCache(cacheKey, { ...result, expiresAt: Date.now() + ttl });
  }
}

function writeUpgradeError(socket, status, message) {
  const phrase = status === 429 ? "Too Many Requests" : "Bad Request";
  const body = JSON.stringify({ error: message });
  socket.write(
    "HTTP/1.1 " + status + " " + phrase + "\r\n"
    + "Content-Type: application/json\r\n"
    + "Content-Length: " + Buffer.byteLength(body) + "\r\n"
    + "Connection: close\r\n\r\n" + body,
  );
  socket.destroy();
}

function acquireWebSocketSlot(ip) {
  const current = ACTIVE_WS_BY_IP.get(ip) || 0;
  if (current >= MAX_WS_PER_IP || activeWebSocketCount >= MAX_WS_GLOBAL) return false;
  ACTIVE_WS_BY_IP.set(ip, current + 1);
  activeWebSocketCount += 1;
  return true;
}

function releaseWebSocketSlot(ip) {
  const current = ACTIVE_WS_BY_IP.get(ip) || 0;
  if (current <= 1) ACTIVE_WS_BY_IP.delete(ip);
  else ACTIVE_WS_BY_IP.set(ip, current - 1);
  activeWebSocketCount = Math.max(0, activeWebSocketCount - 1);
}

function bridgeBinanceStream(client, streams) {
  let closed = false;
  let upstream = null;
  let endpointIndex = 0;

  const cleanup = () => {
    if (closed) return;
    closed = true;
    if (upstream && upstream.readyState !== WebSocket.CLOSED) {
      try {
        upstream.close();
      } catch {
        upstream.terminate();
      }
    }
  };

  client.on("close", cleanup);
  client.on("error", cleanup);

  const tryNextEndpoint = () => {
    if (closed || client.readyState !== WebSocket.OPEN) return;
    if (endpointIndex >= BINANCE_WS_ORIGINS.length) {
      client.close(1013, "Binance public stream is unavailable");
      return;
    }

    const origin = BINANCE_WS_ORIGINS[endpointIndex++];
    const target = origin + "/stream?streams=" + streams;
    let opened = false;
    let fallbackStarted = false;
    let connectTimer;

    const next = () => {
      if (opened || fallbackStarted || closed) return;
      fallbackStarted = true;
      clearTimeout(connectTimer);
      try {
        upstream?.terminate();
      } catch {
        // Retry only against the next allowlisted official public stream host.
      }
      setTimeout(tryNextEndpoint, 100);
    };

    upstream = new WebSocket(target, {
      handshakeTimeout: 7_000,
      maxPayload: 2 * 1024 * 1024,
      perMessageDeflate: false,
      headers: { "User-Agent": "FirsatKontrolMarketRelay/1.0" },
    });

    connectTimer = setTimeout(() => {
      if (!opened) next();
    }, 7_500);

    upstream.on("open", () => {
      if (fallbackStarted || closed) {
        upstream.close();
        return;
      }
      opened = true;
      clearTimeout(connectTimer);
      upstream.on("message", (data, isBinary) => {
        if (client.readyState === WebSocket.OPEN) client.send(data, { binary: isBinary });
      });
      upstream.on("error", () => {
        if (client.readyState === WebSocket.OPEN) client.close(1011, "Upstream stream error");
      });
    });

    upstream.on("error", () => {
      if (!opened) next();
    });

    upstream.on("close", () => {
      clearTimeout(connectTimer);
      if (!opened) next();
      else if (!closed && client.readyState === WebSocket.OPEN) {
        client.close(1011, "Upstream stream closed");
      }
    });
  };

  tryNextEndpoint();
}

export function createRelayServer() {
  const server = http.createServer((request, response) => {
    handleHttp(request, response).catch(() => {
      if (!response.headersSent) {
        jsonResponse(response, 502, { error: "Piyasa verisi isteği tamamlanamadı." });
      } else {
        response.destroy();
      }
    });
  });

  const webSocketServer = new WebSocketServer({
    noServer: true,
    maxPayload: 64 * 1024,
    perMessageDeflate: false,
  });

  server.on("upgrade", (request, socket, head) => {
    let url;
    try {
      url = new URL(request.url || "/", "https://relay.invalid");
    } catch {
      writeUpgradeError(socket, 400, "Geçersiz WebSocket URL.");
      return;
    }

    if (request.method !== "GET" || url.pathname !== "/ws/binance/stream") {
      writeUpgradeError(socket, 400, "WebSocket endpoint izin listesinde değil.");
      return;
    }
    if (
      url.searchParams.getAll("streams").length !== 1
      || [...url.searchParams.keys()].some((key) => key !== "streams")
    ) {
      writeUpgradeError(socket, 400, "Yalnızca tek streams parametresi kabul edilir.");
      return;
    }

    const streams = url.searchParams.get("streams");
    const streamError = validateWebSocketStreams(streams);
    if (streamError) {
      writeUpgradeError(socket, 400, streamError);
      return;
    }

    const ip = clientIp(request);
    if (!acquireWebSocketSlot(ip)) {
      writeUpgradeError(socket, 429, "WebSocket bağlantı sınırına ulaşıldı.");
      return;
    }

    webSocketServer.handleUpgrade(request, socket, head, (client) => {
      let released = false;
      const release = () => {
        if (released) return;
        released = true;
        releaseWebSocketSlot(ip);
      };
      client.once("close", release);
      client.once("error", release);
      webSocketServer.emit("connection", client, request);
      bridgeBinanceStream(client, streams);
    });
  });

  return server;
}

const invokedAsMain = process.argv[1]
  && import.meta.url === pathToFileURL(process.argv[1]).href;

if (invokedAsMain) {
  const server = createRelayServer();
  server.listen(PORT, "0.0.0.0", () => {
    console.log("Fırsat Kontrol piyasa geçidi " + PORT + " portunda hazır.");
  });
}
