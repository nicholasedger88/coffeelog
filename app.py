from __future__ import annotations

import json
import re
import sqlite3
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pycountry
import requests
import reverse_geocoder as rg
from flask import Flask, flash, jsonify, redirect, render_template, request, url_for
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "coffeelog.db"

ALLOWED_GRINDERS = ["Aergrind (Nicholas)", "Belinda’s grinder"]
AERGRIND_SETTINGS = [
    {"value": f"{rotation}-{click:02d}", "label": f"{rotation} rot, {click} clicks"}
    for rotation in range(0, 5)
    for click in range(0, 13)
]
BELINDA_SETTINGS = [str(i) for i in range(1, 13)]
ALLOWED_BREW_STYLES = ["Aeropress", "Moka pot", "V60"]
ALLOWED_USERS = ["Nicholas", "Belinda"]
ALLOWED_PROCESSES = ["washed", "natural", "anaerobic", "honey", "experimental"]
ALLOWED_PRODUCT_ENTRY_KINDS = ["idea", "feature", "bug", "refinement", "release_note"]
ALLOWED_PRODUCT_STATUSES = [
    "idea",
    "planned",
    "in_progress",
    "blocked",
    "tested",
    "live",
    "archived",
]
ALLOWED_PRODUCT_PRIORITIES = ["low", "medium", "high"]
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
app.secret_key = os.environ.get("COFFEELOG_SECRET_KEY", "coffee-log-dev-only")
app.config["ALLOW_DEMO_SEED"] = os.environ.get("COFFEELOG_ALLOW_DEMO_SEED", "1") == "1"


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


@app.template_filter("format_grind")
def format_grind_setting(value: str, grinder: str | None = None) -> str:
    if not value:
        return ""
    if grinder == "Aergrind (Nicholas)":
        parts = value.replace("|", "-").split("-")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            rotation = int(parts[0])
            clicks = int(parts[1])
            return f"{rotation} rot, {clicks} clicks"
    return value


@app.template_filter("format_duration")
def format_duration(seconds: int | float | None) -> str:
    if seconds is None:
        return ""
    total = int(round(seconds))
    minutes = total // 60
    remaining = total % 60
    return f"{minutes}:{remaining:02d}"


@app.template_filter("format_clock")
def format_clock(seconds: int | float | None) -> str:
    if seconds is None:
        return ""
    total = int(round(seconds))
    hours = total // 3600
    minutes = (total % 3600) // 60
    remaining = total % 60
    return f"{hours:02d}:{minutes:02d}:{remaining:02d}"


@app.template_filter("recipe_summary")
def recipe_summary(brew: sqlite3.Row | dict[str, Any]) -> str:
    def get_value(key: str) -> Any:
        return brew[key] if isinstance(brew, sqlite3.Row) else brew.get(key)

    def format_amount(value: float | None, suffix: str) -> str:
        if value is None:
            return ""
        text = f"{value:.1f}".rstrip("0").rstrip(".")
        return f"{text}{suffix}"

    parts: list[str] = []
    dose = get_value("dose_g")
    if dose is not None:
        parts.append(format_amount(float(dose), "g"))
    water = get_value("water_ml")
    if water is not None:
        parts.append(f"{int(water)}ml")
    temp = get_value("temp_c")
    if temp is not None:
        parts.append(format_amount(float(temp), "°C"))
    total = get_value("total_brew_s")
    if total is not None:
        parts.append(format_duration(total))
    return " · ".join([part for part in parts if part])


@app.template_filter("has_recipe")
def has_recipe(brew: sqlite3.Row | dict[str, Any]) -> bool:
    fields = [
        "dose_g",
        "water_ml",
        "temp_c",
        "total_brew_s",
        "pour_time_s",
        "bloom_water_ml",
        "bloom_time_s",
        "agitation",
        "recipe_notes",
    ]
    for field in fields:
        if isinstance(brew, sqlite3.Row):
            try:
                value = brew[field]
            except (IndexError, KeyError):
                continue
        else:
            value = brew.get(field)
        if value not in (None, ""):
            return True
    return False


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


def continent_from_latlon(lat: float | None, lon: float | None) -> str:
    if lat is None or lon is None:
        return "Unknown"
    if lat <= -60:
        return "Antarctica"
    if -35 <= lat <= 37 and -20 <= lon <= 52:
        return "Africa"
    if 35 <= lat <= 71 and -25 <= lon <= 40:
        return "Europe"
    if 5 <= lat <= 77 and 40 <= lon <= 150:
        return "Asia"
    if 7 <= lat <= 72 and -170 <= lon <= -50:
        return "North America"
    if -56 <= lat <= 13 and -82 <= lon <= -34:
        return "South America"
    if -50 <= lat <= 10 and 110 <= lon <= 180:
        return "Oceania"
    return "Unknown"


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

