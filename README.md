# Coffee Log

A minimal Flask + SQLite MVP to log coffees, browse entries, and explore origins on a map.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
flask --app app run --debug
```

Visit:
- `http://localhost:5000/add` to add a coffee
- `http://localhost:5000/log` to browse your log
- `http://localhost:5000/map` to explore on a map

The add form can fetch elevation data from the free Open-Elevation API when you pick a location.

## Seed synthetic data

```bash
python seed.py
```

Or use the **Seed demo data** button on the log page (MVP demo only).
