/**
 * SurfClock Backend (Google AI Studio & Google Cloud Run)
 *
 * Serves:
 *   - GET /api/surf : JSON telemetry & scoring payload polled by the ESP32-S3 SurfClock
 *   - GET /         : Live interactive SurfClock telemetry dashboard
 *   - GET /healthz  : Health check endpoint for Cloud Run
 *
 * Built with zero external dependencies (Node 20+ native http + fetch) and a
 * 10-minute in-memory Open-Meteo cache so 60-second ESP32 polls stay well within
 * Google Cloud Run's $0/month Always Free tier.
 */

const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const { URL } = require("node:url");

const PORT = Number(process.env.PORT) || 3000;
const CACHE_TTL_MS = 10 * 60 * 1000; // 10 minutes

// ============================================================================
// Configure Your 5 Local Surf Breaks (12, 2, 4, 8, and 10 o'clock on the dial)
// Tip: In Google AI Studio, simply ask Gemini:
//   "Update SPOTS to my 5 local beaches: [list your beaches]"
// ============================================================================
const SPOTS = [
  { pos: 1, name: "Long Reef", dial_text: "LONG REEF", angle: 0, lat: -33.742, lon: 151.311, facing: 70, swell_min: 40, swell_max: 130, wind_min: 240, wind_max: 300, min_s: 0.8, max_s: 3.5, period: 12 },
  { pos: 2, name: "Dee Why", dial_text: "DEE WHY", angle: 60, lat: -33.754, lon: 151.299, facing: 100, swell_min: 80, swell_max: 170, wind_min: 240, wind_max: 290, min_s: 0.8, max_s: 3.5, period: 12 },
  { pos: 3, name: "Curl Curl", dial_text: "CURL CURL", angle: 120, lat: -33.768, lon: 151.298, facing: 95, swell_min: 70, swell_max: 160, wind_min: 260, wind_max: 310, min_s: 0.6, max_s: 3.0, period: 12 },
  { pos: 4, name: "Freshwater", dial_text: "FRESHIE", angle: 240, lat: -33.780, lon: 151.291, facing: 85, swell_min: 70, swell_max: 150, wind_min: 250, wind_max: 300, min_s: 0.7, max_s: 2.2, period: 11 },
  { pos: 5, name: "Queenscliff", dial_text: "QUEENSCLIFF", angle: 300, lat: -33.791, lon: 151.289, facing: 80, swell_min: 60, swell_max: 150, wind_min: 240, wind_max: 300, min_s: 0.6, max_s: 2.5, period: 11 }
];

const DASHBOARD_HTML = fs.readFileSync(path.join(__dirname, "dashboard.html"), "utf8");

// In-memory cache to avoid hitting Open-Meteo on every 60-second ESP32 poll
let cachedPayload = null;
let lastFetchMs = 0;

function angleDiff(a, b) {
  const diff = Math.abs((a - b) % 360);
  return diff > 180 ? 360 - diff : diff;
}

function inWindow(angle, minD, maxD) {
  angle = ((angle % 360) + 360) % 360;
  minD = ((minD % 360) + 360) % 360;
  maxD = ((maxD % 360) + 360) % 360;
  return minD <= maxD ? (angle >= minD && angle <= maxD) : (angle >= minD || angle <= maxD);
}