CREATE TABLE IF NOT EXISTS bags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coffee_name TEXT NOT NULL,
    brand TEXT NOT NULL,
    varietal TEXT,
    flavours TEXT,
    country TEXT,
    location TEXT,
    process TEXT,
    latitude REAL,
    longitude REAL,
    altitude_m INTEGER,
    continent TEXT,
    owner_user TEXT,
    photo_path TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS brews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bag_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    brew_style TEXT NOT NULL,
    grinder TEXT NOT NULL,
    logged_by_user TEXT NOT NULL DEFAULT 'Nicholas',
    grind_setting TEXT NOT NULL,
    notes TEXT,
    dose_g REAL,
    water_ml INTEGER,
    temp_c REAL,
    total_brew_s INTEGER,
    pour_time_s INTEGER,
    bloom_water_ml INTEGER,
    bloom_time_s INTEGER,
    agitation TEXT,
    recipe_notes TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (bag_id) REFERENCES bags(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS brew_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brew_id INTEGER NOT NULL,
    step_order INTEGER NOT NULL,
    start_seconds INTEGER NOT NULL,
    end_seconds INTEGER NOT NULL,
    label_text TEXT,
    liquid_text TEXT,
    FOREIGN KEY (brew_id) REFERENCES brews(id) ON DELETE CASCADE
);
"""


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_db()
    conn.executescript(SCHEMA_SQL)
    migrate_bags_schema(conn)
    migrate_brews_schema(conn)
    migrate_brew_steps_schema(conn)
    conn.commit()
    conn.close()


def migrate_bags_schema(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(bags)").fetchall()}
    migrations = {
        "flavours": "ALTER TABLE bags ADD COLUMN flavours TEXT;",
        "photo_path": "ALTER TABLE bags ADD COLUMN photo_path TEXT;",
        "continent": "ALTER TABLE bags ADD COLUMN continent TEXT;",
        "owner_user": "ALTER TABLE bags ADD COLUMN owner_user TEXT;",
    }
    for column, statement in migrations.items():
        if column in columns:
            continue
        try:
            conn.execute(statement)
            app.logger.info("Migrated: added bags.%s", column)
        except sqlite3.OperationalError:
            pass
    conn.execute(
        "UPDATE bags SET owner_user = COALESCE(owner_user, 'Nicholas') WHERE owner_user IS NULL OR owner_user = ''"
    )


def migrate_brews_schema(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(brews)").fetchall()}
    migrations = {
        "dose_g": "ALTER TABLE brews ADD COLUMN dose_g REAL;",
        "water_ml": "ALTER TABLE brews ADD COLUMN water_ml INTEGER;",
        "temp_c": "ALTER TABLE brews ADD COLUMN temp_c REAL;",
        "total_brew_s": "ALTER TABLE brews ADD COLUMN total_brew_s INTEGER;",
        "pour_time_s": "ALTER TABLE brews ADD COLUMN pour_time_s INTEGER;",
        "bloom_water_ml": "ALTER TABLE brews ADD COLUMN bloom_water_ml INTEGER;",
        "bloom_time_s": "ALTER TABLE brews ADD COLUMN bloom_time_s INTEGER;",
        "agitation": "ALTER TABLE brews ADD COLUMN agitation TEXT;",
        "recipe_notes": "ALTER TABLE brews ADD COLUMN recipe_notes TEXT;",
        "logged_by_user": "ALTER TABLE brews ADD COLUMN logged_by_user TEXT;",
    }
    for column, statement in migrations.items():
        if column in columns:
            continue
        try:
            conn.execute(statement)
            app.logger.info("Migrated: added brews.%s", column)
        except sqlite3.OperationalError:
            pass
    conn.execute(
        "UPDATE brews SET logged_by_user = COALESCE(logged_by_user, 'Nicholas') WHERE logged_by_user IS NULL OR logged_by_user = ''"
    )




def migrate_brew_steps_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS brew_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brew_id INTEGER NOT NULL,
            step_order INTEGER NOT NULL,
            start_seconds INTEGER NOT NULL,
            end_seconds INTEGER NOT NULL,
            label_text TEXT,
            liquid_text TEXT,
            FOREIGN KEY (brew_id) REFERENCES brews(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_brew_steps_brew_order
        ON brew_steps (brew_id, step_order)
        """
    )


def parse_brew_steps(raw_steps: str | None) -> tuple[list[dict[str, Any]], list[str]]:
    if not raw_steps:
        return [], []
    errors: list[str] = []
    try:
        payload = json.loads(raw_steps)
    except json.JSONDecodeError:
        return [], ["Brew recorder data is invalid."]
    if not isinstance(payload, list):
        return [], ["Brew recorder data is invalid."]

    parsed_steps: list[dict[str, Any]] = []
    previous_end = 0
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            errors.append("Brew recorder step format is invalid.")
            continue
        start_raw = item.get("start_seconds")
        end_raw = item.get("end_seconds")
        if not isinstance(start_raw, int) or not isinstance(end_raw, int):
            errors.append(f"Step {index} has invalid timing data.")
            continue
        if start_raw < 0 or end_raw < 0 or end_raw <= start_raw:
            errors.append(f"Step {index} timing must be positive and increasing.")
            continue
        if start_raw < previous_end:
            errors.append(f"Step {index} starts before the previous step ends.")
            continue
        if end_raw > 36000:
            errors.append(f"Step {index} timing is too long.")
            continue
        label_text = str(item.get("label_text", "")).strip()[:200]
        liquid_text = str(item.get("liquid_text", "")).strip()[:120]
        parsed_steps.append(
            {
                "step_order": index,
                "start_seconds": start_raw,
                "end_seconds": end_raw,
                "label_text": label_text,
                "liquid_text": liquid_text,
            }
        )
        previous_end = end_raw

    return parsed_steps, errors

def normalize_flavours(raw: str) -> str:
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    return ", ".join(parts)


def extract_flavour_tokens(raw_values: list[str]) -> list[str]:
    tokens: dict[str, str] = {}
    for raw in raw_values:
        for part in raw.split(","):
            token = part.strip()
            if not token:
                continue
            key = token.lower()
            tokens.setdefault(key, token)
    return sorted(tokens.values(), key=lambda value: value.lower())


def parse_aergrind_setting(value: str) -> tuple[int, int] | None:
    if not value:
        return None
    parts = value.replace("|", "-").split("-")
    if len(parts) != 2:
        return None
    try:
        rotation = int(parts[0])
        clicks = int(parts[1])
    except ValueError:
        return None
    if 0 <= rotation <= 4 and 0 <= clicks <= 12:
        return rotation, clicks
    return None


def parse_optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def parse_optional_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def parse_duration_input(value: str | None) -> tuple[int | None, str | None]:
    if value is None:
        return None, None
    text = value.strip()
    if not text:
        return None, None
    if ":" in text:
        parts = text.split(":")
        if len(parts) != 2:
            return None, "Use mm:ss or seconds."
        minutes_raw, seconds_raw = parts
        if not minutes_raw.isdigit() or not seconds_raw.isdigit():
            return None, "Use mm:ss or seconds."
        minutes = int(minutes_raw)
        seconds = int(seconds_raw)
        if seconds >= 60:
            return None, "Seconds must be under 60."
        return minutes * 60 + seconds, None
    try:
        return int(text), None
    except ValueError:
        return None, "Use mm:ss or seconds."


