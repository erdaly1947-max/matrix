import test from "node:test";
import assert from "node:assert/strict";
import { BoundedRestCache, REST_CACHE_MAX_BYTES, REST_CACHE_MAX_ENTRIES } from "../rest_cache.js";

const entry = (length, expiresAt = Date.now() + 60_000) => ({
  body: "x".repeat(length),
  expiresAt,
  status: 200,
  contentType: "application/json; charset=utf-8",
  cacheControl: "public, max-age=0, must-revalidate",
  upstreamHost: "data-api.binance.vision",
});

test("default cache limits protect the Render process memory budget", () => {
  assert.equal(REST_CACHE_MAX_ENTRIES, 2_000);
  assert.equal(REST_CACHE_MAX_BYTES, 32 * 1024 * 1024);
});

test("evicts oldest entries when entry-count limit is reached", () => {
  const cache = new BoundedRestCache({ maxEntries: 2, maxBytes: 10_000 });
  cache.set("first", entry(10));
  cache.set("second", entry(10));
  cache.set("third", entry(10));

  assert.equal(cache.size, 2);
  assert.equal(cache.get("first"), null);
  assert.ok(cache.get("second"));
  assert.ok(cache.get("third"));
});

test("evicts oldest entries when aggregate estimated bytes exceed the budget", () => {
  const cache = new BoundedRestCache({ maxEntries: 20, maxBytes: 600 });
  cache.set("first", entry(100));
  cache.set("second", entry(100));

  assert.equal(cache.size, 1);
  assert.equal(cache.get("first"), null);
  assert.ok(cache.get("second"));
  assert.ok(cache.bytes <= cache.maxBytes);
});

test("does not cache one response larger than the entire byte budget", () => {
  const cache = new BoundedRestCache({ maxEntries: 20, maxBytes: 400 });
  const accepted = cache.set("too-large", entry(500));

  assert.equal(accepted, false);
  assert.equal(cache.size, 0);
  assert.equal(cache.bytes, 0);
});

test("overwriting a key adjusts byte accounting without duplicate entries", () => {
  const cache = new BoundedRestCache({ maxEntries: 20, maxBytes: 2_000 });
  cache.set("same", entry(100));
  const previousBytes = cache.bytes;
  cache.set("same", entry(10));

  assert.equal(cache.size, 1);
  assert.ok(cache.bytes < previousBytes);
  assert.equal(cache.get("same").body.length, 10);
});

test("expired entries are removed and their byte budget is released", () => {
  const cache = new BoundedRestCache({ maxEntries: 20, maxBytes: 2_000 });
  cache.set("expired", entry(100, 100));
  const before = cache.bytes;
  assert.equal(cache.get("expired", 101), null);
  assert.equal(cache.size, 0);
  assert.equal(cache.bytes, 0);
  assert.ok(before > 0);
});

test("inserting a new entry purges expired cache records before eviction", () => {
  const cache = new BoundedRestCache({ maxEntries: 2, maxBytes: 2_000 });
  cache.set("expired", entry(100, 100), 10);
  cache.set("active", entry(100, 10_000), 10);
  cache.set("new", entry(100, 20_000), 200);

  assert.equal(cache.size, 2);
  assert.equal(cache.get("expired", 200), null);
  assert.ok(cache.get("active", 200));
  assert.ok(cache.get("new", 200));
});
