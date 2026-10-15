# 🌊 SurfClock Backend (Google AI Studio & Cloud Run)

This folder is a self-contained **Google AI Studio Build** & **Google Cloud Run** application that powers both:
1. **`GET /api/surf`** — The lightweight JSON telemetry endpoint polled every 60 seconds by the physical ESP32-S3 SurfClock.
2. **`GET /`** — The live interactive SurfClock telemetry web dashboard.

It uses **zero external npm dependencies** (native Node 20+ `http` + `fetch`) and caches Open-Meteo marine/weather responses in memory for **10 minutes**, keeping CPU usage under ~2% of Google Cloud Run's **$0/month Always Free tier**.

---

## 🚀 Deploy in 60 Seconds via Google AI Studio (Recommended)

1. Open **[Google AI Studio → Build](https://aistudio.google.com/apps)** (`aistudio.google.com/apps`).
2. Create a new app and upload/import the files in this `backend/` folder (`server.js`, `dashboard.html`, `package.json`, `Dockerfile`, `metadata.json`).
3. *(Optional)* Customize your 5 beaches by prompting Gemini right inside AI Studio:
   > *"Update the `SPOTS` array in `server.js` for my 5 local breaks: [Your 5 Beaches] with their GPS coordinates, facing bearings, and offshore wind windows."*
4. Click **🚀 Deploy to Cloud Run** in the top-right corner of AI Studio:
   - **Region:** Pick `us-central1` or `us-west1` (Tier 1 regions eligible for the **$0/month Always Free tier**).
   - **Authentication:** Check **"Allow unauthenticated invocations"** so your ESP32 SurfClock can call `/api/surf` over Wi-Fi without browser login cookies.
5. Copy your deployed Cloud Run URL (`https://<your-service>.run.app`) and point your SurfClock at it over USB serial (`115200` baud):
   ```text
   api https://<your-service>.run.app/api/surf
   ```

---

## 💻 Deploy via Terminal (`gcloud` CLI)

```bash
cd backend
gcloud run deploy surfclock --source . --region us-central1 --allow-unauthenticated
```

---

## 🧪 Run Locally

```bash
cd backend
npm start
```
- **Dashboard:** `http://localhost:3000/`
- **ESP32 JSON API:** `http://localhost:3000/api/surf` (append `?force=1` to bypass the 10-minute cache)
