#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# [tool.uv]
# exclude-newer = "2025-03-13T00:00:00Z"
# ///

import json
import subprocess
from pathlib import Path

# Load tables data from JSON file
data_dir = Path("data")
tables_file = data_dir / "tablas.json"

print(f"Loading tables data from {tables_file}...")
with open(tables_file, "r", encoding="utf-8") as f:
    tables = json.load(f)

print(f"\t✓ Loaded {len(tables)} tables")


print("Fetching SERIES_TABLA...")

LIMIT = 50
with (
    open("/tmp/series.input.spec", "w") as series_spec,
    open("/tmp/tablas.input.spec", "w") as tables_spec,
):
    for t in tables[:LIMIT]:
        # Series
        series_url = f"https://servicios.ine.es/wstempus/jsCache/ES/SERIES_TABLA/{t['Id']}?det=10"
        series_spec.write(f"{series_url}\n")
        series_spec.write("\tout=series_metadata.json\n")
        series_spec.write(f"\tdir=data/tablas/{t['Id']}\n\n")
        # Tables
        tables_url = f"https://www.ine.es/jaxiT3/files/t/es/csv_bdsc/{t['Id']}.csv"
        tables_spec.write(f"{tables_url}\n")
        tables_spec.write(f"\tout={t['Id']}.csv\n")
        tables_spec.write(f"\tdir=data/tablas/{t['Id']}\n\n")

subprocess.run(
    [
        "aria2c",
        "-i /tmp/series.input.spec",
        "-j 16",
        "-x 16",
        "-s 16",
        "-k 20M",
        "-c",
        "--file-allocation=none",
        "--optimize-concurrent-downloads=true",
        "--retry-wait=120",
        "--max-tries=10",
        "--connect-timeout=10",
        "--continue=true",
        "--timeout=10",
        "--log=/tmp/series_csv_aria2.log",
        "--log-level=warn",
        "--auto-file-renaming=false",
        "--console-log-level=warn",
        "--allow-overwrite=true",
    ],
    check=True,
    capture_output=True,
)

print("\t✓ Done!")

print("Fetching TABLES CSV files...")

subprocess.run(
    [
        "aria2c",
        "-i /tmp/tablas.input.spec",
        "-j 16",
        "-x 16",
        "-s 16",
        "-k 20M",
        "-c",
        "--file-allocation=none",
        "--optimize-concurrent-downloads=true",
        "--retry-wait=120",
        "--max-tries=10",
        "--connect-timeout=10",
        "--continue=true",
        "--timeout=10",
        "--log=/tmp/tables_csv_aria2.log",
        "--log-level=warn",
        "--auto-file-renaming=false",
        "--console-log-level=warn",
        "--allow-overwrite=true",
        "--on-download-complete=scripts/hook.py",
    ],
    check=True,
    capture_output=True,
)

print("\t✓ Done!")

# TODO: Do another round looking for the missing files and retry those
# grep -rl "unos minutos" data/tablas/*
