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
VARIETALS = ["Bourbon", "Gesha", "Caturra", "SL28", "Heirloom", "Pacamara"]
PROCESSES = ["washed", "natural", "anaerobic", "honey"]
FLAVOURS = [
    "strawberry, jasmine, cacao",
    "bergamot, peach, black tea",
    "chocolate, almond, cherry",
    "pineapple, lemongrass, honey",
    "blackberry, florals, lime",
]


def seed_data(conn: sqlite3.Connection) -> int:
    cursor = conn.cursor()
    now = datetime.utcnow()
    count = 0

    for i in range(60):
        country, location, lat, lon = random.choice(COUNTRIES)
        grinder = random.choice(ALLOWED_GRINDERS)
        grind_setting = random.choice(AERGRIND_SETTINGS if grinder == "Aergrind (Nicholas)" else BELINDA_SETTINGS)
        date_value = (now - timedelta(days=random.randint(0, 120))).date().isoformat()
        altitude = random.randint(1200, 2200)

        cursor.execute(
            """
            INSERT INTO coffees (
                date, brand, varietal, altitude_m, latitude, longitude,
                location, country, process, flavours, rating, grinder, grind_setting,
                brew_style, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                date_value,
                random.choice(BRANDS),
                random.choice(VARIETALS),
                altitude,
                lat + random.uniform(-0.3, 0.3),
                lon + random.uniform(-0.3, 0.3),
                location,
                country,
                random.choice(PROCESSES),
                random.choice(FLAVOURS),
                random.randint(3, 5),
                grinder,
                grind_setting,
                random.choice(ALLOWED_BREW_STYLES),
                now.isoformat(timespec="seconds"),
            ),
        )
        count += 1

    conn.commit()
    return count


if __name__ == "__main__":
    init_db()
    connection = sqlite3.connect("coffeelog.db")
    inserted = seed_data(connection)
    connection.close()
    print(f"Seeded {inserted} coffees.")
