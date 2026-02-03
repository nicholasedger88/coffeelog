from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from flask import Flask, flash, jsonify, redirect, render_template, request, url_for

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "coffeelog.db"

ALLOWED_GRINDERS = ["Aergrind (Nicholas)", "Belinda’s grinder"]
AERGRIND_SETTINGS = ["Aergrind Fine", "Aergrind Medium"]
BELINDA_SETTINGS = [str(i) for i in range(1, 13)]
ALLOWED_BREW_STYLES = ["Aeropress", "Moka pot", "V60"]
ALLOWED_PROCESSES = ["washed", "natural", "anaerobic", "honey", "experimental"]
ELEVATION_API = "https://api.open-elevation.com/api/v1/lookup"

app = Flask(__name__)
app.secret_key = "coffee-log-mvp"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS coffees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    brand TEXT,
    varietal TEXT,
    origin_region TEXT,
    altitude_m INTEGER,
    latitude REAL,
    longitude REAL,
    location TEXT,
    country TEXT,
    process TEXT,
    flavours TEXT,
    rating INTEGER NOT NULL,
    grinder TEXT,
    grind_setting TEXT,
    brew_style TEXT,
    created_at TEXT NOT NULL
);
"""


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_db()
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()


def normalize_flavours(raw: str) -> str:
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    return ", ".join(parts)


def parse_optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def parse_optional_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def validate_payload(form: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    data: dict[str, Any] = {}

    date_value = form.get("date", "").strip()
    if not date_value:
        errors.append("Date is required.")
    else:
        data["date"] = date_value

    rating_value = form.get("rating", "").strip()
    if not rating_value:
        errors.append("Rating is required.")
    else:
        try:
            rating = int(rating_value)
            if rating < 1 or rating > 5:
                raise ValueError
            data["rating"] = rating
        except ValueError:
            errors.append("Rating must be between 1 and 5.")

    grinder = form.get("grinder", "").strip()
    if grinder and grinder not in ALLOWED_GRINDERS:
        errors.append("Grinder must be one of the allowed options.")
    data["grinder"] = grinder

    grind_setting = form.get("grind_setting", "").strip()
    if grinder == "Aergrind (Nicholas)" and grind_setting not in AERGRIND_SETTINGS:
        errors.append("Choose a valid Aergrind setting.")
    if grinder == "Belinda’s grinder" and grind_setting not in BELINDA_SETTINGS:
        errors.append("Choose a valid Belinda setting.")
    data["grind_setting"] = grind_setting

    brew_style = form.get("brew_style", "").strip()
    if brew_style and brew_style not in ALLOWED_BREW_STYLES:
        errors.append("Brew style must be one of the allowed options.")
    data["brew_style"] = brew_style

    altitude_m = parse_optional_int(form.get("altitude_m"))
    if altitude_m is not None:
        if altitude_m <= 0 or altitude_m > 9000:
            errors.append("Altitude must be between 1 and 9000 meters.")
    data["altitude_m"] = altitude_m

    latitude = parse_optional_float(form.get("latitude"))
    longitude = parse_optional_float(form.get("longitude"))
    if latitude is not None and (latitude < -90 or latitude > 90):
        errors.append("Latitude must be between -90 and 90.")
    if longitude is not None and (longitude < -180 or longitude > 180):
        errors.append("Longitude must be between -180 and 180.")
    data["latitude"] = latitude
    data["longitude"] = longitude

    data["brand"] = form.get("brand", "").strip()
    data["varietal"] = form.get("varietal", "").strip()
    data["origin_region"] = form.get("origin_region", "").strip()
    data["country"] = form.get("country", "").strip()
    data["location"] = form.get("location", "").strip()
    data["process"] = form.get("process", "").strip()
    data["flavours"] = normalize_flavours(form.get("flavours", ""))

    return data, errors


def get_distinct_values(field: str) -> list[str]:
    if field not in {
        "brand",
        "varietal",
        "origin_region",
        "country",
        "location",
        "process",
        "brew_style",
    }:
        return []
    conn = get_db()
    rows = conn.execute(
        f"SELECT DISTINCT {field} FROM coffees WHERE {field} IS NOT NULL AND {field} != '' ORDER BY {field}"
    ).fetchall()
    conn.close()
    return [row[field] for row in rows]


def build_filters_from_request(args: dict[str, str]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if args.get("date_from"):
        clauses.append("date >= ?")
        params.append(args["date_from"])
    if args.get("date_to"):
        clauses.append("date <= ?")
        params.append(args["date_to"])

    for field in [
        "brand",
        "varietal",
        "origin_region",
        "country",
        "process",
        "brew_style",
    ]:
        value = args.get(field)
        if value:
            clauses.append(f"{field} = ?")
            params.append(value)

    if args.get("min_rating"):
        try:
            min_rating = int(args["min_rating"])
            clauses.append("rating >= ?")
            params.append(min_rating)
        except ValueError:
            pass

    where = ""
    if clauses:
        where = " WHERE " + " AND ".join(clauses)
    return where, params


def fetch_coffees(filters: tuple[str, list[Any]]) -> list[sqlite3.Row]:
    where, params = filters
    conn = get_db()
    rows = conn.execute(
        f"SELECT * FROM coffees{where} ORDER BY date DESC, created_at DESC",
        params,
    ).fetchall()
    conn.close()
    return rows


@app.route("/")
def index() -> Any:
    return redirect(url_for("add_coffee"))


@app.route("/add", methods=["GET", "POST"])
def add_coffee() -> Any:
    init_db()
    if request.method == "POST":
        data, errors = validate_payload(request.form)
        if errors:
            for error in errors:
                flash(error, "error")
        else:
            conn = get_db()
            conn.execute(
                """
                INSERT INTO coffees (
                    date, brand, varietal, origin_region, altitude_m, latitude, longitude,
                    location, country, process, flavours, rating, grinder, grind_setting,
                    brew_style, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["date"],
                    data["brand"],
                    data["varietal"],
                    data["origin_region"],
                    data["altitude_m"],
                    data["latitude"],
                    data["longitude"],
                    data["location"],
                    data["country"],
                    data["process"],
                    data["flavours"],
                    data["rating"],
                    data["grinder"],
                    data["grind_setting"],
                    data["brew_style"],
                    datetime.utcnow().isoformat(timespec="seconds"),
                ),
            )
            conn.commit()
            conn.close()
            flash("Coffee logged successfully.", "success")
            return redirect(url_for("log"))

    return render_template(
        "add.html",
        grinders=ALLOWED_GRINDERS,
        aergrind_settings=AERGRIND_SETTINGS,
        belinda_settings=BELINDA_SETTINGS,
        brew_styles=ALLOWED_BREW_STYLES,
        processes=ALLOWED_PROCESSES,
    )


