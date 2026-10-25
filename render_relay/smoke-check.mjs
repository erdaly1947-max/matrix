import assert from "node:assert/strict";
import WebSocket from "ws";

const base = String(process.env.RELAY_URL || "https://firsat-kontrol-market-relay.onrender.com")
  .replace(/\/+$/, "");
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function fetchJson(path, timeoutMs = 30_000) {
  const response = await fetch(base + path, {
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(timeoutMs),
  });
  const text = await response.text();
  let value;
  try {
    value = JSON.parse(text);
  } catch {
    throw new Error(path + " yanıtı JSON değil (HTTP " + response.status + ").");
  }
  if (!response.ok) {
    throw new Error(path + " HTTP " + response.status + ": " + JSON.stringify(value).slice(0, 300));
  }
  return { response, value };
}

async function waitForHealth() {
  let lastError = "Henüz yanıt yok.";
  for (let i = 0; i < 60; i += 1) {
    try {
      const { response, value } = await fetchJson("/healthz", 8_000);
      if (value.ok === true && value.service === "firsat-kontrol-market-relay" && value.version === 2) {
        console.log("RENDER_HEALTH_OK " + response.status);
        return;
      }
      lastError = "Beklenmeyen sağlık yanıtı: " + JSON.stringify(value);
    } catch (error) {
      lastError = error.message || String(error);
    }
    await sleep(5_000);
  }
  throw new Error("Render hizmeti 5 dakika içinde hazır olmadı: " + lastError);
}

async function verifyBinance() {
  const { value: info, response: infoResponse } = await fetchJson("/binance/api/v3/exchangeInfo");
  assert.ok(Array.isArray(info.symbols) && info.symbols.length > 0, "Binance exchangeInfo sembol listesi boş.");
  assert.ok(info.symbols.some((item) => item.symbol === "BTCUSDT" && item.status === "TRADING"), "BTCUSDT aktif Spot parite olarak bulunamadı.");
  console.log("BINANCE_EXCHANGE_INFO_OK upstream=" + (infoResponse.headers.get("x-firsat-relay-upstream") || "unknown") + " symbols=" + info.symbols.length);

  const { value: klines } = await fetchJson("/binance/api/v3/klines?symbol=BTCUSDT&interval=5m&limit=2");
  assert.ok(Array.isArray(klines) && klines.length >= 1, "Binance mum verisi boş.");
  assert.ok(Array.isArray(klines[0]) && klines[0].length >= 6, "Binance mum veri biçimi beklenenden farklı.");
  console.log("BINANCE_KLINES_OK candles=" + klines.length);
}

async function verifyBtcTurk() {
  const { value } = await fetchJson("/btcturk/api/v2/ticker/currency?symbol=usdt");
  assert.ok(value && typeof value === "object", "BtcTurk ticker yanıtı geçersiz.");
  console.log("BTCTURK_USDT_TICKER_OK");
}

async function verifyWebSocket() {
  const target = new URL("/ws/binance/stream", base);
  target.protocol = target.protocol === "https:" ? "wss:" : "ws:";
  target.searchParams.set("streams", "btcusdt@kline_5m");

  await new Promise((resolve, reject) => {
    let completed = false;
    const ws = new WebSocket(target, { handshakeTimeout: 10_000, perMessageDeflate: false });
    const timer = setTimeout(() => finish(new Error("Canlı Binance WebSocket verisi 20 saniye içinde gelmedi.")), 20_000);
    function finish(error) {
      if (completed) return;
      completed = true;
      clearTimeout(timer);
      try { ws.close(); } catch {}
      if (error) reject(error);
      else resolve();
    }
    ws.on("open", () => console.log("BINANCE_WEBSOCKET_HANDSHAKE_OK"));
    ws.on("message", (data) => {
      try {
        const envelope = JSON.parse(data.toString());
        const payload = envelope?.data ?? envelope;
        assert.ok(payload?.k && typeof payload.k === "object", "WebSocket mesajı kline verisi içermiyor.");
        console.log("BINANCE_WEBSOCKET_KLINE_OK");
        finish();
      } catch (error) {
        finish(error);
      }
    });
    ws.on("error", (error) => finish(new Error("Binance WebSocket bağlantısı başarısız: " + error.message)));
    ws.on("close", (code, reason) => {
      if (!completed) finish(new Error("WebSocket veri gelmeden kapandı: " + code + " " + reason.toString()));
    });
  });
}

await waitForHealth();
await verifyBinance();
await verifyBtcTurk();
await verifyWebSocket();
console.log("RENDER_LIVE_MARKET_DATA_SMOKE_TESTS_OK");