def parse_recipe_fields(form: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    data: dict[str, Any] = {}

    data["recipe_notes"] = form.get("recipe_notes", "").strip()

    dose_g = parse_optional_float(form.get("dose_g"))
    if dose_g is not None and not (0 < dose_g <= 100):
        errors.append("Dose must be between 0 and 100g.")
    data["dose_g"] = dose_g

    water_ml = parse_optional_int(form.get("water_ml"))
    if water_ml is not None and not (0 < water_ml <= 2000):
        errors.append("Water must be between 0 and 2000ml.")
    data["water_ml"] = water_ml

    temp_c = parse_optional_float(form.get("temp_c"))
    if temp_c is not None and not (0 < temp_c <= 100):
        errors.append("Temperature must be between 0 and 100°C.")
    data["temp_c"] = temp_c

    total_brew_s, total_error = parse_duration_input(form.get("total_brew_s"))
    if total_error:
        errors.append("Total brew time must be in mm:ss or seconds.")
    if total_brew_s is not None and not (0 <= total_brew_s <= 3600):
        errors.append("Total brew time must be between 0 and 3600s.")
    data["total_brew_s"] = total_brew_s

    pour_time_s, pour_error = parse_duration_input(form.get("pour_time_s"))
    if pour_error:
        errors.append("Pour time must be in mm:ss or seconds.")
    if pour_time_s is not None and not (0 <= pour_time_s <= 3600):
        errors.append("Pour time must be between 0 and 3600s.")
    data["pour_time_s"] = pour_time_s

    bloom_water_ml = parse_optional_int(form.get("bloom_water_ml"))
    if bloom_water_ml is not None and not (0 <= bloom_water_ml <= 1000):
        errors.append("Bloom water must be between 0 and 1000ml.")
    data["bloom_water_ml"] = bloom_water_ml

    bloom_time_s = parse_optional_int(form.get("bloom_time_s"))
    if bloom_time_s is not None and not (0 <= bloom_time_s <= 600):
        errors.append("Bloom time must be between 0 and 600s.")
    data["bloom_time_s"] = bloom_time_s

    agitation = form.get("agitation", "").strip()
    agitation, agitation_error = parse_allowed_choice(
        agitation,
        {"none", "swirl", "stir"},
        "Agitation must be none, swirl, or stir.",
        allow_empty=True,
    )
    if agitation_error:
        errors.append(agitation_error)
    data["agitation"] = agitation

    return data, errors


def validate_bag_payload(form: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    data: dict[str, Any] = {}

    coffee_name = form.get("coffee_name", "").strip()
    if not coffee_name:
        errors.append("Coffee name is required.")
    data["coffee_name"] = coffee_name

    brand = form.get("brand", "").strip()
    if not brand:
        errors.append("Brand is required.")
    data["brand"] = brand

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

    data["varietal"] = form.get("varietal", "").strip()
    data["flavours"] = normalize_flavours(form.get("flavours", ""))
    data["country"] = form.get("country", "").strip()
    data["location"] = form.get("location", "").strip()
    data["process"] = form.get("process", "").strip()
    owner_user, owner_error = parse_allowed_choice(
        form.get("log_as", "").strip(),
        set(ALLOWED_USERS),
        "Log as must be Nicholas or Belinda.",
    )
    if owner_error:
        errors.append(owner_error)
    data["owner_user"] = owner_user

    return data, errors


def validate_brew_payload(form: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
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

    brew_style, brew_style_error = parse_allowed_choice(
        form.get("brew_style", "").strip(),
        set(ALLOWED_BREW_STYLES),
        "Brew style must be one of the allowed options.",
    )
    if brew_style_error:
        errors.append(brew_style_error)
    data["brew_style"] = brew_style

    grinder, grinder_error = parse_allowed_choice(
        form.get("grinder", "").strip(),
        set(ALLOWED_GRINDERS),
        "Grinder must be one of the allowed options.",
    )
    if grinder_error:
        errors.append(grinder_error)
    data["grinder"] = grinder

    grind_setting = form.get("grind_setting", "").strip()
    if grinder == "Aergrind (Nicholas)":
        if not parse_aergrind_setting(grind_setting):
            errors.append("Choose a valid Aergrind setting.")
    if grinder == "Belinda’s grinder" and grind_setting not in BELINDA_SETTINGS:
        errors.append("Choose a valid Belinda setting.")
    data["grind_setting"] = grind_setting

    data["notes"] = form.get("notes", "").strip()
    logged_by_user, user_error = parse_allowed_choice(
        form.get("log_as", "").strip(),
        set(ALLOWED_USERS),
        "Log as must be Nicholas or Belinda.",
    )
    if user_error:
        errors.append(user_error)
    data["logged_by_user"] = logged_by_user
    recipe_data, recipe_errors = parse_recipe_fields(form)
    data.update(recipe_data)
    errors.extend(recipe_errors)

    return data, errors


def get_distinct_values(field: str) -> list[str]:
    bag_fields = {
        "coffee_name": "bags.coffee_name",
        "brand": "bags.brand",
        "varietal": "bags.varietal",
        "continent": "bags.continent",
        "country": "bags.country",
        "location": "bags.location",
        "process": "bags.process",
        "owner_user": "bags.owner_user",
    }
    brew_fields = {
        "brew_style": "brews.brew_style",
        "grinder": "brews.grinder",
        "grind_setting": "brews.grind_setting",
        "logged_by_user": "brews.logged_by_user",
        "flavours": "bags.flavours",
    }
    field_expr = bag_fields.get(field) or brew_fields.get(field)
    if not field_expr:
        return []
    conn = get_db()
    rows = conn.execute(
        f"""
        SELECT DISTINCT {field_expr} AS value
        FROM brews
        JOIN bags ON bags.id = brews.bag_id
        WHERE {field_expr} IS NOT NULL AND {field_expr} != ''
        ORDER BY {field_expr}
        """
    ).fetchall()
    conn.close()
    return [row["value"] for row in rows]


def parse_allowed_choice(
    value: str,
    allowed: set[str],
    message: str,
    allow_empty: bool = False,
) -> tuple[str | None, str | None]:
    if not value:
        return (None, None) if allow_empty else ("", message)
    if value in allowed:
        return value, None
    return value, message


def build_distinct_values(include_brew_fields: bool = True) -> dict[str, list[str]]:
    values = {
        "coffee_name": get_distinct_values("coffee_name"),
        "brand": get_distinct_values("brand"),
        "varietal": get_distinct_values("varietal"),
        "continent": get_distinct_values("continent"),
        "country": get_distinct_values("country"),
        "location": get_distinct_values("location"),
        "process": get_distinct_values("process"),
        "owner_user": get_distinct_values("owner_user"),
    }
    if include_brew_fields:
        values["brew_style"] = get_distinct_values("brew_style")
        values["logged_by_user"] = get_distinct_values("logged_by_user")
    return values


def fetch_latest_brew_id_for_bag(bag_id: int) -> int | None:
    conn = get_db()
    row = conn.execute(
        """
        SELECT id FROM brews
        WHERE bag_id = ?
        ORDER BY date DESC, created_at DESC
        LIMIT 1
        """,
        (bag_id,),
    ).fetchone()
    conn.close()
    if row:
        return row["id"]
    return None


def build_dial_in_assistant(brews: list[sqlite3.Row]) -> dict[str, Any] | None:
    if not brews:
        return None
    rated = [brew for brew in brews if brew["rating"] is not None]
    if not rated:
        return None

    def pick_best_group(rows: list[sqlite3.Row], key_fn: Any) -> tuple[str | None, float | None, int]:
        buckets: dict[str, list[int]] = {}
        for row in rows:
            key = key_fn(row)
            if not key:
                continue
            buckets.setdefault(key, []).append(int(row["rating"]))
        best_name: str | None = None
        best_avg: float | None = None
        best_n = 0
        for name, values in buckets.items():
            avg = sum(values) / len(values)
            n = len(values)
            if (
                best_avg is None
                or avg > best_avg
                or (avg == best_avg and n > best_n)
            ):
                best_name = name
                best_avg = avg
                best_n = n
        return best_name, best_avg, best_n

    best_style, best_style_avg, best_style_n = pick_best_group(
        rated, lambda row: row["brew_style"]
    )
    best_grind, best_grind_avg, best_grind_n = pick_best_group(
        rated, lambda row: f'{row["grinder"]} · {format_grind_setting(row["grind_setting"], row["grinder"])}'
    )

    top_rows = [row for row in rated if int(row["rating"]) >= 4]
    if not top_rows:
        top_rows = rated

    def avg_metric(metric: str) -> float | None:
        numbers = [float(row[metric]) for row in top_rows if row[metric] is not None]
        if not numbers:
            return None
        return sum(numbers) / len(numbers)

    return {
        "brew_count": len(brews),
        "best_style": {"name": best_style, "avg": best_style_avg, "n": best_style_n},
        "best_grind": {"name": best_grind, "avg": best_grind_avg, "n": best_grind_n},
        "recipe_targets": {
            "dose_g": avg_metric("dose_g"),
            "water_ml": avg_metric("water_ml"),
            "temp_c": avg_metric("temp_c"),
            "total_brew_s": avg_metric("total_brew_s"),
        },
    }


def build_filters_from_request(args: dict[str, str]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if args.get("date_from"):
        clauses.append("brews.date >= ?")
        params.append(args["date_from"])
    if args.get("date_to"):
        clauses.append("brews.date <= ?")
        params.append(args["date_to"])

    bag_fields = {
        "coffee_name": "bags.coffee_name",
        "brand": "bags.brand",
        "varietal": "bags.varietal",
        "continent": "bags.continent",
        "country": "bags.country",
        "location": "bags.location",
        "process": "bags.process",
        "owner_user": "bags.owner_user",
    }
    brew_fields = {
        "brew_style": "brews.brew_style",
        "grinder": "brews.grinder",
        "grind_setting": "brews.grind_setting",
        "logged_by_user": "brews.logged_by_user",
    }
    for field, column in {**bag_fields, **brew_fields}.items():
        value = args.get(field)
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)

    if args.get("min_rating"):
        try:
            min_rating = int(args["min_rating"])
            clauses.append("brews.rating >= ?")
            params.append(min_rating)
        except ValueError:
            pass

    where = ""
    if clauses:
        where = " WHERE " + " AND ".join(clauses)
    return where, params


def build_bag_filters_from_request(args: dict[str, str]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    for field, column in {
        "coffee_name": "bags.coffee_name",
        "brand": "bags.brand",
        "varietal": "bags.varietal",
        "continent": "bags.continent",
        "country": "bags.country",
        "location": "bags.location",
        "process": "bags.process",
    }.items():
        value = args.get(field)
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    where = ""
    if clauses:
        where = " WHERE " + " AND ".join(clauses)
    return where, params


def fetch_brews(filters: tuple[str, list[Any]]) -> list[sqlite3.Row]:
    where, params = filters
    conn = get_db()
    rows = conn.execute(
        f"""
        SELECT
            brews.id,
            brews.bag_id,
            brews.date,
            brews.rating,
            brews.brew_style,
            brews.grinder,
            brews.logged_by_user,
            brews.grind_setting,
            brews.notes,
            brews.dose_g,
            brews.water_ml,
            brews.temp_c,
            brews.total_brew_s,
            brews.pour_time_s,
            brews.bloom_water_ml,
            brews.bloom_time_s,
            brews.agitation,
            brews.recipe_notes,
            brews.created_at,
            bags.coffee_name,
            bags.brand,
            bags.varietal,
            bags.flavours,
            bags.country,
            bags.location,
            bags.process,
            bags.owner_user,
            bags.latitude,
            bags.longitude,
            bags.altitude_m,
            bags.continent,
            bags.photo_path
        FROM brews
        JOIN bags ON bags.id = brews.bag_id
        {where}
        ORDER BY brews.date DESC, brews.created_at DESC
        """,
        params,
    ).fetchall()
    conn.close()
    return rows


def fetch_ranked_field(
    field: str, filters: tuple[str, list[Any]], limit: int = 10
) -> list[dict[str, Any]]:
    field_map = {
        "coffee_name": "bags.coffee_name",
        "brand": "bags.brand",
        "varietal": "bags.varietal",
        "brew_style": "brews.brew_style",
        "continent": "bags.continent",
        "country": "bags.country",
        "location": "bags.location",
        "process": "bags.process",
    }
    column = field_map.get(field)
    if not column:
        return []
    where, params = filters
    where = combine_where(where, f"{column} IS NOT NULL AND {column} != ''")
    conn = get_db()
    rows = conn.execute(
        f"""
        SELECT {column} AS name, AVG(brews.rating) AS avg_rating, COUNT(*) AS n
        FROM brews
        JOIN bags ON bags.id = brews.bag_id
        {where}
        GROUP BY {column}
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
    where = combine_where(where, "bags.location IS NOT NULL AND bags.location != ''")
    conn = get_db()
    rows = conn.execute(
        f"""
        SELECT bags.country, bags.location, AVG(brews.rating) AS avg_rating, COUNT(*) AS n
        FROM brews
        JOIN bags ON bags.id = brews.bag_id
        {where}
        GROUP BY bags.country, bags.location
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
    coffee_name = row["coffee_name"] if "coffee_name" in row.keys() else None
    brand = row["brand"] if "brand" in row.keys() else None
    title = coffee_name or brand or "Unknown coffee"
    if coffee_name and brand:
        title = f"{coffee_name} · {brand}"
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


def fetch_bag_options() -> list[sqlite3.Row]:
    conn = get_db()
    rows = conn.execute(
        """
        SELECT id, coffee_name, brand
        FROM bags
        ORDER BY coffee_name, brand
        """
    ).fetchall()
    conn.close()
    return rows


def fetch_bag_detail(bag_id: int) -> sqlite3.Row | None:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM bags WHERE id = ?",
        (bag_id,),
    ).fetchone()
    conn.close()
    return row


def fetch_bag_summary(user: str | None = None) -> list[sqlite3.Row]:
    conn = get_db()
    where = ""
    params: list[Any] = []
    if user in ALLOWED_USERS:
        where = """
        WHERE bags.owner_user = ?
           OR EXISTS (
               SELECT 1 FROM brews b2
               WHERE b2.bag_id = bags.id AND b2.logged_by_user = ?
           )
        """
        params = [user, user]
    rows = conn.execute(
        f"""
        SELECT
            bags.*,
            COUNT(brews.id) AS brew_count,
            AVG(brews.rating) AS avg_rating,
            SUM(CASE WHEN brews.logged_by_user = 'Nicholas' THEN 1 ELSE 0 END) AS nicholas_brews,
            SUM(CASE WHEN brews.logged_by_user = 'Belinda' THEN 1 ELSE 0 END) AS belinda_brews
        FROM bags
        LEFT JOIN brews ON brews.bag_id = bags.id
        {where}
        GROUP BY bags.id
        ORDER BY bags.created_at DESC
        """,
        params,
    ).fetchall()
    conn.close()
    return rows


def fetch_brews_for_bag(bag_id: int) -> list[sqlite3.Row]:
    conn = get_db()
    rows = conn.execute(
        """
        SELECT brews.*, bags.latitude, bags.longitude, bags.altitude_m
        FROM brews
        JOIN bags ON bags.id = brews.bag_id
        WHERE bags.id = ?
        ORDER BY brews.date DESC, brews.created_at DESC
        """,
        (bag_id,),
    ).fetchall()
    conn.close()
    return rows


def fetch_steps_for_brew_ids(brew_ids: list[int]) -> dict[int, list[sqlite3.Row]]:
    if not brew_ids:
        return {}
    placeholders = ",".join(["?" for _ in brew_ids])
    conn = get_db()
    rows = conn.execute(
        f"""
        SELECT *
        FROM brew_steps
        WHERE brew_id IN ({placeholders})
        ORDER BY brew_id, step_order ASC
        """,
        brew_ids,
    ).fetchall()
    conn.close()
    grouped: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(row["brew_id"], []).append(row)
    return grouped


def fetch_grind_insights(bag_id: int) -> list[sqlite3.Row]:
    conn = get_db()
    rows = conn.execute(
        """
        SELECT brews.grinder, brews.grind_setting, AVG(brews.rating) AS avg_rating, COUNT(*) AS n
        FROM brews
        WHERE brews.bag_id = ?
        GROUP BY brews.grinder, brews.grind_setting
        ORDER BY avg_rating DESC, n DESC
        """,
        (bag_id,),
    ).fetchall()
    conn.close()
    return rows


def build_product_log_filters(args: Any) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    for field in ("entry_kind", "status", "priority"):
        value = args.get(field, "").strip()
        if not value:
            continue
        clauses.append(f"{field} = ?")
        params.append(value)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def fetch_product_log_entries(filters: tuple[str, list[Any]]) -> list[sqlite3.Row]:
    where, params = filters
    conn = get_db()
    rows = conn.execute(
        f"""
        SELECT *
        FROM product_log_entries
        {where}
        ORDER BY COALESCE(entry_date, created_at) DESC, updated_at DESC
        """
        ,
        params,
    ).fetchall()
    conn.close()
    return rows


def fetch_product_log_entry(entry_id: int) -> sqlite3.Row | None:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM product_log_entries WHERE id = ?",
        (entry_id,),
    ).fetchone()
    conn.close()
    return row


def fetch_bags_for_equator(filters: tuple[str, list[Any]]) -> list[sqlite3.Row]:
    where, params = filters
    conn = get_db()
    rows = conn.execute(
        f"""
        SELECT
            bags.id,
            bags.coffee_name,
            bags.brand,
            bags.country,
            bags.location,
            bags.latitude,
            bags.longitude,
            bags.continent,
            AVG(brews.rating) AS avg_rating
        FROM bags
        LEFT JOIN brews ON brews.bag_id = bags.id
        {where}
        GROUP BY bags.id
        ORDER BY bags.created_at DESC
        """
        ,
        params,
    ).fetchall()
    conn.close()
    return rows


def insert_bag(conn: sqlite3.Connection, bag_data: dict[str, Any], photo: Any = None) -> int:
    continent = continent_from_latlon(bag_data["latitude"], bag_data["longitude"])
    cursor = conn.execute(
        """
        INSERT INTO bags (
            coffee_name, brand, varietal, flavours, country, location, process,
            latitude, longitude, altitude_m, continent, owner_user, photo_path, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            bag_data["coffee_name"],
            bag_data["brand"],
            bag_data["varietal"],
            bag_data["flavours"],
            bag_data["country"],
            bag_data["location"],
            bag_data["process"],
            bag_data["latitude"],
            bag_data["longitude"],
            bag_data["altitude_m"],
            continent,
            bag_data["owner_user"],
            None,
            datetime.utcnow().isoformat(timespec="seconds"),
        ),
    )
    bag_id = int(cursor.lastrowid)
    photo_path = save_bag_photo(bag_id, photo)
    if photo_path:
        conn.execute(
            "UPDATE bags SET photo_path = ? WHERE id = ?",
            (photo_path, bag_id),
        )
    return bag_id


def save_bag_photo(bag_id: int, photo_file: Any) -> str | None:
    if not photo_file or not photo_file.filename:
        return None
    allowed_types = {"image/jpeg", "image/png"}
    if photo_file.mimetype not in allowed_types:
        return None
    try:
        image = Image.open(photo_file)
    except (OSError, ValueError):
        return None
    image = image.convert("RGB")
    image.thumbnail((800, 800))
    uploads_dir = BASE_DIR / "static" / "uploads" / "bags"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    filename = f"bag-{bag_id}.webp"
    output_path = uploads_dir / filename
    image.save(output_path, format="WEBP", quality=75)
    return f"uploads/bags/{filename}"


@app.route("/")
def index() -> Any:
    return redirect(url_for("add_coffee"))


@app.route("/add", methods=["GET", "POST"])
def add_coffee() -> Any:
    init_db()
    bag_options = fetch_bag_options()
    bag_options_data = [dict(row) for row in bag_options]
    selected_bag_id = request.args.get("bag_id") or request.form.get("bag_id")
    selected_entry_mode = request.form.get("entry_mode", "brew")
    if request.method == "POST":
        selected_entry_mode = request.form.get("entry_mode", "brew")
        bag_only_mode = selected_entry_mode == "bag"
        bag_id = parse_optional_int(selected_bag_id)
        bag_data: dict[str, Any] = {}
        errors: list[str] = []
        if bag_only_mode:
            bag_data, errors = validate_bag_payload(request.form)
        if not bag_only_mode and not bag_id:
            errors.append("Select an existing bag.")
        brew_data: dict[str, Any] = {}
        brew_steps: list[dict[str, Any]] = []
        if not bag_only_mode:
            brew_data, brew_errors = validate_brew_payload(request.form)
            errors.extend(brew_errors)
            brew_steps, step_errors = parse_brew_steps(request.form.get("brew_steps_json"))
            errors.extend(step_errors)

        if errors:
            for error in errors:
                flash(error, "error")
        else:
            conn = get_db()
            if bag_only_mode:
                bag_id = insert_bag(conn, bag_data, request.files.get("bag_photo"))
            else:
                brew_cursor = conn.execute(
                    """
                    INSERT INTO brews (
                        bag_id, date, rating, brew_style, grinder, logged_by_user,
                        grind_setting, notes, dose_g, water_ml, temp_c,
                        total_brew_s, pour_time_s, bloom_water_ml, bloom_time_s,
                        agitation, recipe_notes, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        bag_id,
                        brew_data["date"],
                        brew_data["rating"],
                        brew_data["brew_style"],
                        brew_data["grinder"],
                        brew_data["logged_by_user"],
                        brew_data["grind_setting"],
                        brew_data["notes"],
                        brew_data["dose_g"],
                        brew_data["water_ml"],
                        brew_data["temp_c"],
                        brew_data["total_brew_s"],
                        brew_data["pour_time_s"],
                        brew_data["bloom_water_ml"],
                        brew_data["bloom_time_s"],
                        brew_data["agitation"],
                        brew_data["recipe_notes"],
                        datetime.utcnow().isoformat(timespec="seconds"),
                    ),
                )
                brew_id = int(brew_cursor.lastrowid)
                for step in brew_steps:
                    conn.execute(
                        """
                        INSERT INTO brew_steps (
                            brew_id, step_order, start_seconds, end_seconds, label_text, liquid_text
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            brew_id,
                            step["step_order"],
                            step["start_seconds"],
                            step["end_seconds"],
                            step["label_text"],
                            step["liquid_text"],
                        ),
                    )
            conn.commit()
            conn.close()
            flash("Bag added successfully." if bag_only_mode else "Brew logged successfully.", "success")
            return redirect(url_for("bag_detail", bag_id=bag_id))

    return render_template(
        "add.html",
        grinders=ALLOWED_GRINDERS,
        aergrind_settings=AERGRIND_SETTINGS,
        belinda_settings=BELINDA_SETTINGS,
        brew_styles=ALLOWED_BREW_STYLES,
        users=ALLOWED_USERS,
        processes=ALLOWED_PROCESSES,
        today_date=datetime.now().date().isoformat(),
        bag_options=bag_options,
        bag_options_data=bag_options_data,
        selected_bag_id=selected_bag_id,
        selected_entry_mode=selected_entry_mode,
    )


@app.post("/brews/<int:brew_id>/recipe")
def update_brew_recipe(brew_id: int) -> Any:
    init_db()
    recipe_data, errors = parse_recipe_fields(request.form)
    if errors:
        for error in errors:
            flash(error, "error")
        return redirect(request.referrer or url_for("log"))
    conn = get_db()
    conn.execute(
        """
        UPDATE brews
        SET dose_g = ?,
            water_ml = ?,
            temp_c = ?,
            total_brew_s = ?,
            pour_time_s = ?,
            bloom_water_ml = ?,
            bloom_time_s = ?,
            agitation = ?,
            recipe_notes = ?
        WHERE id = ?
        """,
        (
            recipe_data["dose_g"],
            recipe_data["water_ml"],
            recipe_data["temp_c"],
            recipe_data["total_brew_s"],
            recipe_data["pour_time_s"],
            recipe_data["bloom_water_ml"],
            recipe_data["bloom_time_s"],
            recipe_data["agitation"],
            recipe_data["recipe_notes"],
            brew_id,
        ),
    )
    conn.commit()
    conn.close()
    flash("Recipe updated.", "success")
    return redirect(request.referrer or url_for("log"))


@app.route("/log")
def log() -> Any:
    init_db()
    entry_id = request.args.get("entry_id")
    filters = build_filters_from_request(request.args)
    coffees = fetch_brews(filters)
    return render_template(
        "log.html",
        coffees=coffees,
        entry_id=entry_id,
        allow_demo_seed=app.config["ALLOW_DEMO_SEED"],
        build_query=build_query,
        distinct_values=build_distinct_values(include_brew_fields=True),
    )


@app.route("/map")
def map_view() -> Any:
    init_db()
    filters = build_filters_from_request(request.args)
    bag_id = request.args.get("bag_id")
    where, params = filters
    if bag_id:
        where = combine_where(where, "bags.id = ?")
        params.append(bag_id)
    coffees = [
        dict(row)
        for row in fetch_brews((where, params))
        if row["latitude"] is not None and row["longitude"] is not None
    ]
    latest_brew_id = None
    if bag_id:
        try:
            latest_brew_id = fetch_latest_brew_id_for_bag(int(bag_id))
        except ValueError:
            latest_brew_id = None
    return render_template(
        "map.html",
        coffees=json.dumps(coffees),
        latest_brew_id=latest_brew_id,
        build_query=build_query,
        distinct_values=build_distinct_values(include_brew_fields=True),
    )


@app.route("/altitude")
def altitude_view() -> Any:
    init_db()
    filters = build_filters_from_request(request.args)
    coffees = [
        dict(row)
        for row in fetch_brews(filters)
        if row["altitude_m"] is not None
    ]
    return render_template(
        "altitude.html",
        coffees=json.dumps(coffees),
        build_query=build_query,
        distinct_values=build_distinct_values(include_brew_fields=True),
    )


@app.route("/equator")
def equator_view() -> Any:
    init_db()
    filters = build_bag_filters_from_request(request.args)
    bags = [
        dict(row)
        for row in fetch_bags_for_equator(filters)
        if row["latitude"] is not None and row["longitude"] is not None
    ]
    return render_template(
        "equator.html",
        bags=json.dumps(bags),
        build_query=build_query,
        distinct_values=build_distinct_values(include_brew_fields=False),
    )


@app.route("/bags")
def bags_view() -> Any:
    init_db()
    user = request.args.get("user")
    bags = fetch_bag_summary(user)
    return render_template("bags.html", bags=bags, users=ALLOWED_USERS, selected_user=user)


@app.route("/bags/<int:bag_id>")
def bag_detail(bag_id: int) -> Any:
    init_db()
    bag = fetch_bag_detail(bag_id)
    if not bag:
        flash("Bag not found.", "error")
        return redirect(url_for("bags_view"))
    brews = fetch_brews_for_bag(bag_id)
    grind_insights = fetch_grind_insights(bag_id)
    brew_steps_by_brew = fetch_steps_for_brew_ids([int(brew["id"]) for brew in brews])
    latest_brew_id = brews[0]["id"] if brews else None
    dial_in_assistant = build_dial_in_assistant(brews)
    return render_template(
        "bag_detail.html",
        bag=bag,
        brews=brews,
        grind_insights=grind_insights,
        brew_steps_by_brew=brew_steps_by_brew,
        latest_brew_id=latest_brew_id,
        dial_in_assistant=dial_in_assistant,
    )


@app.route("/bags/<int:bag_id>/flavours", methods=["POST"])
def update_bag_flavours(bag_id: int) -> Any:
    init_db()
    flavours = normalize_flavours(request.form.get("flavours", ""))
    conn = get_db()
    conn.execute(
        "UPDATE bags SET flavours = ? WHERE id = ?",
        (flavours, bag_id),
    )
    conn.commit()
    conn.close()
    flash("Bag flavours updated.", "success")
    return redirect(url_for("bag_detail", bag_id=bag_id))


@app.route("/product-log")
def product_log() -> Any:
    init_db()
    filters = build_product_log_filters(request.args)
    entries = fetch_product_log_entries(filters)
    return render_template(
        "product_log.html",
        entries=entries,
        filters={
            "entry_kind": request.args.get("entry_kind", "").strip(),
            "status": request.args.get("status", "").strip(),
            "priority": request.args.get("priority", "").strip(),
        },
        entry_kinds=ALLOWED_PRODUCT_ENTRY_KINDS,
        statuses=ALLOWED_PRODUCT_STATUSES,
        priorities=ALLOWED_PRODUCT_PRIORITIES,
        today_date=datetime.now().date().isoformat(),
    )


@app.post("/product-log/quick-add")
def product_log_quick_add() -> Any:
    init_db()
    title = request.form.get("title", "").strip()
    summary = request.form.get("summary", "").strip()
    priority = request.form.get("priority", "medium").strip() or "medium"
    if not title:
        flash("Quick add title is required.", "error")
        return redirect(url_for("product_log"))
    if priority not in ALLOWED_PRODUCT_PRIORITIES:
        flash("Priority must be low, medium, or high.", "error")
        return redirect(url_for("product_log"))
    now = datetime.utcnow().isoformat(timespec="seconds")
    entry_date = datetime.now().date().isoformat()
    conn = get_db()
    conn.execute(
        """
        INSERT INTO product_log_entries (
            title, entry_kind, status, priority, version_label,
            entry_date, summary, testing_notes, known_issues,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            title,
            "idea",
            "idea",
            priority,
            "",
            entry_date,
            summary,
            "",
            "",
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()
    flash("Idea captured.", "success")
    return redirect(url_for("product_log"))


@app.post("/product-log")
def create_product_log_entry() -> Any:
    init_db()
    payload, errors = parse_product_log_payload(request.form)
    if errors:
        for error in errors:
            flash(error, "error")
        return redirect(url_for("product_log"))
    now = datetime.utcnow().isoformat(timespec="seconds")
    conn = get_db()
    conn.execute(
        """
        INSERT INTO product_log_entries (
            title, entry_kind, status, priority, version_label,
            entry_date, summary, testing_notes, known_issues,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["title"],
            payload["entry_kind"],
            payload["status"],
            payload["priority"],
            payload["version_label"],
            payload["entry_date"],
            payload["summary"],
            payload["testing_notes"],
            payload["known_issues"],
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()
    flash("Product log entry added.", "success")
    return redirect(url_for("product_log"))


@app.route("/product-log/<int:entry_id>/edit", methods=["GET", "POST"])
def edit_product_log_entry(entry_id: int) -> Any:
    init_db()
    entry = fetch_product_log_entry(entry_id)
    if not entry:
        flash("Product log entry not found.", "error")
        return redirect(url_for("product_log"))
    if request.method == "POST":
        payload, errors = parse_product_log_payload(request.form)
        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "product_log_edit.html",
                entry=entry,
                form_data=request.form,
                entry_kinds=ALLOWED_PRODUCT_ENTRY_KINDS,
                statuses=ALLOWED_PRODUCT_STATUSES,
                priorities=ALLOWED_PRODUCT_PRIORITIES,
            )
        now = datetime.utcnow().isoformat(timespec="seconds")
        conn = get_db()
        conn.execute(
            """
            UPDATE product_log_entries
            SET title = ?,
                entry_kind = ?,
                status = ?,
                priority = ?,
                version_label = ?,
                entry_date = ?,
                summary = ?,
                testing_notes = ?,
                known_issues = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                payload["title"],
                payload["entry_kind"],
                payload["status"],
                payload["priority"],
                payload["version_label"],
                payload["entry_date"],
                payload["summary"],
                payload["testing_notes"],
                payload["known_issues"],
                now,
                entry_id,
            ),
        )
        conn.commit()
        conn.close()
        flash("Product log entry updated.", "success")
        return redirect(url_for("product_log"))
    return render_template(
        "product_log_edit.html",
        entry=entry,
        form_data=entry,
        entry_kinds=ALLOWED_PRODUCT_ENTRY_KINDS,
        statuses=ALLOWED_PRODUCT_STATUSES,
        priorities=ALLOWED_PRODUCT_PRIORITIES,
    )


@app.post("/product-log/<int:entry_id>/delete")
def delete_product_log_entry(entry_id: int) -> Any:
    init_db()
    conn = get_db()
    conn.execute("DELETE FROM product_log_entries WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()
    flash("Product log entry deleted.", "success")
    return redirect(url_for("product_log"))


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
        "continents": fetch_ranked_field("continent", filters),
        "countries": fetch_ranked_field("country", filters),
        "regions": fetch_ranked_regions(filters),
        "coffee_names": fetch_ranked_field("coffee_name", filters),
        "processes": fetch_ranked_field("process", filters),
    }

    where, params = filters
    conn = get_db()
    total_count = conn.execute(
        f"""
        SELECT COUNT(*) AS n
        FROM brews
        JOIN bags ON bags.id = brews.bag_id
        {where}
        """,
        params,
    ).fetchone()["n"]
    altitude_where = combine_where(where, "bags.altitude_m IS NOT NULL")
    altitude_rows = conn.execute(
        f"""
        SELECT bags.altitude_m, brews.rating, bags.coffee_name, bags.brand
        FROM brews
        JOIN bags ON bags.id = brews.bag_id
        {altitude_where}
        """,
        params,
    ).fetchall()
    highest_row = conn.execute(
        f"""
        SELECT bags.coffee_name, bags.brand, bags.altitude_m
        FROM brews
        JOIN bags ON bags.id = brews.bag_id
        {altitude_where}
        ORDER BY bags.altitude_m DESC
        LIMIT 1
        """,
        params,
    ).fetchone()
    lowest_row = conn.execute(
        f"""
        SELECT bags.coffee_name, bags.brand, bags.altitude_m
        FROM brews
        JOIN bags ON bags.id = brews.bag_id
        {altitude_where}
        ORDER BY bags.altitude_m ASC
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
        selection_map = {
            "coffee_name": "bags.coffee_name",
            "brand": "bags.brand",
            "varietal": "bags.varietal",
            "brew_style": "brews.brew_style",
            "continent": "bags.continent",
            "country": "bags.country",
            "location": "bags.location",
            "process": "bags.process",
        }
        if dim in selection_map:
            selection_where = combine_where(selection_where, f"{selection_map[dim]} = ?")
            selection_params.append(value)
            selection_title = f"{dim.replace('_', ' ').title()}: {value}"
        elif dim == "region":
            parts = value.split("||", 1)
            country = parts[0] if parts else ""
            location = parts[1] if len(parts) > 1 else ""
            if country:
                selection_where = combine_where(selection_where, "bags.country = ?")
                selection_params.append(country)
            if location:
                selection_where = combine_where(selection_where, "bags.location = ?")
                selection_params.append(location)
            region_label = f"{country} · {location}".strip(" ·")
            if region_label:
                selection_title = f"Region: {region_label}"
        elif dim == "altitude_bin":
            bin_lookup = {bin_item["label"]: bin_item for bin_item in altitude_bins}
            bin_item = bin_lookup.get(value)
            if bin_item:
                selection_title = f"Altitude: {value}"
                selection_where = combine_where(selection_where, "bags.altitude_m IS NOT NULL")
                selection_where = combine_where(selection_where, "bags.altitude_m >= ?")
                selection_params.append(bin_item["min"])
                if bin_item["max"] is not None:
                    selection_where = combine_where(selection_where, "bags.altitude_m < ?")
                    selection_params.append(bin_item["max"])

        if selection_title:
            conn = get_db()
            summary = conn.execute(
                f"""
                SELECT AVG(brews.rating) AS avg_rating, COUNT(*) AS n
                FROM brews
                JOIN bags ON bags.id = brews.bag_id
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
            selection_coffees = fetch_brews((selection_where, selection_params))

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
        continents=get_distinct_values("continent"),
    )


@app.route("/api/suggest")
def suggest() -> Any:
    field = request.args.get("field", "")
    term = request.args.get("term", "").strip().lower()
    if field not in {
        "coffee_name",
        "brand",
        "varietal",
        "country",
        "location",
        "process",
        "flavours",
        "brew_style",
        "grinder",
        "grind_setting",
    }:
        return jsonify([])
    field_map = {
        "coffee_name": "bags.coffee_name",
        "brand": "bags.brand",
        "varietal": "bags.varietal",
        "country": "bags.country",
        "location": "bags.location",
        "process": "bags.process",
        "flavours": "bags.flavours",
        "brew_style": "brews.brew_style",
        "grinder": "brews.grinder",
        "grind_setting": "brews.grind_setting",
    }
    column = field_map[field]
    if field == "flavours":
        conn = get_db()
        rows = conn.execute(
            """
            SELECT DISTINCT bags.flavours AS value
            FROM bags
            WHERE bags.flavours IS NOT NULL AND bags.flavours != ''
            """
        ).fetchall()
        conn.close()
        tokens = extract_flavour_tokens([row["value"] for row in rows])
        if term:
            tokens = [token for token in tokens if token.lower().startswith(term)]
        return jsonify(tokens[:8])
    conn = get_db()
    rows = conn.execute(
        f"""
        SELECT DISTINCT {column} AS value
        FROM brews
        JOIN bags ON bags.id = brews.bag_id
        WHERE {column} IS NOT NULL
          AND {column} != ''
          AND LOWER({column}) LIKE ?
        ORDER BY {column}
        LIMIT 8
        """,
        (f"%{term}%",),
    ).fetchall()
    conn.close()
    return jsonify([row["value"] for row in rows])


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


@app.route("/api/geocode_search")
def geocode_search() -> Any:
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"ok": False, "error": "Missing query."})
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"format": "jsonv2", "q": query, "limit": 5},
            headers={
                "User-Agent": "CoffeeLog/1.0 (coffeelog@example.com)",
                "Accept": "application/json",
            },
            timeout=6,
        )
        response.raise_for_status()
        results = response.json()
        candidates = [
            {
                "display_name": result.get("display_name"),
                "lat": float(result["lat"]),
                "lon": float(result["lon"]),
            }
            for result in results
            if result.get("lat") and result.get("lon")
        ]
        return jsonify({"ok": True, "results": candidates})
    except (requests.RequestException, ValueError, TypeError):
        return jsonify({"ok": False, "error": "Location search failed."})


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
    if not app.config["ALLOW_DEMO_SEED"]:
        flash("Seeding is disabled in this environment.", "error")
        return redirect(url_for("bags_view"))
    from seed import seed_data

    init_db()
    inserted = seed_data(get_db())
    flash(f"Seeded {inserted} brews.", "success")
    return redirect(url_for("bags_view"))


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
