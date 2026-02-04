from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pycountry
import requests
import reverse_geocoder as rg
from flask import Flask, flash, jsonify, redirect, render_template, request, url_for

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "coffeelog.db"

ALLOWED_GRINDERS = ["Aergrind (Nicholas)", "Belinda’s grinder"]
AERGRIND_SETTINGS = ["Aergrind Fine", "Aergrind Medium"]
BELINDA_SETTINGS = [str(i) for i in range(1, 13)]
ALLOWED_BREW_STYLES = ["Aeropress", "Moka pot", "V60"]
ALLOWED_PROCESSES = ["washed", "natural", "anaerobic", "honey", "experimental"]
ELEVATION_API = "https://api.open-elevation.com/api/v1/lookup"
COUNTRY_CODES = {
    "Brazil": "BR",
    "Burundi": "BI",
    "Colombia": "CO",
    "Costa Rica": "CR",
    "Ethiopia": "ET",
    "Guatemala": "GT",
    "Indonesia": "ID",
    "Kenya": "KE",
    "Panama": "PA",
    "Peru": "PE",
    "Rwanda": "RW",
    "Tanzania": "TZ",
}

app = Flask(__name__)
app.secret_key = "coffee-log-mvp"


def emoji_flag(country_code: str) -> str:
    return "".join(chr(127397 + ord(char)) for char in country_code.upper())


def flag_for_country(country: str | None) -> str | None:
    if not country:
        return None
    code = COUNTRY_CODES.get(country)
    if not code:
        return None
    return emoji_flag(code)


@app.context_processor
def inject_country_flags() -> dict[str, Any]:
    return {
        "country_flags": {
            country: flag_for_country(country) for country in COUNTRY_CODES.keys()
        }
    }


@app.template_filter("flag_country")
def flag_country(country: str) -> str:
    flag = flag_for_country(country)
    if not flag:
        return country
    return f"{flag} {country}"


@app.template_filter("format_latlon")
def format_latlon(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.5f}"


def build_query(args: dict[str, str], **updates: str) -> str:
    data = dict(args)
    for key, value in updates.items():
        if value:
            data[key] = value
        else:
            data.pop(key, None)
    return urlencode(data)


def combine_where(base: str, clause: str) -> str:
    if not clause:
        return base
    if base:
        return f"{base} AND {clause}"
    return f" WHERE {clause}"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS coffees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    brand TEXT,
    varietal TEXT,
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
    data["latitude"] = round(latitude, 5) if latitude is not None else None
    data["longitude"] = round(longitude, 5) if longitude is not None else None

    data["brand"] = form.get("brand", "").strip()
    data["varietal"] = form.get("varietal", "").strip()
    data["country"] = form.get("country", "").strip()
    data["location"] = form.get("location", "").strip()
    data["process"] = form.get("process", "").strip()
    data["flavours"] = normalize_flavours(form.get("flavours", ""))

    return data, errors