async function fetchSpotConditions(spot) {
  const mUrl = `https://marine-api.open-meteo.com/v1/marine?latitude=${spot.lat}&longitude=${spot.lon}&hourly=wave_height,wave_direction,wave_period,swell_wave_height,swell_wave_direction,swell_wave_period&timezone=auto`;
  const wUrl = `https://api.open-meteo.com/v1/forecast?latitude=${spot.lat}&longitude=${spot.lon}&current=wind_speed_10m,wind_direction_10m,wind_gusts_10m&timezone=auto`;

  const headers = { "User-Agent": "SurfClock-CloudRun/1.0" };
  const [mRes, wRes] = await Promise.all([
    fetch(mUrl, { headers, signal: AbortSignal.timeout(8000) }),
    fetch(wUrl, { headers, signal: AbortSignal.timeout(8000) })
  ]);

  if (!mRes.ok || !wRes.ok) {
    throw new Error(`Open-Meteo HTTP error (${mRes.status} / ${wRes.status})`);
  }

  const mData = await mRes.json();
  const wData = await wRes.json();

  const mh = mData.hourly || {};
  const wc = wData.current || {};

  const waveHeight = mh.wave_height?.[0] || 0.0;
  const wavePeriod = mh.wave_period?.[0] || 0.0;
  const waveDir = mh.wave_direction?.[0] || 0.0;
  const swellHeight = mh.swell_wave_height?.[0] || waveHeight;
  const swellPeriod = mh.swell_wave_period?.[0] || wavePeriod;
  const swellDir = mh.swell_wave_direction?.[0] || waveDir;

  const windSpeed = wc.wind_speed_10m || 0.0;
  const windDir = wc.wind_direction_10m || 0.0;

  return {
    swell_h: swellHeight,
    swell_p: swellPeriod,
    swell_d: swellDir,
    wind_spd: windSpeed,
    wind_d: windDir
  };
}

// Oceanographic swell exposure & headland bathymetry factor
function getSwellExposure(spotPos, swellDir) {
  if (spotPos === 3) {
    if (swellDir >= 130 && swellDir <= 200) return 1.15;
    if (swellDir >= 60 && swellDir <= 130) return 1.05;
    return 1.0;
  } else if (spotPos === 4) {
    if (swellDir >= 140 && swellDir <= 210) return 0.80;
    if (swellDir >= 75 && swellDir <= 115) return 0.95;
    return 0.85;
  } else if (spotPos === 5) {
    if (swellDir >= 140 && swellDir <= 210) return 0.82;
    if (swellDir >= 50 && swellDir <= 110) return 0.95;
    return 0.90;
  } else if (spotPos === 1) {
    return (swellDir >= 40 && swellDir <= 130) ? 1.10 : 1.00;
  }
  return 1.0;
}

function scoreSpot(spot, cond) {
  const exposure = getSwellExposure(spot.pos, cond.swell_d);
  const effSwellH = cond.swell_h * exposure;

  // Height score (0-35)
  const idealS = (spot.min_s + spot.max_s) / 2;
  let hScore = 0;
  if (effSwellH < spot.min_s) {
    hScore = Math.max(0, 15 * (effSwellH / Math.max(0.1, spot.min_s)));
  } else if (effSwellH <= spot.max_s) {
    const ratio = 1.0 - Math.abs(effSwellH - idealS) / (spot.max_s - spot.min_s);
    hScore = 25 + 10 * Math.max(0, ratio);
  } else {
    hScore = Math.max(5, 30 - (effSwellH - spot.max_s) * 10);
  }

  // Period score (0-25)
  let pScore = 0;
  if (cond.swell_p >= 14) pScore = 25;
  else if (cond.swell_p >= 11) pScore = 20 + (cond.swell_p - 11) * 1.66;
  else if (cond.swell_p >= 8) pScore = 12 + (cond.swell_p - 8) * 2.66;
  else pScore = Math.max(2, cond.swell_p * 1.5);

  // Direction score (0-15)
  let dScore = 0;
  if (inWindow(cond.swell_d, spot.swell_min, spot.swell_max)) {
    dScore = 15;
  } else {
    const diff = Math.min(angleDiff(cond.swell_d, spot.swell_min), angleDiff(cond.swell_d, spot.swell_max));
    dScore = Math.max(0, 15 - diff * 0.25);
  }

  // Wind score (-15 to 25)
  const offshoreCenter = (spot.facing + 180) % 360;
  const windDiff = angleDiff(cond.wind_d, offshoreCenter);
  let wScore = 0;
  let wText = "Light";

  if (cond.wind_spd < 7) {
    const alignment = 1.0 - (windDiff / 180.0);
    wScore = 21.0 + 3.0 * alignment;
    wText = "Glassy";
  } else if (inWindow(cond.wind_d, spot.wind_min, spot.wind_max) || windDiff < 45) {
    wScore = cond.wind_spd <= 20 ? 25 : 18;
    wText = "Clean Offshore";
  } else if (windDiff < 90) {
    wScore = cond.wind_spd < 15 ? 12 : 4;
    wText = "Cross-shore";
  } else {
    wScore = cond.wind_spd < 12 ? 5 : (cond.wind_spd < 22 ? -5 : -15);
    wText = cond.wind_spd >= 22 ? "Blown Out" : "Onshore Chop";
  }

  const rawTotal = hScore + pScore + dScore + wScore;
  const total = Math.max(0, Math.min(100, Math.round(rawTotal)));
  return { score: total, rawScore: rawTotal, wind_condition: wText, effective_swell_h: effSwellH };
}

