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
// Configure Your 5 Local Surf Breaks in spots.json (12, 2, 4, 8, and 10 o'clock)
// Tip: In Google AI Studio, simply ask Gemini:
//   "Update spots.json to my 5 local beaches: [list your beaches]"
// ============================================================================
const DEFAULT_SPOTS = [
  { pos: 1, name: "Long Reef", dial_text: "LONG REEF", angle: 0, lat: -33.742, lon: 151.311, facing: 70, swell_min: 40, swell_max: 130, wind_min: 240, wind_max: 300, min_s: 0.8, max_s: 3.5, period: 12 },
  { pos: 2, name: "Dee Why", dial_text: "DEE WHY", angle: 60, lat: -33.754, lon: 151.299, facing: 100, swell_min: 80, swell_max: 170, wind_min: 240, wind_max: 290, min_s: 0.8, max_s: 3.5, period: 12 },
  { pos: 3, name: "Curl Curl", dial_text: "CURL CURL", angle: 120, lat: -33.768, lon: 151.298, facing: 95, swell_min: 70, swell_max: 160, wind_min: 260, wind_max: 310, min_s: 0.6, max_s: 3.0, period: 12 },
  { pos: 4, name: "Freshwater", dial_text: "FRESHIE", angle: 240, lat: -33.780, lon: 151.291, facing: 85, swell_min: 70, swell_max: 150, wind_min: 250, wind_max: 300, min_s: 0.7, max_s: 2.2, period: 11 },
  { pos: 5, name: "Queenscliff", dial_text: "QUEENSCLIFF", angle: 300, lat: -33.791, lon: 151.289, facing: 80, swell_min: 60, swell_max: 150, wind_min: 240, wind_max: 300, min_s: 0.6, max_s: 2.5, period: 11 }
];

function loadSpots() {
  try {
    const raw = fs.readFileSync(path.join(__dirname, "spots.json"), "utf8");
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed.length > 0) return parsed;
  } catch (_) {}
  return DEFAULT_SPOTS;
}

