# app.py
import os
import math
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from zoneinfo import ZoneInfo

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
BASE_URL = "https://world.openfoodfacts.net/api/v2"
WORKOUTS_COLLECTION = "workouts"  # legacy read-only collection
FIRESTORE_DISABLED = os.environ.get("FIRESTORE_DISABLED") == "1"

# -----------------------------------------------------------------------------
# FastAPI
# -----------------------------------------------------------------------------
app = FastAPI(title="Food & Activity API", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten for prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Time helpers
# -----------------------------------------------------------------------------
def now_iso() -> str:
    return datetime.now(ZoneInfo("America/Chicago")).isoformat()

def current_date_iso() -> str:
    return datetime.now(ZoneInfo("America/Chicago")).date().isoformat()

def safe_float(x, default=None):
    try:
        if x is None or (isinstance(x, str) and x.strip() == ""):
            return default
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except Exception:
        return default

# -----------------------------------------------------------------------------
# Firestore init (lazy)
# -----------------------------------------------------------------------------
_db = None
def get_db():
    global _db
    if FIRESTORE_DISABLED:
        return None
    if _db is not None:
        return _db
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore

        try:
            firebase_admin.get_app()
        except ValueError:
            cred_path = "./firebase-admin.json"
            if cred_path and os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
            else:
                cred = credentials.ApplicationDefault()
            firebase_admin.initialize_app(cred)

        _db = firestore.client()
        return _db
    except Exception as e:
        print("Firestore init failed:", e)
        return None

# -----------------------------------------------------------------------------
# Firestore path helpers
# -----------------------------------------------------------------------------

def _ensure_db_or_503():
    db = get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Firestore unavailable")
    return db

def _parse_amount(val) -> float:
    """
    Try to parse water 'amount' as float.
    Ignores non-numeric strings (returns 0.0). Extend here if you want '8oz'/'250ml' parsing.
    """
    try:
        return float(val)
    except Exception:
        return 0.0

def get_daily_water_total(user_id: str, date_str: str) -> dict:
    db = _ensure_db_or_503()
    total = 0.0
    count = 0
    for snap in water_logs_collection(db, user_id, date_str).stream():
        data = snap.to_dict() or {}
        total += _parse_amount(data.get("amount"))
        count += 1
    return {"user_id": user_id, "date": date_str, "total_water": total, "entries": count}

def get_daily_workout_total(user_id: str, date_str: str) -> dict:
    db = _ensure_db_or_503()
    total = 0.0
    count = 0
    for snap in workout_logs_collection(db, user_id, date_str).stream():
        data = snap.to_dict() or {}
        try:
            val = float(data.get("calories_burned"))
        except Exception:
            val = 0.0
        total += val
        count += 1
    return {"user_id": user_id, "date": date_str, "total_calories_burned": total, "entries": count}

def get_daily_nutrition_totals(user_id: str, date_str: str) -> dict:
    db = _ensure_db_or_503()
    totals = {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
    count = 0
    for snap in food_logs_collection(db, user_id, date_str).stream():
        data = snap.to_dict() or {}
        for k in ("calories", "protein", "carbs", "fat"):
            try:
                v = float(data.get(k)) if data.get(k) is not None else 0.0
            except Exception:
                v = 0.0
            totals[k] += v
        count += 1
    # round to 2 decimals for display
    for k in totals:
        totals[k] = round(totals[k], 2)
    totals.update({"user_id": user_id, "date": date_str, "entries": count})
    return totals


def food_logs_collection(db, user_id: str, date_str: str):
    return (
        db.collection("Users")
        .document(user_id)
        .collection("FoodLogs")
        .document(date_str)
        .collection("food")
    )

def water_logs_collection(db, user_id: str, date_str: str):
    return (
        db.collection("Users")
        .document(user_id)
        .collection("FoodLogs")
        .document(date_str)
        .collection("water")
    )

def workout_logs_collection(db, user_id: str, date_str: str):
    return (
        db.collection("Users")
        .document(user_id)
        .collection("FoodLogs")
        .document(date_str)
        .collection("workout")
    )

# -----------------------------------------------------------------------------
# Firestore write utilities
# -----------------------------------------------------------------------------
def log_food_to_firestore(user_id: str, date_str: str, dt_iso: str, payload: Dict[str, Any]) -> bool:
    # Users/{user_id}/FoodLogs/{date}/food/{datetime}
    db = get_db()
    if db is None:
        print("Firestore unavailable; skipping food log write.")
        return False
    try:
        food_logs_collection(db, user_id, date_str).document(dt_iso).set(payload, merge=True)
        return True
    except Exception as e:
        print(f"Failed to write food log: {e}")
        return False

def log_water_to_firestore(user_id: str, date_str: str, dt_iso: str, amount) -> bool:
    # Users/{user_id}/FoodLogs/{date}/water/{datetime}
    db = get_db()
    if db is None:
        print("Firestore unavailable; skipping water log write.")
        return False
    try:
        water_logs_collection(db, user_id, date_str).document(dt_iso).set({"amount": amount}, merge=True)
        return True
    except Exception as e:
        print(f"Failed to write water log: {e}")
        return False

def log_workout_to_firestore(user_id: str, date_str: str, dt_iso: str, calories_burned: float) -> bool:
    # Users/{user_id}/FoodLogs/{date}/workout/{datetime}
    db = get_db()
    if db is None:
        print("Firestore unavailable; skipping workout log write.")
        return False
    try:
        workout_logs_collection(db, user_id, date_str).document(dt_iso).set(
            {"calories_burned": calories_burned}, merge=True
        )
        return True
    except Exception as e:
        print(f"Failed to write workout log: {e}")
        return False

# -----------------------------------------------------------------------------
# OpenFoodFacts helpers
# -----------------------------------------------------------------------------
def extract_nutrition_from_off(product: Dict[str, Any]) -> Dict[str, Optional[float]]:
    nutr = product.get("nutriments", {}) or {}

    kcal = safe_float(nutr.get("energy-kcal_serving"))
    if kcal is None:
        kcal = safe_float(nutr.get("energy-kcal_100g"))
    if kcal is None:
        kj_serv = safe_float(nutr.get("energy_serving"))
        kj_100g = safe_float(nutr.get("energy_100g"))
        kj = kj_serv if kj_serv is not None else kj_100g
        if kj is not None:
            kcal = kj / 4.184

    protein = safe_float(nutr.get("proteins_serving")) or safe_float(nutr.get("proteins_100g"))
    carbs = safe_float(nutr.get("carbohydrates_serving")) or safe_float(nutr.get("carbohydrates_100g"))
    fat = safe_float(nutr.get("fat_serving")) or safe_float(nutr.get("fat_100g"))

    return {
        "calories": None if kcal is None else round(kcal, 2),
        "protein": None if protein is None else round(protein, 2),
        "carbs": None if carbs is None else round(carbs, 2),
        "fat": None if fat is None else round(fat, 2),
    }

# -----------------------------------------------------------------------------
# Core handlers
# -----------------------------------------------------------------------------
def handle_barcode(barcode: str, *, user_id: Optional[str] = None) -> Dict[str, Any]:
    if not barcode.isdigit():
        raise HTTPException(status_code=400, detail="Invalid barcode: must be digits.")

    url = f"{BASE_URL}/product/{barcode}.json"
    response = requests.get(url, timeout=12)
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"OpenFoodFacts error: {response.status_code}")

    data = response.json()
    if "product" not in data:
        raise HTTPException(status_code=404, detail=f"No product found for barcode {barcode}")

    product = data["product"]
    date_str = current_date_iso()
    created_at = now_iso()
    nutrition = extract_nutrition_from_off(product)

    result = {
        "type": "barcode",
        "id": barcode,
        "date": date_str,
        "name": product.get("product_name"),
        "brands": product.get("brands"),
        "categories": product.get("categories"),
        "nutriscore": product.get("nutriscore_grade"),
        "ingredients": [i.get("text") for i in (product.get("ingredients") or []) if "text" in i],
        "image_url": product.get("image_url"),
        "calories": nutrition["calories"],
        "protein": nutrition["protein"],
        "carbs": nutrition["carbs"],
        "fat": nutrition["fat"],
    }

    if user_id:
        payload = {
            "barcode": barcode,           # barcode is now a field
            "name": result["name"],
            "calories": nutrition["calories"],
            "protein": nutrition["protein"],
            "carbs": nutrition["carbs"],
            "fat": nutrition["fat"],
            "createdAt": created_at,
        }
        result["logged"] = log_food_to_firestore(user_id, date_str, created_at, payload)

    return result

def handle_workout_read(workout_id: str) -> Dict[str, Any]:
    # legacy read from top-level workouts/{id}
    db = get_db()
    if db is None:
        return {
            "type": "workout",
            "id": workout_id,
            "date": current_date_iso(),
            "error": "Firestore not available.",
        }
    doc_ref = db.collection(WORKOUTS_COLLECTION).document(workout_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail=f"Workout '{workout_id}' not found")
    data = doc.to_dict() or {}
    return {
        "type": "workout",
        "id": workout_id,
        "date": current_date_iso(),
        "calories_burned": data.get("calories_burned"),
    }

def handle_workout_log(calories_burned: float, *, user_id: Optional[str]) -> Dict[str, Any]:
    if user_id is None:
        raise HTTPException(status_code=400, detail="user_id is required to log a workout")
    if calories_burned is None:
        raise HTTPException(status_code=400, detail="calories_burned is required")
    try:
        calories = float(calories_burned)
    except Exception:
        raise HTTPException(status_code=400, detail="calories_burned must be numeric")

    date_str = current_date_iso()
    dt_iso = now_iso()
    logged = log_workout_to_firestore(user_id, date_str, dt_iso, calories)

    return {
        "type": "workout",
        "mode": "logged",
        "date": date_str,
        "datetime": dt_iso,
        "calories_burned": calories,
        "user_id": user_id,
        "logged": logged,
    }

def handle_water(water_str: str, *, user_id: Optional[str] = None) -> Dict[str, Any]:
    try:
        amount = float(water_str)
    except ValueError:
        amount = water_str  # leave as-is

    date_str = current_date_iso()
    dt_iso = now_iso()
    result = {
        "type": "water",
        "id": str(water_str),
        "date": date_str,
        "amount": amount,
        "status": "ok",
        "datetime": dt_iso,
    }
    if user_id:
        result["logged"] = log_water_to_firestore(user_id, date_str, dt_iso, amount)
    return result

def get_item_by_prefixed_id(prefixed_id: str, *, user_id: Optional[str] = None) -> Dict[str, Any]:
    if not prefixed_id or len(prefixed_id) < 2:
        raise HTTPException(status_code=400, detail="Expect 1-letter prefix followed by an ID/value.")
    prefix = prefixed_id[0].upper()
    identifier = prefixed_id[1:]

    if prefix == "B":
        return handle_barcode(identifier, user_id=user_id)
    elif prefix == "L":
        return handle_water(identifier, user_id=user_id)
    elif prefix == "W":
        # If W is followed by digits -> treat as a workout log (calories)
        if identifier.replace(".", "", 1).isdigit():
            return handle_workout_log(float(identifier), user_id=user_id)
        # Otherwise, treat as legacy workout read by document id
        return handle_workout_read(identifier)

    raise HTTPException(status_code=400, detail="Unknown prefix. Use B/W/L.")

# -----------------------------------------------------------------------------
# Pydantic models
# -----------------------------------------------------------------------------
class ScanRequest(BaseModel):
    prefixed_id: str = Field(..., example="B3017620422003")
    user_id: Optional[str] = Field(None, description="If provided, logs to FoodLogs")

class BarcodeRequest(BaseModel):
    barcode: str = Field(..., example="3017620422003")
    user_id: Optional[str] = None

class WaterRequest(BaseModel):
    amount: str = Field(..., example="25")  # accepts "25" or "25.0" or "8oz"
    user_id: Optional[str] = None

class WorkoutLogRequest(BaseModel):
    calories_burned: float = Field(..., example=250)
    user_id: str = Field(..., description="User id to log under")

# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"ok": True, "time": now_iso(), "firestore_enabled": not FIRESTORE_DISABLED}

@app.post("/scan")
def scan(req: ScanRequest):
    """
    B... → barcode scan (logs if user_id provided, stored at food/{datetime})
    L... → water log (logs if user_id provided, stored at water/{datetime})
    W### → workout log with calories (requires user_id), stored at workout/{datetime}
    Wabc → legacy workout read from workouts/{id}
    """
    return get_item_by_prefixed_id(req.prefixed_id, user_id=req.user_id)

@app.get("/scan")
def scan_q(prefixed_id: str = Query(...), user_id: Optional[str] = Query(None)):
    return get_item_by_prefixed_id(prefixed_id, user_id=user_id)

@app.post("/barcode")
def scan_barcode(req: BarcodeRequest):
    return handle_barcode(req.barcode, user_id=req.user_id)

@app.get("/workouts/{workout_id}")
def get_workout(workout_id: str):
    return handle_workout_read(workout_id)

@app.post("/water")
def log_water(req: WaterRequest):
    return handle_water(req.amount, user_id=req.user_id)

@app.post("/workout")
def log_workout(req: WorkoutLogRequest):
    return handle_workout_log(req.calories_burned, user_id=req.user_id)

from fastapi import Depends

def _resolve_date(date: Optional[str]) -> str:
    return date or current_date_iso()

@app.get("/totals/water")
def totals_water(user_id: str, date: Optional[str] = None):
    """
    Sum of water 'amount' for the specified day.
    Example: /totals/water?user_id=abc&date=2025-10-11
    """
    return get_daily_water_total(user_id, _resolve_date(date))

@app.get("/totals/workout")
def totals_workout(user_id: str, date: Optional[str] = None):
    """
    Sum of workout 'calories_burned' for the specified day.
    """
    return get_daily_workout_total(user_id, _resolve_date(date))

@app.get("/totals/nutrition")
def totals_nutrition(user_id: str, date: Optional[str] = None):
    """
    Sum of nutrition (calories, protein, carbs, fat) from all food entries for the day.
    """
    return get_daily_nutrition_totals(user_id, _resolve_date(date))

@app.get("/totals/day")
def totals_day(user_id: str, date: Optional[str] = None):
    """
    Convenience endpoint: returns water, workout, and nutrition totals together.
    """
    d = _resolve_date(date)
    water = get_daily_water_total(user_id, d)
    workout = get_daily_workout_total(user_id, d)
    nutrition = get_daily_nutrition_totals(user_id, d)
    return {
        "user_id": user_id,
        "date": d,
        "water": {"total": water["total_water"], "entries": water["entries"]},
        "workout": {"calories_burned": workout["total_calories_burned"], "entries": workout["entries"]},
        "nutrition": {
            "calories": nutrition["calories"],
            "protein": nutrition["protein"],
            "carbs": nutrition["carbs"],
            "fat": nutrition["fat"],
            "entries": nutrition["entries"],
        },
    }

