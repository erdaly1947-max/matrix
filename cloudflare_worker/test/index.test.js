import test from "node:test";
import assert from "node:assert/strict";
import { __test } from "../src/index.js";

const route = (path) => __test.resolveRestRoute(path);

test("yalnızca sabitlenmiş Binance REST yolları eşlenir", () => {
  assert.equal(route("/binance/api/v3/exchangeInfo").origin, "https://data-api.binance.vision");
  assert.equal(route("/binance/api/v3/klines").path, "/api/v3/klines");
  assert.equal(route("/binance/api/v3/ticker/24hr").exchange, "binance");
  assert.equal(route("/binance/api/v3/depth").exchange, "binance");
  assert.equal(route("/binance/api/v3/account"), null);
  assert.equal(route("/binance/https://evil.example"), null);
});

test("BtcTurk tarafında sadece üç halka açık piyasa endpointi kabul edilir", () => {
  assert.equal(route("/btcturk/api/v2/server/exchangeinfo").origin, "https://api.btcturk.com");
  assert.equal(route("/btcturk/api/v2/ticker/currency").path, "/api/v2/ticker/currency");
  assert.equal(route("/btcturk/api/v2/ticker").exchange, "btcturk");
  assert.equal(route("/btcturk/api/v2/order"), null);
});

test("Binance klines sorgusunda parametre ve aralık doğrulanır", () => {
  const r = route("/binance/api/v3/klines");
  assert.equal(__test.validateRestQuery(r, new URLSearchParams("symbol=BTCUSDT&interval=5m&limit=90")), null);
  assert.notEqual(__test.validateRestQuery(r, new URLSearchParams("symbol=BTCUSDT&interval=bogus")), null);
  assert.notEqual(__test.validateRestQuery(r, new URLSearchParams("symbol=BTCUSDT&interval=5m&url=https%3A%2F%2Fevil.example")), null);
  assert.notEqual(__test.validateRestQuery(r, new URLSearchParams("symbol=BTCUSDT&interval=5m&limit=90000")), null);
});

test("toplu ticker sorgusu JSON simgelerini kısıtlar", () => {
  const r = route("/binance/api/v3/ticker/24hr");
  assert.equal(__test.validateRestQuery(r, new URLSearchParams('symbols=%5B%22BTCUSDT%22%2C%22ETHUSDT%22%5D')), null);
  assert.notEqual(__test.validateRestQuery(r, new URLSearchParams('symbols=%5B%22BTCUSDT%22%2C%22https%3A%2F%2Fevil%22%5D')), null);
  assert.notEqual(__test.validateRestQuery(r, new URLSearchParams("symbol=BTCUSDT&symbols=%5B%22ETHUSDT%22%5D")), null);
});

test("BtcTurk currency sorgusu sadece USDT ile sınırlandırılır", () => {
  const r = route("/btcturk/api/v2/ticker/currency");
  assert.equal(__test.validateRestQuery(r, new URLSearchParams("symbol=usdt")), null);
  assert.notEqual(__test.validateRestQuery(r, new URLSearchParams("symbol=btc")), null);
});

test("WebSocket yalnızca izin verilen kline akışlarını kabul eder", () => {
  assert.equal(__test.validateStreams("btcusdt@kline_5m/ethusdt@kline_1h").length, 2);
  assert.equal(__test.validateStreams("btcusdt@depth"), null);
  assert.equal(__test.validateStreams("btcusdt@kline_5m/../evil"), null);
  assert.equal(__test.validateStreams("btcusdt@kline_5m/btcusdt@kline_5m"), null);
  assert.equal(__test.validateStreams("btcusdt@kline_1M").length, 1);
});

test("önbellek ömürleri API verisinin özelliğine göre ayarlanır", () => {
  assert.equal(__test.cacheTtlSeconds(route("/binance/api/v3/exchangeInfo"), new URLSearchParams()), 300);
  assert.equal(__test.cacheTtlSeconds(route("/binance/api/v3/depth"), new URLSearchParams()), 1);
  assert.equal(__test.cacheTtlSeconds(route("/binance/api/v3/klines"), new URLSearchParams("symbol=BTCUSDT&interval=5m")), 5);
  assert.equal(__test.cacheTtlSeconds(route("/binance/api/v3/klines"), new URLSearchParams("symbol=BTCUSDT&interval=5m&startTime=1000")), 60);
});