const SPOTS = loadSpots();

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
  const mUrl = `https://marine-api.open-meteo.com/v1/marine?latitude=${spot.lat}&longitude=${spot.lon}&current=wave_height,wave_direction,wave_period,swell_wave_height,swell_wave_direction,swell_wave_period,wind_wave_height,wind_wave_direction,wind_wave_period,secondary_swell_wave_height,secondary_swell_wave_period,secondary_swell_wave_direction&timezone=auto`;
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

  const mc = mData.current || {};
  const wc = wData.current || {};

  const sw1H = mc.swell_wave_height || 0.0;
  const sw2H = mc.secondary_swell_wave_height || 0.0;
  const wwH = mc.wind_wave_height || 0.0;
  const totalH = mc.wave_height || sw1H;

  // Effective groundswell height: combine primary + secondary swell energy + 25% of wind-swell energy
  const combinedSwellH = Math.sqrt(sw1H * sw1H + sw2H * sw2H + 0.25 * wwH * wwH);
  const effSwellH = Math.max(sw1H, combinedSwellH, 0.85 * totalH);

  // Convert Open-Meteo ECWAM Mean Period (Tm) to Peak Spectral Period (Tp = 1.22 * Tm)
  const rawPeriod = Math.max(mc.swell_wave_period || 0.0, mc.wave_period || 0.0);
  const peakPeriod = rawPeriod * 1.22;

  const swellDir = mc.swell_wave_direction ?? mc.wave_direction ?? spot.facing;
  const windSpeed = wc.wind_speed_10m || 0.0;
  const windDir = wc.wind_direction_10m || 0.0;

  return {
    swell_h: effSwellH,
    swell_p: peakPeriod,
    swell_d: swellDir,
    wind_wave_h: wwH,
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

// Surfline-calibrated LOTUS scoring model:
// Shoals & refracts offshore swell to nearshore breaking face height (Hb),
// applies wave-size baseline + period quality + wind speed/direction grooming.
function scoreSpot(spot, cond) {
  const swellH = cond.swell_h || 0;
  const swellP = cond.swell_p || 0;
  const swellD = cond.swell_d ?? spot.facing;
  const windSpd = cond.wind_spd || 0;
  const windD = cond.wind_d ?? 0;
  const windWaveH = cond.wind_wave_h || 0;

  // 1. Directional refraction: cosine angular decay from spot facing bearing
  const swellDiff = angleDiff(swellD, spot.facing);
  const rad = (Math.min(140, swellDiff) * Math.PI) / 180;
  const refraction = 0.52 + 0.82 * Math.pow(Math.max(0, Math.cos(rad * 0.75)), 1.15);

  // 2. Period shoaling: Komar-Gaughan law (Tp / 10.5)^0.35
  const clampedP = Math.max(4.0, Math.min(20.0, swellP));
  const shoaling = Math.pow(clampedP / 10.5, 0.35);

  // 3. Bay / headland bathymetry multiplier
  const bayExposure = getSwellExposure(spot.pos, swellD);

  // Estimated nearshore breaking face height (meters)
  const hb = swellH * refraction * shoaling * bayExposure;

  // 4. Base wave size rating on Surfline 0..6 scale
  let sizeRating = 0;
  const maxS = spot.max_s || 3.2;
  if (hb < 0.25) {
    sizeRating = (hb / 0.25) * 0.7;
  } else if (hb < 0.60) {
    sizeRating = 0.70 + ((hb - 0.25) / 0.35) * 1.05;
  } else if (hb < 1.20) {
    sizeRating = 1.75 + ((hb - 0.60) / 0.60) * 1.05;
  } else if (hb <= maxS) {
    const span = Math.max(0.8, maxS - 1.20);
    sizeRating = 2.80 + Math.min(1.25, ((hb - 1.20) / span) * 1.15);
  } else {
    sizeRating = Math.max(1.4, 3.95 - (hb - maxS) * 0.65);
  }

  // 5. Swell Period Quality Adjustment (-0.40 to +0.85 on 0..6 scale), gated by wave size
  let periodAdj = 0;
  if (clampedP < 7.0) {
    periodAdj = -0.40 + ((clampedP - 4.0) / 3.0) * 0.20;
  } else if (clampedP < 10.0) {
    periodAdj = -0.20 + ((clampedP - 7.0) / 3.0) * 0.25;
  } else if (clampedP < 14.0) {
    periodAdj = 0.05 + ((clampedP - 10.0) / 4.0) * 0.45;
  } else {
    periodAdj = 0.50 + Math.min(0.35, ((clampedP - 14.0) / 6.0) * 0.35);
  }
  const sizeGate = Math.min(1.0, hb / 0.65);
  periodAdj *= sizeGate;

  // 6. Wind Speed x Direction Adjustment (-2.2 to +0.65 on 0..6 scale)
  const offshoreCenter = (spot.facing + 180) % 360;
  const windDiff = angleDiff(windD, offshoreCenter);
  let windAdj = 0;
  let wText = "Light";

  if (windSpd < 7.0) {
    const align = 1.0 - (windDiff / 180.0);
    windAdj = (0.35 + 0.15 * align) * sizeGate;
    wText = "Glassy";
  } else if (inWindow(windD, spot.wind_min, spot.wind_max) || windDiff <= 50) {
    wText = "Clean Offshore";
    if (windSpd <= 18.0) {
      windAdj = (0.50 + 0.15 * (1.0 - Math.min(50, windDiff) / 50.0)) * sizeGate;
    } else if (windSpd <= 30.0) {
      windAdj = (0.50 - ((windSpd - 18.0) / 12.0) * 0.75) * sizeGate;
    } else {
      windAdj = -0.30 - Math.min(1.0, (windSpd - 30.0) / 20.0) * 0.85;
      wText = "Strong Offshore";
    }
  } else if (windDiff <= 100) {
    wText = "Cross-shore";
    const crossSeverity = (windDiff - 50.0) / 50.0;
    if (windSpd <= 12.0) {
      windAdj = -0.05 - 0.20 * crossSeverity;
    } else if (windSpd <= 22.0) {
      windAdj = -0.25 - ((windSpd - 12.0) / 10.0) * (0.60 + 0.25 * crossSeverity);
    } else {
      windAdj = -0.95 - Math.min(1.15, ((windSpd - 22.0) / 15.0) * 1.15);
      if (windSpd >= 28.0) wText = "Blown Out";
    }
  } else {
    wText = windSpd >= 22.0 ? "Blown Out" : "Onshore Chop";
    if (windSpd <= 11.0) {
      windAdj = -0.15 - ((windSpd - 7.0) / 4.0) * 0.25;
    } else if (windSpd <= 20.0) {
      windAdj = -0.40 - ((windSpd - 11.0) / 9.0) * 0.70;
    } else {
      windAdj = -1.10 - Math.min(1.15, ((windSpd - 20.0) / 15.0) * 1.15);
    }
  }

  // 7. Wind-wave chop penalty when short-period wind-sea swamps groundswell
  let chopPenalty = 0;
  if (windWaveH > 0.35 && swellH > 0) {
    const chopRatio = windWaveH / Math.max(0.4, swellH);
    if (chopRatio > 0.6 && windDiff > 55) {
      chopPenalty = Math.min(0.45, (chopRatio - 0.6) * 0.40);
    }
  }

  const rating0to6 = Math.max(0.0, Math.min(6.0, sizeRating + periodAdj + windAdj - chopPenalty - 0.14));
  const rawTotal = 7.5 + (rating0to6 / 6.0) * 86.5;
  const total = Math.max(0, Math.min(100, Math.round(rawTotal)));
  return { score: total, rawScore: rawTotal, wind_condition: wText, effective_swell_h: hb };
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

if (require.main === module) {
  server.listen(PORT, "0.0.0.0", () => {
    console.log(`🌊 SurfClock Backend listening on http://0.0.0.0:${PORT}`);
    console.log(`   Dashboard : http://localhost:${PORT}/`);
    console.log(`   ESP32 API : http://localhost:${PORT}/api/surf`);
  });
}

module.exports = { SPOTS, scoreSpot, fetchSpotConditions, evaluateAllSpots };
