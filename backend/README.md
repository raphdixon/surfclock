# 🌊 SurfClock Backend (Google AI Studio & Cloud Run)

This folder is a self-contained **Google AI Studio Build** & **Google Cloud Run** application that runs the Surfline-calibrated LOTUS scoring algorithm and serves both:
1. **`GET /api/surf`** — The lightweight JSON telemetry endpoint polled every 60 seconds by the physical ESP32-S3 SurfClock.
2. **`GET /`** — The live interactive SurfClock telemetry web dashboard.

It uses **zero external npm dependencies** (native Node 20+ `http` + `fetch`) and caches Open-Meteo marine/weather responses in memory for **10 minutes**, keeping CPU usage under ~2% of Google Cloud Run's **$0/month Always Free tier**.

---

## 🚀 Deploy Your Own in 60 Seconds via Google AI Studio

### Step 1: Download the Ready-to-Upload Zip
Download **[`surfclock-aistudio-backend.zip`](surfclock-aistudio-backend.zip)** from this folder.  
*(It is already packaged as a flat-root archive required by Google AI Studio's zip uploader.)*

### Step 2: Upload into Google AI Studio
1. Open the blank applet template in Code View: **[aistudio.google.com/apps/bundled/blank?showCode=true](https://aistudio.google.com/apps/bundled/blank?showCode=true)**
2. Click **Remix** in the top-right toolbar and name your app `SurfClock Backend`.
3. In the left **File explorer** panel, click **`+` (`Add items to file explorer`)** → **Upload Zip file** and select **`surfclock-aistudio-backend.zip`**.
4. Press **`Cmd+S`** (or **`Ctrl+S`**) to save and start the live preview.

### Step 3: Customize Your 5 Beaches with Gemini
Your 5 beaches live in **`spots.json`** (completely separate from the scoring math in `server.js`). Just prompt Gemini right inside AI Studio:
> *"Update `spots.json` for my 5 local breaks: [Your 5 Beaches] ordered clockwise at 0°, 60°, 120°, 240°, and 300°, with their GPS coordinates, seaward facing bearings, and offshore wind windows."*

### Step 4: 1-Click Deploy to Cloud Run
1. Click **🚀 Deploy to Cloud Run** in the top-right corner of Google AI Studio.
2. **Region:** Pick `us-central1` or `us-west1` (Tier 1 regions eligible for the **$0/month Always Free tier**).
3. **Authentication:** Enable **"Allow unauthenticated invocations"** so your ESP32 SurfClock can poll `/api/surf` over Wi-Fi without browser login cookies.
4. Copy your deployed Cloud Run URL (`https://<your-service>.run.app`) and point your SurfClock at it over USB serial (`115200` baud):
   ```text
   api https://<your-service>.run.app/api/surf
   ```

---

## 🧮 How the Surfline-Calibrated Algorithm Works

The scoring engine in `server.js` was calibrated against **2,520 hourly Surfline LOTUS forecasts** and **100 live global & Australian beaches** (achieving `94%` within-one-tier agreement and `+0.9` point bias):
- **Live 15-Minute Telemetry:** Fetches `current` Open-Meteo Marine (`swell_wave_height`, `secondary_swell_wave_height`, `wind_wave_height`, `swell_wave_period`) and Weather (`wind_speed_10m`, `wind_direction_10m`) data.
- **Spectral Peak Period ($T_p$):** Converts ECWAM mean period ($T_{m02}$) to peak spectral period ($T_p = 1.22 \times T_m$).
- **Nearshore Face Height ($H_b$):** Applies directional cosine refraction against each beach's `facing` bearing plus Komar-Gaughan period shoaling $(T_p / 10.5)^{0.35}$.
- **Wave-Size Gate:** Caps small surf (`<0.6m` / `1–2 ft`) near `POOR` / `POOR_TO_FAIR` even when winds are glassy.
- **Wind & Chop Matrix:** Rewards glassy (`<7 km/h`) and light offshore (`7–18 km/h`) winds; penalizes cross-shore/onshore winds and short-period wind-sea chop.

---

## 💻 Deploy via Terminal (`gcloud` CLI)

```bash
cd backend
gcloud run deploy surfclock --source . --region us-central1 --allow-unauthenticated
```

---

## 🧪 Run & Test Locally

```bash
cd backend
npm test     # Runs unit tests for spots.json and the Surfline LOTUS scorer
npm start    # Starts local server on http://localhost:3000
npm run zip  # Rebuilds surfclock-aistudio-backend.zip after local edits
```
- **Dashboard:** `http://localhost:3000/`
- **ESP32 JSON API:** `http://localhost:3000/api/surf` (append `?force=1` to bypass the 10-minute cache)
