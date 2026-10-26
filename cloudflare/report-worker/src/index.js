const MAX_COMPRESSED_BYTES = 8 * 1024 * 1024;
const MAX_ZIP_BYTES = 8 * 1024 * 1024;
const REPORT_KEYS = Object.freeze({
  analysis: "latest",
  daily: "daily_latest",
  troubleshooting: "troubleshooting_latest",
  troubleshootingZip: "troubleshooting_zip_latest",
});
const JSON_REPORT_ROUTES = Object.freeze({
  "/api/report": { kind: "analysis", key: REPORT_KEYS.analysis, readPath: "/latest" },
  "/api/report/daily": { kind: "daily", key: REPORT_KEYS.daily, readPath: "/daily" },
  "/api/report/troubleshooting": { kind: "troubleshooting", key: REPORT_KEYS.troubleshooting, readPath: "/troubleshooting" },
});
const JSON_READ_ROUTES = Object.freeze({
  "/latest": { kind: "analysis", key: REPORT_KEYS.analysis },
  "/daily": { kind: "daily", key: REPORT_KEYS.daily },
  "/troubleshooting": { kind: "troubleshooting", key: REPORT_KEYS.troubleshooting },
});

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

function requestTokenIsValid(request, env) {
  const authorization = request.headers.get("Authorization") || "";
  const provided = authorization.startsWith("Bearer ") ? authorization.slice(7) : "";
  return tokenMatches(provided, env.UPLOAD_TOKEN);
}

function validJsonReport(report, kind) {
  if (!report || report.report_type !== kind || report.schema_version !== 1) return false;
  if (kind === "analysis") {
    return Array.isArray(report.candidates) && report.candidate_count === report.candidates.length;
  }
  if (kind === "daily") {
    return typeof report.report_generated_at_utc === "string" &&
      report.payload && typeof report.payload === "object" &&
      report.payload.state && typeof report.payload.state === "object" &&
      report.payload.diagnostics && typeof report.payload.diagnostics === "object";
  }
  if (kind === "troubleshooting") {
    return typeof report.generated_at_utc === "string" &&
      report.daily_report && typeof report.daily_report === "object" &&
      report.diagnostics && typeof report.diagnostics === "object" &&
      Array.isArray(report.manifest?.files) && typeof report.log_tail === "string";
  }
  return false;
}

