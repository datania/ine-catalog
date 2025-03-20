#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["httpx", "tqdm", "asyncio", "polars"]
# [tool.uv]
# exclude-newer = "2025-03-13T00:00:00Z"
# ///
import json
from pathlib import Path

import httpx  # type: ignore
import polars as pl  # type: ignore
from tqdm import tqdm  # type: ignore

# Load tables data from JSONL file
data_dir = Path("ine")
tables_file = data_dir / "tablas.jsonl"

print(f"Loading tables data from {tables_file}...")
tables = []
with open(tables_file, "r", encoding="utf-8") as f:
    for line in f:
        tables.append(json.loads(line))

print(f"\t✓ Loaded {len(tables)} tables")


def save_parquet(data, filename):
    pl.DataFrame(data).write_parquet(
        filename, compression="zstd", row_group_size=1048576
    )


# Create directories for output data
ine_dir = Path("ine/tablas")
ine_dir.mkdir(exist_ok=True, parents=True)

client = httpx.Client(
    transport=httpx.HTTPTransport(retries=3),
    limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
    timeout=60,
)

for table in tqdm(tables, desc="Processing INE Tables"):
    url = f"https://servicios.ine.es/wstempus/jsCache/ES/SERIES_TABLA/{table['Id']}?det=10"

    try:
        headers = {"Accept-Encoding": "gzip"}
        response = client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

        directory = ine_dir / str(table["Id"])
        directory.mkdir(exist_ok=True)

        save_parquet(data, directory / "metadatos_series.parquet")

    except Exception as e:
        print(f"Error processing table {table['Id']}: {e}")
        continue
