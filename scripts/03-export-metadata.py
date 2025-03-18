#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["httpx", "tqdm"]
# [tool.uv]
# exclude-newer = "2025-03-13T00:00:00Z"
# ///

import json
from pathlib import Path

import httpx  # type: ignore
from tqdm import tqdm

# Load tables data from JSONL file
data_dir = Path("ine")
tables_file = data_dir / "tablas.jsonl"

print(f"Loading tables data from {tables_file}...")
tables = []
with open(tables_file, "r", encoding="utf-8") as f:
    for line in f:
        tables.append(json.loads(line))

print(f"\t✓ Loaded {len(tables)} tables")


def save_jsonl(data, filename):
    with open(filename, "w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


for table in tqdm(tables, desc="Processing Table Metadata"):
    url = f"https://servicios.ine.es/wstempus/jsCache/ES/SERIES_TABLA/{table['Id']}?det=10"
    response = httpx.get(url)
    data = response.json()

    directory = data_dir / "tablas" / str(table["Id"])
    directory.mkdir(exist_ok=True)

    save_jsonl(data, directory / "metadata_series.jsonl")