async function evaluateAllSpots(forceRefresh = false) {
  const now = Date.now();
  if (!forceRefresh && cachedPayload && (now - lastFetchMs) < CACHE_TTL_MS) {
    return cachedPayload;
  }

  const results = await Promise.all(SPOTS.map(async (s) => {
    try {
      const c = await fetchSpotConditions(s);
      const sc = scoreSpot(s, c);
      return {
        pos: s.pos,
        name: s.name,
        dial_text: s.dial_text,
        angle: s.angle,
        score: sc.score,
        raw_score: Math.round(sc.rawScore * 100) / 100,
        effective_swell_h: Math.round(sc.effective_swell_h * 100) / 100,
        cond: sc.wind_condition,
        conditions: {
          swell_height_m: Math.round(c.swell_h * 100) / 100,
          swell_period_s: Math.round(c.swell_p * 10) / 10,
          swell_direction_deg: Math.round(c.swell_d),
          wind_speed_kmh: Math.round(c.wind_spd * 10) / 10,
          wind_direction_deg: Math.round(c.wind_d)
        }
      };
    } catch {
      return { pos: s.pos, name: s.name, dial_text: s.dial_text, angle: s.angle, score: 50, raw_score: 50, cond: "Estimated" };
    }
  }));

  results.sort((a, b) => (b.raw_score ?? b.score) - (a.raw_score ?? a.score));
  const winner = results[0];

  const rawRating = Math.max(1.0, Math.min(10.0, winner.score / 10.0));
  const ratingFloat = Math.round(rawRating * 10) / 10;
  const ratingInt = Math.max(1, Math.min(10, Math.round(rawRating)));

  cachedPayload = {
    beach_pos: winner.pos,
    beach_name: winner.name,
    dial_text: winner.dial_text,
    dial_angle: winner.angle,
    score: winner.score,
    conditions_rating: ratingFloat,
    conditions_int: ratingInt,
    wind_condition: winner.cond,
    timestamp: Math.floor(now / 1000),
    spots: results
  };
  lastFetchMs = now;
  return cachedPayload;
}

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type"
};

const server = http.createServer(async (req, res) => {
  if (req.method === "OPTIONS") {
    res.writeHead(204, CORS_HEADERS);
    res.end();
    return;
  }

  const url = new URL(req.url, `http://${req.headers.host || "localhost"}`);

  if (url.pathname === "/healthz") {
    res.writeHead(200, { "Content-Type": "text/plain", ...CORS_HEADERS });
    res.end("ok");
    return;
  }

  if (url.pathname === "/api/surf" || url.pathname === "/surf") {
    try {
      const force = url.searchParams.has("force");
      const payload = await evaluateAllSpots(force);
      const body = JSON.stringify(payload, null, 2);
      res.writeHead(200, { "Content-Type": "application/json; charset=utf-8", ...CORS_HEADERS });
      res.end(body);
    } catch (err) {
      res.writeHead(500, { "Content-Type": "application/json; charset=utf-8", ...CORS_HEADERS });
      res.end(JSON.stringify({ error: String(err.message || err) }));
    }
    return;
  }

  if (url.pathname === "/" || url.pathname === "/index.html") {
    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8", ...CORS_HEADERS });
    res.end(DASHBOARD_HTML);
    return;
  }

  res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8", ...CORS_HEADERS });
  res.end("SurfClock Backend Active. Endpoints: / (dashboard), /api/surf (ESP32 JSON)");
});

server.listen(PORT, "0.0.0.0", () => {
  console.log(`🌊 SurfClock Backend listening on http://0.0.0.0:${PORT}`);
  console.log(`   Dashboard : http://localhost:${PORT}/`);
  console.log(`   ESP32 API : http://localhost:${PORT}/api/surf`);
});