async function getStoredJsonReport(env, route) {
  const record = await env.ANALYSIS_REPORTS.getWithMetadata(route.key, "arrayBuffer");
  if (!record || !record.value) {
    return jsonResponse({ ok: false, error: "Bu rapor türü için henüz kayıt yok." }, 404);
  }
  let report;
  try {
    report = await readGzipJson(record.value);
  } catch {
    return jsonResponse({ ok: false, error: "Saklanan rapor açılamadı." }, 500);
  }
  return jsonResponse(report, 200, {
    "X-Report-SHA256": record.metadata?.sha256 || "",
    "X-Report-Generated-At": record.metadata?.generated_at_utc || "",
    "X-Report-Type": route.kind,
  });
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

    const jsonUploadRoute = JSON_REPORT_ROUTES[url.pathname];
    if (request.method === "POST" && jsonUploadRoute) {
      if (!requestTokenIsValid(request, env)) {
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
      if (!validJsonReport(report, jsonUploadRoute.kind)) {
        return jsonResponse({ ok: false, error: "Rapor şeması geçersiz." }, 422);
      }
      const digest = await sha256Hex(compressed);
      const metadata = {
        generated_at_utc: report.generated_at_utc || report.report_generated_at_utc || new Date().toISOString(),
        report_type: jsonUploadRoute.kind,
        candidate_count: report.candidate_count ?? report.daily_report?.state?.candidates?.length ?? null,
        compressed_bytes: compressed.byteLength,
        sha256: digest,
        schema_version: report.schema_version,
      };
      await env.ANALYSIS_REPORTS.put(jsonUploadRoute.key, compressed, { metadata });
      return jsonResponse({
        ok: true,
        report_type: jsonUploadRoute.kind,
        candidate_count: metadata.candidate_count,
        compressed_bytes: compressed.byteLength,
        sha256: digest,
        read_url: new URL(jsonUploadRoute.readPath, url.origin).toString(),
      }, 201);
    }

    if (url.pathname === "/api/report/troubleshooting-zip" && request.method === "POST") {
      if (!requestTokenIsValid(request, env)) {
        return jsonResponse({ ok: false, error: "Yetkisiz yükleme." }, 401);
      }
      const contentType = (request.headers.get("Content-Type") || "").toLowerCase();
      if (!contentType.startsWith("application/zip")) {
        return jsonResponse({ ok: false, error: "ZIP dosyası application/zip olmalıdır." }, 415);
      }
      if (request.headers.has("Content-Encoding")) {
        return jsonResponse({ ok: false, error: "ZIP gövdesi ayrıca Content-Encoding içermemelidir." }, 415);
      }
      const archive = await request.arrayBuffer();
      if (!archive.byteLength || archive.byteLength > MAX_ZIP_BYTES) {
        return jsonResponse({ ok: false, error: "ZIP boyutu geçersiz veya 8 MiB sınırını aşıyor." }, 413);
      }
      const signature = new Uint8Array(archive, 0, Math.min(4, archive.byteLength));
      const isZip = signature.length >= 4 && signature[0] === 0x50 && signature[1] === 0x4b &&
        ((signature[2] === 0x03 && signature[3] === 0x04) ||
         (signature[2] === 0x05 && signature[3] === 0x06) ||
         (signature[2] === 0x07 && signature[3] === 0x08));
      if (!isZip) return jsonResponse({ ok: false, error: "Geçerli ZIP başlığı bulunamadı." }, 400);
      const digest = await sha256Hex(archive);
      await env.ANALYSIS_REPORTS.put(REPORT_KEYS.troubleshootingZip, archive, {
        metadata: {
          generated_at_utc: new Date().toISOString(),
          report_type: "troubleshooting_zip",
          compressed_bytes: archive.byteLength,
          sha256: digest,
        },
      });
      return jsonResponse({
        ok: true,
        report_type: "troubleshooting_zip",
        compressed_bytes: archive.byteLength,
        sha256: digest,
        read_url: new URL("/troubleshooting.zip", url.origin).toString(),
      }, 201);
    }

    if (request.method === "GET" && url.pathname === "/chatgpt/analysis") {
      const record = await env.ANALYSIS_REPORTS.getWithMetadata(REPORT_KEYS.analysis, "arrayBuffer");
      if (!record || !record.value) {
        return jsonResponse({ ok: false, error: "Analiz raporu bulunamadı." }, 404);
      }
      try {
        const report = await readGzipJson(record.value);
        const fields = [
          "symbol", "base_asset", "quote_asset", "phase", "state", "phase_timeframe",
          "latest_price", "findings", "evidence_groups", "relative_strength_vs_btc_pct_points",
          "btc_return_correlation", "missing_checks", "source_market_pair", "btcturk_market_pair",
          "category_status", "data_note", "risk_plan", "data_freshness", "opportunity_score",
          "score_0_100", "final_decision", "decision_class", "decision_reason",
          "strong_opportunity_qualified", "strong_opportunity_gate_reasons", "liquidity_assessment"
        ];
        const candidates = (Array.isArray(report.candidates) ? report.candidates : []).map((candidate) => {
          const compact = {};
          for (const field of fields) {
            if (candidate && Object.prototype.hasOwnProperty.call(candidate, field)) compact[field] = candidate[field];
          }
          return compact;
        });
        return jsonResponse({
          report_type: report.report_type,
          schema_version: report.schema_version,
          generated_at_utc: report.generated_at_utc,
          source_state_generated_at_utc: report.source_state_generated_at_utc,
          application_version: report.application_version,
          radar: report.radar,
          universe: report.universe,
          market_context: report.market_context,
          market_context_freshness: report.market_context_freshness,
          market_context_warning: report.market_context_warning,
          candidate_count: report.candidate_count,
          candidates,
          interpretation_limits: report.interpretation_limits
        }, 200, {
          "X-Report-SHA256": record.metadata?.sha256 || "",
          "X-Report-Generated-At": record.metadata?.generated_at_utc || "",
          "X-Report-Type": "analysis-summary"
        });
      } catch {
        return jsonResponse({ ok: false, error: "Analiz özeti oluşturulamadı." }, 500);
      }
    }

    const readPath = url.pathname.startsWith("/read/") ? `/${url.pathname.slice(6)}` : url.pathname;
    const jsonReadRoute = JSON_READ_ROUTES[readPath];
    if (request.method === "GET" && jsonReadRoute) {
      return getStoredJsonReport(env, jsonReadRoute);
    }

    if (url.pathname === "/troubleshooting.zip" && request.method === "GET") {
      const record = await env.ANALYSIS_REPORTS.getWithMetadata(REPORT_KEYS.troubleshootingZip, "arrayBuffer");
      if (!record || !record.value) {
        return jsonResponse({ ok: false, error: "Henüz sorun giderme ZIP paketi yüklenmedi." }, 404);
      }
      return new Response(record.value, {
        status: 200,
        headers: {
          "Content-Type": "application/zip",
          "Content-Disposition": 'attachment; filename="firsat_kontrol_devir_latest.zip"',
          "Cache-Control": "no-store, max-age=0",
          "X-Report-SHA256": record.metadata?.sha256 || "",
          "X-Report-Generated-At": record.metadata?.generated_at_utc || "",
          "X-Content-Type-Options": "nosniff",
        },
      });
    }

    return jsonResponse({ ok: false, error: "Uç nokta bulunamadı." }, 404);
  },
};
