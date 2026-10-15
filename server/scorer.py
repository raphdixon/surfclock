import json
import math
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional

def angle_diff(a: float, b: float) -> float:
    """Returns absolute minimal difference between two angles in degrees (0 to 180)."""
    diff = (a - b) % 360
    if diff > 180:
        diff = 360 - diff
    return diff

def is_angle_in_window(angle: float, min_deg: float, max_deg: float) -> bool:
    """Checks if an angle lies within a circular window [min_deg, max_deg]."""
    angle = angle % 360
    min_deg = min_deg % 360
    max_deg = max_deg % 360
    if min_deg <= max_deg:
        return min_deg <= angle <= max_deg
    else:
        return angle >= min_deg or angle <= max_deg

def get_swell_exposure(spot_pos: int, swell_dir: float) -> float:
    """Calculates headland sheltering and exposure multiplier for each bay."""
    if spot_pos == 3: # Curl Curl: open swell magnet
        if 130 <= swell_dir <= 200: return 1.15
        if 60 <= swell_dir <= 130: return 1.05
        return 1.0
    elif spot_pos == 4: # Freshwater: enclosed protected cove
        if 140 <= swell_dir <= 210: return 0.80 # S swell headland wrap penalty
        if 75 <= swell_dir <= 115: return 0.95  # Direct East opens the bay
        return 0.85 # NE sheltered
    elif spot_pos == 5: # Queenscliff: sheltered bight / bombie
        if 140 <= swell_dir <= 210: return 0.82 # South swell wrap
        if 50 <= swell_dir <= 110: return 0.95  # E/NE swell direct
        return 0.90
    elif spot_pos == 1: # Long Reef: exposed reef
        return 1.10 if 40 <= swell_dir <= 130 else 1.00
    return 1.0 # Dee Why

