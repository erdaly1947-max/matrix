const MAX_COMPRESSED_BYTES = 8 * 1024 * 1024;
const REPORT_KEY = "latest";

function jsonResponse(payload, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store, max-age=0",
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Authorization, Content-Type, Content-Encoding",
      "X-Content-Type-Options": "nosniff",
      ...extraHeaders,
    },
  });
}

function tokenMatches(provided, expected) {
  if (typeof provided !== "string" || typeof expected !== "string" || !expected) return false;
  let mismatch = provided.length ^ expected.length;
  const max = Math.max(provided.length, expected.length);
  for (let i = 0; i < max; i += 1) {
    mismatch |= (provided.charCodeAt(i) || 0) ^ (expected.charCodeAt(i) || 0);
  }
  return mismatch === 0;
}

async function sha256Hex(buffer) {
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function readGzipJson(compressed) {
  const stream = new Blob([compressed]).stream().pipeThrough(new DecompressionStream("gzip"));
  const text = await new Response(stream).text();
  return JSON.parse(text);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Authorization, Content-Type, Content-Encoding",
      "Access-Control-Max-Age": "86400",
    }});

    if (url.pathname === "/health" && request.method === "GET") {
      return jsonResponse({ ok: true, service: "analysis-report-store", storage: "Cloudflare KV" });
    }

    if (url.pathname === "/api/report" && request.method === "POST") {
      const authorization = request.headers.get("Authorization") || "";
      const provided = authorization.startsWith("Bearer ") ? authorization.slice(7) : "";
      if (!tokenMatches(provided, env.UPLOAD_TOKEN)) {
        return jsonResponse({ ok: false, error: "Yetkisiz yükleme." }, 401);
      }
      if ((request.headers.get("Content-Encoding") || "").toLowerCase() !== "gzip") {
        return jsonResponse({ ok: false, error: "İstek gzip sıkıştırmalı olmalıdır." }, 415);
      }
      const compressed = await request.arrayBuffer();
      if (!compressed.byteLength || compressed.byteLength > MAX_COMPRESSED_BYTES) {
        return jsonResponse({ ok: false, error: "Sıkıştırılmış rapor boyutu geçersiz." }, 413);
      }
      let report;
      try {
        report = await readGzipJson(compressed);
      } catch {
        return jsonResponse({ ok: false, error: "Gzip/JSON içeriği okunamadı." }, 400);
      }
      if (!report || report.report_type !== "analysis" || report.schema_version !== 1 ||
          !Array.isArray(report.candidates) || report.candidate_count !== report.candidates.length) {
        return jsonResponse({ ok: false, error: "Analiz raporu şeması geçersiz." }, 422);
      }
      const digest = await sha256Hex(compressed);
      const metadata = {
        generated_at_utc: report.generated_at_utc || new Date().toISOString(),
        candidate_count: report.candidate_count,
        compressed_bytes: compressed.byteLength,
        sha256: digest,
        schema_version: report.schema_version,
      };
      await env.ANALYSIS_REPORTS.put(REPORT_KEY, compressed, { metadata });
      return jsonResponse({
        ok: true,
        report_type: "analysis",
        candidate_count: report.candidate_count,
        compressed_bytes: compressed.byteLength,
        sha256: digest,
        read_url: new URL("/latest", url.origin).toString(),
      }, 201);
    }

    if (url.pathname === "/latest" && request.method === "GET") {
      const record = await env.ANALYSIS_REPORTS.getWithMetadata(REPORT_KEY, "arrayBuffer");
      if (!record || !record.value) {
        return jsonResponse({ ok: false, error: "Henüz analiz raporu yüklenmedi." }, 404);
      }
      let report;
      try {
        report = await readGzipJson(record.value);
      } catch {
        return jsonResponse({ ok: false, error: "Saklanan analiz raporu açılamadı." }, 500);
      }
      return jsonResponse(report, 200, {
        "X-Report-SHA256": record.metadata?.sha256 || "",
        "X-Report-Generated-At": record.metadata?.generated_at_utc || "",
      });
    }

    return jsonResponse({ ok: false, error: "Uç nokta bulunamadı." }, 404);
  },
};