@app.route("/log")
def log() -> Any:
    init_db()
    filters = build_filters_from_request(request.args)
    coffees = fetch_coffees(filters)
    return render_template(
        "log.html",
        coffees=coffees,
        distinct_values={
            "brand": get_distinct_values("brand"),
            "varietal": get_distinct_values("varietal"),
            "origin_region": get_distinct_values("origin_region"),
            "country": get_distinct_values("country"),
            "process": get_distinct_values("process"),
            "brew_style": get_distinct_values("brew_style"),
        },
    )


@app.route("/map")
def map_view() -> Any:
    init_db()
    filters = build_filters_from_request(request.args)
    coffees = [
        dict(row)
        for row in fetch_coffees(filters)
        if row["latitude"] is not None and row["longitude"] is not None
    ]
    return render_template(
        "map.html",
        coffees=json.dumps(coffees),
        distinct_values={
            "brand": get_distinct_values("brand"),
            "varietal": get_distinct_values("varietal"),
            "origin_region": get_distinct_values("origin_region"),
            "country": get_distinct_values("country"),
            "process": get_distinct_values("process"),
            "brew_style": get_distinct_values("brew_style"),
        },
    )


@app.route("/api/suggest")
def suggest() -> Any:
    field = request.args.get("field", "")
    term = request.args.get("term", "").strip().lower()
    if field not in {
        "brand",
        "varietal",
        "origin_region",
        "country",
        "location",
        "process",
        "flavours",
    }:
        return jsonify([])
    conn = get_db()
    rows = conn.execute(
        f"""
        SELECT DISTINCT {field}
        FROM coffees
        WHERE {field} IS NOT NULL
          AND {field} != ''
          AND LOWER({field}) LIKE ?
        ORDER BY {field}
        LIMIT 8
        """,
        (f"%{term}%",),
    ).fetchall()
    conn.close()
    return jsonify([row[field] for row in rows])


