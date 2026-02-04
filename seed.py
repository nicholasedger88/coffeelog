from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timedelta

from app import (
    ALLOWED_BREW_STYLES,
    ALLOWED_GRINDERS,
    AERGRIND_SETTINGS,
    BELINDA_SETTINGS,
    init_db,
)

COUNTRIES = [
    ("Ethiopia", "Adado", 6.3056, 38.5721),
    ("Kenya", "Ichamama", -0.408, 36.952),
    ("Colombia", "San Agustin", 1.879, -76.275),
    ("Rwanda", "Kigali", -1.963, 29.807),
    ("Panama", "La Esmeralda", 8.766, -82.434),
    ("Brazil", "Patrocinio", -18.946, -46.993),
    ("Costa Rica", "Copey", 9.624, -84.083),
    ("Guatemala", "La Libertad", 15.314, -91.507),
    ("Indonesia", "Takengon", 4.627, 96.848),
    ("Peru", "Jaen", -5.708, -78.807),
    ("Burundi", "Masha", -2.904, 29.629),
    ("Tanzania", "Mbozi", -9.121, 33.944),
]

BRANDS = ["Dak", "Friedhats", "Onyx", "Five Elephant", "Tim Wendelboe", "Passenger"]
COFFEE_NAMES = [
    "Morning Drift",
    "Cinder Bloom",
    "Rain Song",
    "Amber Grove",
    "Field Note",
    "Aurora",
    "Cedar Valley",
    "Driftwood",
    "Mesa",
    "Lumen",
]
VARIETALS = ["Bourbon", "Gesha", "Caturra", "SL28", "Heirloom", "Pacamara"]
PROCESSES = ["washed", "natural", "anaerobic", "honey"]
FLAVOURS = [
    "strawberry, jasmine, cacao",
    "bergamot, peach, black tea",
    "chocolate, almond, cherry",
    "pineapple, lemongrass, honey",
    "blackberry, florals, lime",
]
NOTES = [
    "Sour, thin — went too coarse. Next: finer grind.",
    "Sweeter, more body — reduced sourness.",
    "Bright acidity, floral finish. Slightly faster pour.",
    "Bitter edge; extend bloom and grind coarser.",
    "Juicy and balanced. Keep ratio similar.",
]


def seed_data(conn: sqlite3.Connection) -> int:
    cursor = conn.cursor()
    now = datetime.utcnow()
    bag_ids: list[int] = []

    for _ in range(20):
        country, location, lat, lon = random.choice(COUNTRIES)
        coffee_name = random.choice(COFFEE_NAMES)
        brand = random.choice(BRANDS)
        varietal = random.choice(VARIETALS)
        altitude = random.randint(1200, 2200)
        cursor.execute(
            """
            INSERT INTO bags (
                coffee_name, brand, varietal, country, location, process,
                latitude, longitude, altitude_m, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                coffee_name,
                brand,
                varietal,
                country,
                location,
                random.choice(PROCESSES),
                lat + random.uniform(-0.3, 0.3),
                lon + random.uniform(-0.3, 0.3),
                altitude,
                now.isoformat(timespec="seconds"),
            ),
        )
        bag_ids.append(cursor.lastrowid)

    brew_count = 0
    for bag_id in bag_ids:
        for _ in range(random.randint(2, 4)):
            grinder = random.choice(ALLOWED_GRINDERS)
            if grinder == "Aergrind (Nicholas)":
                grind_setting = random.choice(AERGRIND_SETTINGS)["value"]
            else:
                grind_setting = random.choice(BELINDA_SETTINGS)
            date_value = (now - timedelta(days=random.randint(0, 120))).date().isoformat()
            cursor.execute(
                """
                INSERT INTO brews (
                    bag_id, date, flavours, rating, brew_style, grinder,
                    grind_setting, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bag_id,
                    date_value,
                    random.choice(FLAVOURS),
                    random.randint(2, 5),
                    random.choice(ALLOWED_BREW_STYLES),
                    grinder,
                    grind_setting,
                    random.choice(NOTES),
                    now.isoformat(timespec="seconds"),
                ),
            )
            brew_count += 1

    conn.commit()
    return brew_count


if __name__ == "__main__":
    init_db()
    connection = sqlite3.connect("coffeelog.db")
    inserted = seed_data(connection)
    connection.close()
    print(f"Seeded {inserted} brews.")