class SurfScorer:
    def __init__(self, spots_file: str):
        with open(spots_file, 'r') as f:
            self.spots: List[Dict[str, Any]] = json.load(f)
        self.cached_scores: Optional[Dict[str, Any]] = None
        self.last_fetch_time: float = 0
        self.cache_ttl_seconds: float = 600  # 10 minutes cache
        self.override_pos: Optional[int] = None

    def set_override(self, pos: Optional[int]):
        """Manually override the winning beach position (1-12) or set to None to clear."""
        self.override_pos = pos

    def fetch_conditions_for_spot(self, spot: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch real-time marine and weather data from Open-Meteo."""
        lat = spot["lat"]
        lon = spot["lon"]
        
        marine_url = (
            f"https://marine-api.open-meteo.com/v1/marine?"
            f"latitude={lat}&longitude={lon}&current="
            f"wave_height,wave_direction,wave_period,"
            f"swell_wave_height,swell_wave_direction,swell_wave_period,"
            f"wind_wave_height,wind_wave_direction,wind_wave_period,"
            f"secondary_swell_wave_height,secondary_swell_wave_period,secondary_swell_wave_direction&timezone=auto"
        )
        weather_url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&current="
            f"wind_speed_10m,wind_direction_10m,wind_gusts_10m&timezone=auto"
        )
        
        headers = {"User-Agent": "SurfClock-ScoringEngine/1.0"}
        
        # Parallel fetch for marine & weather
        def fetch_url(url):
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                return json.loads(resp.read().decode())

        with ThreadPoolExecutor(max_workers=2) as ex:
            f_m = ex.submit(fetch_url, marine_url)
            f_w = ex.submit(fetch_url, weather_url)
            marine_data = f_m.result()
            weather_data = f_w.result()

        mc = marine_data.get("current", {})
        wc = weather_data.get("current", {})
        
        sw1_h = mc.get("swell_wave_height") or 0.0
        sw2_h = mc.get("secondary_swell_wave_height") or 0.0
        ww_h = mc.get("wind_wave_height") or 0.0
        wave_height = mc.get("wave_height") or sw1_h
        
        combined_swell_h = math.sqrt(sw1_h ** 2 + sw2_h ** 2 + 0.25 * (ww_h ** 2))
        swell_height = max(sw1_h, combined_swell_h, 0.85 * wave_height)
            
        raw_period = max(mc.get("swell_wave_period") or 0.0, mc.get("wave_period") or 0.0)
        swell_period = raw_period * 1.22  # Convert ECWAM Mean Period (Tm) to Peak Period (Tp)
            
        swell_dir = mc.get("swell_wave_direction")
        if swell_dir is None:
            swell_dir = mc.get("wave_direction") or spot.get("facing_deg", 90.0)
            
        wind_speed = wc.get("wind_speed_10m", 0.0)
        wind_dir = wc.get("wind_direction_10m", 0.0)
        wind_gusts = wc.get("wind_gusts_10m", 0.0)
        
        return {
            "wave_height_m": round(wave_height, 2),
            "swell_height_m": round(swell_height, 2),
            "swell_period_s": round(swell_period, 1),
            "swell_direction_deg": round(swell_dir, 0),
            "wind_wave_height_m": round(ww_h, 2),
            "wind_speed_kmh": round(wind_speed, 1),
            "wind_direction_deg": round(wind_dir, 0),
            "wind_gusts_kmh": round(wind_gusts, 1),
        }

    def score_spot(self, spot: Dict[str, Any], cond: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate Surfline-calibrated LOTUS suitability score (0-100) from nearshore physics."""
        swell_h = cond["swell_height_m"]
        swell_p = cond["swell_period_s"]
        swell_d = cond["swell_direction_deg"]
        wind_spd = cond["wind_speed_kmh"]
        wind_d = cond["wind_direction_deg"]
        wind_wave_h = cond.get("wind_wave_height_m", 0.0)
        
        # 1. Directional refraction
        facing = spot.get("facing_deg", 90.0)
        swell_diff = angle_diff(swell_d, facing)
        rad = (min(140.0, swell_diff) * math.pi) / 180.0
        refraction = 0.52 + 0.82 * (max(0.0, math.cos(rad * 0.75)) ** 1.15)
        
        # 2. Period shoaling: Komar-Gaughan law (Tp / 10.5)^0.35
        clamped_p = max(4.0, min(20.0, swell_p))
        shoaling = (clamped_p / 10.5) ** 0.35
        
        # 3. Bay / headland bathymetry multiplier
        exposure = get_swell_exposure(spot["pos"], swell_d)
        hb = swell_h * refraction * shoaling * exposure
        
        # 4. Base wave size rating on Surfline 0..6 scale
        max_s = spot.get("max_swell_m", 3.2)
        if hb < 0.25:
            size_rating = (hb / 0.25) * 0.7
        elif hb < 0.60:
            size_rating = 0.70 + ((hb - 0.25) / 0.35) * 1.05
        elif hb < 1.20:
            size_rating = 1.75 + ((hb - 0.60) / 0.60) * 1.05
        elif hb <= max_s:
            span = max(0.8, max_s - 1.20)
            size_rating = 2.80 + min(1.25, ((hb - 1.20) / span) * 1.15)
        else:
            size_rating = max(1.4, 3.95 - (hb - max_s) * 0.65)
            
        # 5. Swell period quality adjustment (-0.40 to +0.85), gated by wave size
        if clamped_p < 7.0:
            period_adj = -0.40 + ((clamped_p - 4.0) / 3.0) * 0.20
        elif clamped_p < 10.0:
            period_adj = -0.20 + ((clamped_p - 7.0) / 3.0) * 0.25
        elif clamped_p < 14.0:
            period_adj = 0.05 + ((clamped_p - 10.0) / 4.0) * 0.45
        else:
            period_adj = 0.50 + min(0.35, ((clamped_p - 14.0) / 6.0) * 0.35)
            
        size_gate = min(1.0, hb / 0.65)
        period_adj *= size_gate

        # 6. Wind speed x direction adjustment
        offshore_center = (facing + 180) % 360
        wind_diff_from_offshore = angle_diff(wind_d, offshore_center)
        in_offshore_window = is_angle_in_window(wind_d, spot["optimal_wind_dir_min"], spot["optimal_wind_dir_max"])
        
        if wind_spd < 7.0:
            alignment = 1.0 - (wind_diff_from_offshore / 180.0)
            wind_adj = (0.35 + 0.15 * alignment) * size_gate
            wind_cond_text = "Glassy"
        elif in_offshore_window or wind_diff_from_offshore <= 50:
            wind_cond_text = "Clean Offshore"
            if wind_spd <= 18.0:
                wind_adj = (0.50 + 0.15 * (1.0 - min(50.0, wind_diff_from_offshore) / 50.0)) * size_gate
            elif wind_spd <= 30.0:
                wind_adj = (0.50 - ((wind_spd - 18.0) / 12.0) * 0.75) * size_gate
            else:
                wind_adj = -0.30 - min(1.0, (wind_spd - 30.0) / 20.0) * 0.85
                wind_cond_text = "Strong Offshore"
        elif wind_diff_from_offshore <= 100:
            wind_cond_text = "Cross-shore"
            cross_severity = (wind_diff_from_offshore - 50.0) / 50.0
            if wind_spd <= 12.0:
                wind_adj = -0.05 - 0.20 * cross_severity
            elif wind_spd <= 22.0:
                wind_adj = -0.25 - ((wind_spd - 12.0) / 10.0) * (0.60 + 0.25 * cross_severity)
            else:
                wind_adj = -0.95 - min(1.15, ((wind_spd - 22.0) / 15.0) * 1.15)
                if wind_spd >= 28.0:
                    wind_cond_text = "Blown Out"
        else:
            wind_cond_text = "Blown Out" if wind_spd >= 22.0 else "Onshore Chop"
            if wind_spd <= 11.0:
                wind_adj = -0.15 - ((wind_spd - 7.0) / 4.0) * 0.25
            elif wind_spd <= 20.0:
                wind_adj = -0.40 - ((wind_spd - 11.0) / 9.0) * 0.70
            else:
                wind_adj = -1.10 - min(1.15, ((wind_spd - 20.0) / 15.0) * 1.15)

        chop_penalty = 0.0
        if wind_wave_h > 0.35 and swell_h > 0:
            chop_ratio = wind_wave_h / max(0.4, swell_h)
            if chop_ratio > 0.6 and wind_diff_from_offshore > 55:
                chop_penalty = min(0.45, (chop_ratio - 0.6) * 0.40)

        rating_0_to_6 = max(0.0, min(6.0, size_rating + period_adj + wind_adj - chop_penalty - 0.14))
        total = 7.5 + (rating_0_to_6 / 6.0) * 86.5
        final_score = int(max(0, min(100, round(total))))
        
        return {
            "score": final_score,
            "raw_score": round(total, 2),
            "effective_swell_h": round(hb, 2),
            "wind_condition": wind_cond_text,
            "sub_scores": {
                "size_rating_0_6": round(size_rating, 2),
                "period_adj_0_6": round(period_adj, 2),
                "wind_adj_0_6": round(wind_adj, 2),
                "chop_penalty_0_6": round(chop_penalty, 2)
            }
        }

    def _process_one_spot(self, spot: Dict[str, Any]) -> Dict[str, Any]:
        try:
            cond = self.fetch_conditions_for_spot(spot)
            scoring = self.score_spot(spot, cond)
        except Exception as e:
            cond = {"error": str(e), "swell_height_m": 1.2, "swell_period_s": 10.0, "swell_direction_deg": 120, "wind_speed_kmh": 10, "wind_direction_deg": 270}
            scoring = {"score": 50, "wind_condition": "Estimated", "sub_scores": {}}

        return {
            "pos": spot["pos"],
            "name": spot["name"],
            "score": scoring["score"],
            "raw_score": scoring.get("raw_score", scoring["score"]),
            "effective_swell_h": scoring.get("effective_swell_h", cond.get("swell_height_m", 0)),
            "wind_condition": scoring["wind_condition"],
            "conditions": cond,
            "sub_scores": scoring.get("sub_scores", {}),
            "description": spot.get("description", "")
        }

    def evaluate_all(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Evaluate conditions for all 12 spots concurrently."""
        now = time.time()
        if not force_refresh and self.cached_scores and (now - self.last_fetch_time < self.cache_ttl_seconds):
            result = dict(self.cached_scores)
            if self.override_pos is not None:
                result["override_active"] = True
                result["beach_pos"] = self.override_pos
            return result

        # Concurrent processing across all 12 spots
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(self._process_one_spot, self.spots))

        ranked = sorted(results, key=lambda x: x.get("raw_score", x["score"]), reverse=True)
        winner = ranked[0]
        
        payload = {
            "beach_pos": winner["pos"],
            "beach_name": winner["name"],
            "score": winner["score"],
            "wind_condition": winner["wind_condition"],
            "timestamp": int(now),
            "cache_ttl": self.cache_ttl_seconds,
            "override_active": False,
            "spots": sorted(results, key=lambda x: x["pos"])
        }

        self.cached_scores = payload
        self.last_fetch_time = now

        if self.override_pos is not None:
            payload["override_active"] = True
            payload["beach_pos"] = self.override_pos

        return payload