@app.route("/api/parse_maps_link", methods=["POST"])
def parse_maps_link() -> Any:
    data = request.get_json(silent=True) or {}
    url = data.get("url", "")
    patterns = [
        r"@(-?\d+\.\d+),(-?\d+\.\d+)",
        r"[?&]q=(-?\d+\.\d+),(-?\d+\.\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            lat = float(match.group(1))
            lon = float(match.group(2))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return jsonify({"ok": True, "lat": lat, "lon": lon})
            return jsonify({"ok": False, "error": "Coordinates out of range."})
    return jsonify({"ok": False, "error": "Unable to parse coordinates from the link."})


@app.route("/api/elevation")
def elevation() -> Any:
    lat = request.args.get("lat")
    lon = request.args.get("lon")
    if not lat or not lon:
        return jsonify({"ok": False, "error": "Missing coordinates."})
    try:
        lat_value = float(lat)
        lon_value = float(lon)
    except ValueError:
        return jsonify({"ok": False, "error": "Invalid coordinates."})

    if not (-90 <= lat_value <= 90 and -180 <= lon_value <= 180):
        return jsonify({"ok": False, "error": "Coordinates out of range."})

    try:
        response = requests.get(
            ELEVATION_API,
            params={"locations": f"{lat_value},{lon_value}"},
            timeout=6,
        )
        response.raise_for_status()
        payload = response.json()
        results = payload.get("results", [])
        if not results:
            return jsonify({"ok": False, "error": "Elevation unavailable."})
        elevation_value = results[0].get("elevation")
        if elevation_value is None:
            return jsonify({"ok": False, "error": "Elevation unavailable."})
        return jsonify({"ok": True, "altitude_m": round(float(elevation_value))})
    except (requests.RequestException, ValueError, TypeError):
        return jsonify({"ok": False, "error": "Elevation lookup failed."})


@app.route("/api/reverse_geocode", methods=["POST"])
def reverse_geocode() -> Any:
    data = request.get_json(silent=True) or {}
    lat = data.get("lat")
    lon = data.get("lon")
    if lat is None or lon is None:
        return jsonify({"ok": False, "error": "Missing coordinates."})
    try:
        lat_value = float(lat)
        lon_value = float(lon)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid coordinates."})

    if not (-90 <= lat_value <= 90 and -180 <= lon_value <= 180):
        return jsonify({"ok": False, "error": "Coordinates out of range."})

    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={
                "format": "jsonv2",
                "lat": lat_value,
                "lon": lon_value,
                "zoom": 10,
                "addressdetails": 1,
            },
            headers={"User-Agent": "CoffeeLog/1.0 (coffeelog@example.com)"},
            timeout=6,
        )
        response.raise_for_status()
        payload = response.json()
        address = payload.get("address", {})
        country = address.get("country")
        location = (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("county")
            or address.get("state")
            or address.get("region")
        )
        if not country and not location:
            return jsonify({"ok": False, "error": "No location found."})
        return jsonify({"ok": True, "country": country, "location": location})
    except (requests.RequestException, ValueError, TypeError):
        return jsonify({"ok": False, "error": "Reverse geocoding failed."})


@app.route("/seed", methods=["POST"])
def seed_route() -> Any:
    from seed import seed_data

    init_db()
    inserted = seed_data(get_db())
    flash(f"Seeded {inserted} coffees.", "success")
    return redirect(url_for("log"))


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
