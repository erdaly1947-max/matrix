import test from "node:test";
import assert from "node:assert/strict";
import {
  BINANCE_REST_ORIGINS,
  cacheTtlMs,
  resolveRestRoute,
  validateRestQuery,
  validateWebSocketStreams,
} from "../server.js";

test("only explicitly allowlisted public-market endpoints resolve", () => {
  assert.ok(resolveRestRoute("/binance/api/v3/exchangeInfo"));
  assert.ok(resolveRestRoute("/binance/api/v3/klines"));
  assert.ok(resolveRestRoute("/btcturk/api/v2/server/exchangeinfo"));
  assert.equal(resolveRestRoute("/binance/api/v3/account"), null);
  assert.equal(resolveRestRoute("/proxy"), null);
});

test("Binance candle route requires a safe symbol and interval", () => {
  const route = resolveRestRoute("/binance/api/v3/klines");
  assert.equal(validateRestQuery(route, new URLSearchParams("symbol=BTCUSDT&interval=1h&limit=90")), null);
  assert.notEqual(validateRestQuery(route, new URLSearchParams("symbol=BTCUSDT&interval=1h&url=https://example.com")), null);
  assert.notEqual(validateRestQuery(route, new URLSearchParams("symbol=BTCUSDT&symbol=ETHUSDT&interval=1h")), null);
  assert.notEqual(validateRestQuery(route, new URLSearchParams("symbol=BTCUSDT&interval=not-an-interval")), null);
  assert.notEqual(validateRestQuery(route, new URLSearchParams("symbol=BTCUSDT&interval=1h&limit=99999")), null);
});

test("BtcTurk ticker proxy is limited to its public USDT ticker", () => {
  const route = resolveRestRoute("/btcturk/api/v2/ticker/currency");
  assert.equal(validateRestQuery(route, new URLSearchParams("symbol=usdt")), null);
  assert.notEqual(validateRestQuery(route, new URLSearchParams("symbol=btc")), null);
  assert.notEqual(validateRestQuery(route, new URLSearchParams("symbol=usdt&url=https://example.com")), null);
});

test("only the desktop radar's public kline WebSocket streams are accepted", () => {
  assert.equal(
    validateWebSocketStreams("btcusdt@kline_5m/ethusdt@kline_1h/bnbusdt@kline_1M"),
    null,
  );
  assert.notEqual(validateWebSocketStreams(""), null);
  assert.notEqual(validateWebSocketStreams("btcusdt@trade"), null);
  assert.notEqual(validateWebSocketStreams("btcusdt@kline_1h/../account"), null);
  assert.notEqual(validateWebSocketStreams("btcusdt@kline_1h/btcusdt@kline_1h"), null);
});

test("official Binance REST fallback hosts are fixed, and cache TTLs vary by endpoint", () => {
  assert.deepEqual(BINANCE_REST_ORIGINS, [
    "https://data-api.binance.vision",
    "https://api.binance.com",
    "https://api-gcp.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com",
  ]);
  assert.equal(cacheTtlMs(resolveRestRoute("/binance/api/v3/exchangeInfo"), new URLSearchParams()), 300_000);
  assert.equal(cacheTtlMs(resolveRestRoute("/binance/api/v3/klines"), new URLSearchParams("symbol=BTCUSDT&interval=1h")), 5_000);
  assert.equal(cacheTtlMs(resolveRestRoute("/binance/api/v3/klines"), new URLSearchParams("symbol=BTCUSDT&interval=1h&startTime=1")), 30_000);
});