def get_distinct_values(field: str) -> list[str]:
    if field not in {
        "brand",
        "varietal",
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


def fetch_ranked_field(
    field: str, filters: tuple[str, list[Any]], limit: int = 10
) -> list[dict[str, Any]]:
    if field not in {
        "brand",
        "varietal",
        "brew_style",
        "country",
        "location",
        "process",
    }:
        return []
    where, params = filters
    where = combine_where(where, f"{field} IS NOT NULL AND {field} != ''")
    conn = get_db()
    rows = conn.execute(
        f"""
        SELECT {field} AS name, AVG(rating) AS avg_rating, COUNT(*) AS n
        FROM coffees
        {where}
        GROUP BY {field}
        ORDER BY avg_rating DESC, n DESC
        LIMIT ?
        """,
        params + [limit],
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def fetch_ranked_regions(
    filters: tuple[str, list[Any]], limit: int = 10
) -> list[dict[str, Any]]:
    where, params = filters
    where = combine_where(where, "location IS NOT NULL AND location != ''")
    conn = get_db()
    rows = conn.execute(
        f"""
        SELECT country, location, AVG(rating) AS avg_rating, COUNT(*) AS n
        FROM coffees
        {where}
        GROUP BY country, location
        ORDER BY avg_rating DESC, n DESC
        LIMIT ?
        """,
        params + [limit],
    ).fetchall()
    conn.close()
    items: list[dict[str, Any]] = []
    for row in rows:
        country = row["country"] or ""
        location = row["location"] or ""
        name = f"{country} · {location}" if country else location
        items.append(
            {
                "name": name,
                "country": country,
                "location": location,
                "avg_rating": row["avg_rating"],
                "n": row["n"],
            }
        )
    return items


def format_coffee_title(row: sqlite3.Row | None) -> str:
    if not row:
        return "Unknown coffee"
    title = row["brand"] or "Unknown roaster"
    if row["varietal"]:
        title = f"{title} · {row['varietal']}"
    return title


def build_altitude_bins() -> list[dict[str, Any]]:
    return [
        {"label": "0–500 m", "min": 0, "max": 500},
        {"label": "500–1000 m", "min": 500, "max": 1000},
        {"label": "1000–1500 m", "min": 1000, "max": 1500},
        {"label": "1500–2000 m", "min": 1500, "max": 2000},
        {"label": "2000–2500 m", "min": 2000, "max": 2500},
        {"label": "2500+ m", "min": 2500, "max": None},
    ]


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
                    date, brand, varietal, altitude_m, latitude, longitude,
                    location, country, process, flavours, rating, grinder, grind_setting,
                    brew_style, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["date"],
                    data["brand"],
                    data["varietal"],
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
        today_date=datetime.now().date().isoformat(),
    )


@app.route("/log")
def log() -> Any:
    init_db()
    entry_id = request.args.get("entry_id")
    filters = build_filters_from_request(request.args)
    coffees = fetch_coffees(filters)
    return render_template(
        "log.html",
        coffees=coffees,
        entry_id=entry_id,
        build_query=build_query,
        distinct_values={
            "brand": get_distinct_values("brand"),
            "varietal": get_distinct_values("varietal"),
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
        build_query=build_query,
        distinct_values={
            "brand": get_distinct_values("brand"),
            "varietal": get_distinct_values("varietal"),
            "country": get_distinct_values("country"),
            "process": get_distinct_values("process"),
            "brew_style": get_distinct_values("brew_style"),
        },
    )


@app.route("/altitude")
def altitude_view() -> Any:
    init_db()
    filters = build_filters_from_request(request.args)
    coffees = [
        dict(row)
        for row in fetch_coffees(filters)
        if row["latitude"] is not None and row["longitude"] is not None
    ]
    return render_template(
        "altitude.html",
        coffees=json.dumps(coffees),
        build_query=build_query,
        distinct_values={
            "brand": get_distinct_values("brand"),
            "varietal": get_distinct_values("varietal"),
            "country": get_distinct_values("country"),
            "process": get_distinct_values("process"),
            "brew_style": get_distinct_values("brew_style"),
        },
    )


@app.route("/stats")
def stats_view() -> Any:
    init_db()
    filters = build_filters_from_request(request.args)
    dim = request.args.get("dim")
    value = request.args.get("value")

    ranked = {
        "brands": fetch_ranked_field("brand", filters),
        "varietals": fetch_ranked_field("varietal", filters),
        "brew_styles": fetch_ranked_field("brew_style", filters),
        "countries": fetch_ranked_field("country", filters),
        "regions": fetch_ranked_regions(filters),
    }

    where, params = filters
    conn = get_db()
    total_count = conn.execute(f"SELECT COUNT(*) AS n FROM coffees{where}", params).fetchone()["n"]
    altitude_where = combine_where(where, "altitude_m IS NOT NULL")
    altitude_rows = conn.execute(
        f"SELECT altitude_m, rating FROM coffees{altitude_where}",
        params,
    ).fetchall()
    highest_row = conn.execute(
        f"""
        SELECT * FROM coffees
        {altitude_where}
        ORDER BY altitude_m DESC
        LIMIT 1
        """,
        params,
    ).fetchone()
    lowest_row = conn.execute(
        f"""
        SELECT * FROM coffees
        {altitude_where}
        ORDER BY altitude_m ASC
        LIMIT 1
        """,
        params,
    ).fetchone()
    conn.close()

    altitude_values = sorted([row["altitude_m"] for row in altitude_rows if row["altitude_m"]])
    altitude_count = len(altitude_values)
    median_altitude = None
    if altitude_count:
        mid = altitude_count // 2
        if altitude_count % 2 == 0:
            median_altitude = round((altitude_values[mid - 1] + altitude_values[mid]) / 2)
        else:
            median_altitude = altitude_values[mid]

    altitude_bins = build_altitude_bins()
    for bin_item in altitude_bins:
        bin_min = bin_item["min"]
        bin_max = bin_item["max"]
        matches = [
            row
            for row in altitude_rows
            if row["altitude_m"] is not None
            and row["altitude_m"] >= bin_min
            and (bin_max is None or row["altitude_m"] < bin_max)
        ]
        bin_item["n"] = len(matches)
        if matches:
            bin_item["avg_rating"] = sum(row["rating"] for row in matches) / len(matches)
        else:
            bin_item["avg_rating"] = None
    max_bin = max((bin_item["n"] for bin_item in altitude_bins), default=0)

    selection = None
    selection_coffees: list[sqlite3.Row] = []
    selection_where = where
    selection_params = list(params)
    if dim and value:
        selection_title = ""
        if dim in {"brand", "varietal", "brew_style", "country", "location", "process"}:
            selection_where = combine_where(selection_where, f"{dim} = ?")
            selection_params.append(value)
            selection_title = f"{dim.replace('_', ' ').title()}: {value}"
        elif dim == "region":
            parts = value.split("||", 1)
            country = parts[0] if parts else ""
            location = parts[1] if len(parts) > 1 else ""
            if country:
                selection_where = combine_where(selection_where, "country = ?")
                selection_params.append(country)
            if location:
                selection_where = combine_where(selection_where, "location = ?")
                selection_params.append(location)
            region_label = f"{country} · {location}".strip(" ·")
            if region_label:
                selection_title = f"Region: {region_label}"
        elif dim == "altitude_bin":
            bin_lookup = {bin_item["label"]: bin_item for bin_item in altitude_bins}
            bin_item = bin_lookup.get(value)
            if bin_item:
                selection_title = f"Altitude: {value}"
                selection_where = combine_where(selection_where, "altitude_m IS NOT NULL")
                selection_where = combine_where(selection_where, "altitude_m >= ?")
                selection_params.append(bin_item["min"])
                if bin_item["max"] is not None:
                    selection_where = combine_where(selection_where, "altitude_m < ?")
                    selection_params.append(bin_item["max"])

        if selection_title:
            conn = get_db()
            summary = conn.execute(
                f"""
                SELECT AVG(rating) AS avg_rating, COUNT(*) AS n
                FROM coffees
                {selection_where}
                """,
                selection_params,
            ).fetchone()
            conn.close()
            selection = {
                "title": selection_title,
                "avg_rating": summary["avg_rating"],
                "n": summary["n"],
            }
            selection_coffees = fetch_coffees((selection_where, selection_params))

    return render_template(
        "stats.html",
        ranked=ranked,
        altitude={
            "highest": {
                "title": format_coffee_title(highest_row),
                "altitude_m": highest_row["altitude_m"] if highest_row else None,
            },
            "lowest": {
                "title": format_coffee_title(lowest_row),
                "altitude_m": lowest_row["altitude_m"] if lowest_row else None,
            },
            "median": median_altitude,
            "coverage": (altitude_count / total_count * 100) if total_count else 0,
            "bins": altitude_bins,
            "max_bin": max_bin,
        },
        selection=selection,
        selection_coffees=selection_coffees,
        build_query=build_query,
    )


@app.route("/api/suggest")
def suggest() -> Any:
    field = request.args.get("field", "")
    term = request.args.get("term", "").strip().lower()
    if field not in {
        "brand",
        "varietal",
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
    app.logger.info("Reverse geocode request: lat=%s lon=%s", lat, lon)
    if lat is None or lon is None:
        return jsonify({"ok": False, "error": "Missing coordinates."})
    try:
        lat_value = float(lat)
        lon_value = float(lon)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid coordinates."})

    if not (-90 <= lat_value <= 90 and -180 <= lon_value <= 180):
        return jsonify({"ok": False, "error": "Coordinates out of range."})

    nominatim_ok = False
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
            headers={
                "User-Agent": "CoffeeLog/1.0 (coffeelog@example.com)",
                "Accept": "application/json",
            },
            timeout=5,
        )
        response.raise_for_status()
        payload = response.json()
        address = payload.get("address", {})
        country = address.get("country")
        location = (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("hamlet")
            or address.get("county")
            or address.get("state")
        )
        if country or location:
            nominatim_ok = True
            app.logger.info("reverse_geocode lat=%s lon=%s nominatim=success", lat, lon)
            return jsonify(
                {
                    "ok": True,
                    "country": country or "",
                    "location": location or "",
                    "source": "nominatim",
                }
            )
        app.logger.warning("reverse_geocode lat=%s lon=%s nominatim=empty -> offline=attempt", lat, lon)
    except (requests.RequestException, ValueError, TypeError):
        app.logger.warning("reverse_geocode lat=%s lon=%s nominatim=fail -> offline=attempt", lat, lon)

    try:
        results = rg.search((lat_value, lon_value), mode=1)
        if not results:
            app.logger.warning("reverse_geocode lat=%s lon=%s nominatim=fail -> offline=empty", lat, lon)
            return jsonify({"ok": False, "error": "Reverse geocoding failed."})
        result = results[0]
        country_code = result.get("cc")
        country_name = ""
        if country_code:
            country_obj = pycountry.countries.get(alpha_2=country_code)
            country_name = country_obj.name if country_obj else ""
        name = result.get("name", "")
        admin1 = result.get("admin1", "")
        location = name
        if admin1 and admin1 not in location:
            location = f"{name}, {admin1}" if name else admin1
        if not country_name and not location:
            app.logger.warning("reverse_geocode lat=%s lon=%s nominatim=fail -> offline=empty", lat, lon)
            return jsonify({"ok": False, "error": "Reverse geocoding failed."})
        app.logger.info("reverse_geocode lat=%s lon=%s nominatim=fail -> offline=success", lat, lon)
        return jsonify(
            {
                "ok": True,
                "country": country_name,
                "location": location,
                "source": "offline",
            }
        )
    except Exception:
        if nominatim_ok:
            app.logger.info("reverse_geocode lat=%s lon=%s nominatim=success -> offline=skip", lat, lon)
        else:
            app.logger.warning("reverse_geocode lat=%s lon=%s nominatim=fail -> offline=fail", lat, lon)
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
