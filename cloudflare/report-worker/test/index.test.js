import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("../src/index.js", import.meta.url), "utf8");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source, "utf8").toString("base64")}`;
const { default: worker } = await import(moduleUrl);

function makeEnv() {
  const store = new Map();
  return {
    UPLOAD_TOKEN: "test-upload-token",
    ANALYSIS_REPORTS: {
      async put(key, value, options = {}) {
        const bytes = new Uint8Array(value);
        const copy = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
        store.set(key, { value: copy, metadata: options.metadata || {} });
      },
      async getWithMetadata(key) {
        return store.get(key) || { value: null, metadata: null };
      },
    },
  };
}

function makeReport(overrides = {}) {
  const candidates = [{ symbol: "ABCUSDT", final_decision: "İZLE" }];
  return {
    report_type: "analysis",
    schema_version: 1,
    generated_at_utc: "2026-10-26T12:00:00Z",
    candidate_count: candidates.length,
    candidates,
    ...overrides,
  };
}

function gzipJson(value) {
  const stream = new Blob([JSON.stringify(value)]).stream().pipeThrough(new CompressionStream("gzip"));
  return new Response(stream).arrayBuffer();
}

function uploadRequest(body, { token = "test-upload-token", encoding = "gzip" } = {}) {
  const headers = { "Content-Type": "application/json", "Content-Encoding": encoding };
  if (token !== null) headers.Authorization = `Bearer ${token}`;
  return new Request("https://reports.test/api/report", {
    method: "POST",
    headers,
    body,
  });
}

test("health and preflight endpoints respond", async () => {
  const env = makeEnv();
  const health = await worker.fetch(new Request("https://reports.test/health"), env);
  assert.equal(health.status, 200);
  assert.equal((await health.json()).service, "analysis-report-store");

  const preflight = await worker.fetch(new Request("https://reports.test/api/report", { method: "OPTIONS" }), env);
  assert.equal(preflight.status, 204);
  assert.equal(preflight.headers.get("Access-Control-Allow-Origin"), "*");
});

test("upload requires the correct bearer token and gzip content encoding", async () => {
  const env = makeEnv();
  const body = await gzipJson(makeReport());
  const unauthorized = await worker.fetch(uploadRequest(body, { token: "wrong" }), env);
  assert.equal(unauthorized.status, 401);

  const unsupported = await worker.fetch(uploadRequest(body, { encoding: "identity" }), env);
  assert.equal(unsupported.status, 415);
});

test("invalid gzip/JSON and invalid report schema are rejected", async () => {
  const env = makeEnv();
  const badGzip = await worker.fetch(uploadRequest(new TextEncoder().encode("not gzip")), env);
  assert.equal(badGzip.status, 400);

  const invalidSchema = makeReport({ schema_version: 2 });
  const response = await worker.fetch(uploadRequest(await gzipJson(invalidSchema)), env);
  assert.equal(response.status, 422);
});

test("valid report is stored compressed and /latest returns readable JSON", async () => {
  const env = makeEnv();
  const report = makeReport({
    candidates: [
      { symbol: "ABCUSDT", final_decision: "İZLE" },
      { symbol: "XYZUSDT", final_decision: "GİRİŞ KOŞULU BEKLE" },
    ],
    candidate_count: 2,
  });
  const response = await worker.fetch(uploadRequest(await gzipJson(report)), env);
  assert.equal(response.status, 201);
  const upload = await response.json();
  assert.equal(upload.ok, true);
  assert.equal(upload.candidate_count, 2);
  assert.match(upload.sha256, /^[0-9a-f]{64}$/);
  assert.equal(upload.read_url, "https://reports.test/latest");

  const latest = await worker.fetch(new Request("https://reports.test/latest"), env);
  assert.equal(latest.status, 200);
  assert.deepEqual(await latest.json(), report);
  assert.equal(latest.headers.get("X-Report-SHA256"), upload.sha256);
  assert.equal(latest.headers.get("Cache-Control"), "no-store, max-age=0");
});

test("latest is 404 before first upload and unknown routes are 404", async () => {
  const env = makeEnv();
  const latest = await worker.fetch(new Request("https://reports.test/latest"), env);
  assert.equal(latest.status, 404);
  const missing = await worker.fetch(new Request("https://reports.test/not-found"), env);
  assert.equal(missing.status, 404);
});

test("compressed upload size is bounded", async () => {
  const env = makeEnv();
  const oversized = new Uint8Array(8 * 1024 * 1024 + 1);
  const response = await worker.fetch(uploadRequest(oversized), env);
  assert.equal(response.status, 413);
});

test("daily and troubleshooting JSON reports have separate upload and read routes", async () => {
  const env = makeEnv();
  const daily = {
    report_type: "daily",
    schema_version: 1,
    report_generated_at_utc: "2026-10-26T12:10:00Z",
    payload: {
      report_generated_at_utc: "2026-10-26T12:10:00Z",
      state: { status: "RUNNING", candidates: [] },
      diagnostics: { application: "FIRSAT-KONTROL PANELİ" },
    },
    markdown: "# Daily report",
  };
  const dailyUpload = await worker.fetch(
    new Request("https://reports.test/api/report/daily", {
      method: "POST",
      headers: { Authorization: "Bearer test-upload-token", "Content-Type": "application/json", "Content-Encoding": "gzip" },
      body: await gzipJson(daily),
    }),
    env,
  );
  assert.equal(dailyUpload.status, 201);
  assert.equal((await dailyUpload.json()).read_url, "https://reports.test/daily");
  const dailyRead = await worker.fetch(new Request("https://reports.test/daily"), env);
  assert.equal(dailyRead.status, 200);
  assert.deepEqual(await dailyRead.json(), daily);

  const troubleshooting = {
    report_type: "troubleshooting",
    schema_version: 1,
    generated_at_utc: "2026-10-26T12:11:00Z",
    daily_report: daily,
    diagnostics: { status: "RUNNING" },
    manifest: { files: [{ name: "manifest.json", size_bytes: 12, sha256: "abc" }] },
    log_tail: "test log line",
  };
  const upload = await worker.fetch(
    new Request("https://reports.test/api/report/troubleshooting", {
      method: "POST",
      headers: { Authorization: "Bearer test-upload-token", "Content-Type": "application/json", "Content-Encoding": "gzip" },
      body: await gzipJson(troubleshooting),
    }),
    env,
  );
  assert.equal(upload.status, 201);
  assert.equal((await upload.json()).read_url, "https://reports.test/troubleshooting");
  const read = await worker.fetch(new Request("https://reports.test/troubleshooting"), env);
  assert.equal(read.status, 200);
  assert.deepEqual(await read.json(), troubleshooting);
});

test("troubleshooting ZIP can be uploaded and downloaded without replacing JSON reports", async () => {
  const env = makeEnv();
  const archive = new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0x01, 0x02, 0x03]);
  const upload = await worker.fetch(
    new Request("https://reports.test/api/report/troubleshooting-zip", {
      method: "POST",
      headers: { Authorization: "Bearer test-upload-token", "Content-Type": "application/zip" },
      body: archive,
    }),
    env,
  );
  assert.equal(upload.status, 201);
  assert.equal((await upload.json()).read_url, "https://reports.test/troubleshooting.zip");
  const download = await worker.fetch(new Request("https://reports.test/troubleshooting.zip"), env);
  assert.equal(download.status, 200);
  assert.equal(download.headers.get("Content-Type"), "application/zip");
  assert.deepEqual(new Uint8Array(await download.arrayBuffer()), archive);
  const missingDailyBeforeUpload = await worker.fetch(new Request("https://reports.test/daily"), makeEnv());
  assert.equal(missingDailyBeforeUpload.status, 404);
});

test("new report routes require bearer auth and ZIP content type", async () => {
  const env = makeEnv();
  const unauthorized = await worker.fetch(
    new Request("https://reports.test/api/report/daily", {
      method: "POST",
      headers: { Authorization: "Bearer wrong", "Content-Type": "application/json", "Content-Encoding": "gzip" },
      body: await gzipJson({
        report_type: "daily", schema_version: 1, report_generated_at_utc: "2026-10-26T12:00:00Z",
        payload: { state: {}, diagnostics: {} },
      }),
    }),
    env,
  );
  assert.equal(unauthorized.status, 401);
  const wrongContentType = await worker.fetch(
    new Request("https://reports.test/api/report/troubleshooting-zip", {
      method: "POST",
      headers: { Authorization: "Bearer test-upload-token", "Content-Type": "application/octet-stream" },
      body: new Uint8Array([0x50, 0x4b, 0x03, 0x04]),
    }),
    env,
  );
  assert.equal(wrongContentType.status, 415);
});
