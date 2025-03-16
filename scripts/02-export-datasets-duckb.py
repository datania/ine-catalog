#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["duckdb", "tqdm"]
# [tool.uv]
# exclude-newer = "2025-03-13T00:00:00Z"
# ///

import json
from pathlib import Path

import duckdb
from tqdm import tqdm

# Load tables data from JSON file
data_dir = Path("data")
tables_file = data_dir / "tablas.json"

print(f"Loading tables data from {tables_file}...")
with open(tables_file, "r", encoding="utf-8") as f:
    tables = json.load(f)

print(f"\t✓ Loaded {len(tables)} tables")


c = duckdb.connect()
c.sql("""
CREATE SECRET http (TYPE http, EXTRA_HTTP_HEADERS MAP {'Accept-Encoding': 'gzip'});
""")

# Create directories for output data
ine_dir = Path("data/ine")
ine_dir.mkdir(exist_ok=True, parents=True)

print(f"Created output directory: {ine_dir}")


for table in tqdm(tables, desc="Processing tables"):
    c.sql(f"""
        copy (
            from read_csv(
                'https://www.ine.es/jaxiT3/files/t/en/csv_bdsc/{table["Id"]}.csv',
                delim=';',
                ignore_errors=true,
                normalize_names=true,
                null_padding=true,
                parallel=true,
                strict_mode=false,
                compression='gzip'
            )
        )
        to 'data/ine/{table["Id"]}.parquet' (
            format parquet,
            compression 'zstd',
            parquet_version v2,
            row_group_size 1048576
        );
    """)
