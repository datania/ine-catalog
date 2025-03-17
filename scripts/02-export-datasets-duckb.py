#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["duckdb"]
# [tool.uv]
# exclude-newer = "2025-03-13T00:00:00Z"
# ///

import json
from pathlib import Path

import duckdb

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

failed_tables = []
total_tables = len(tables)

for i, table in enumerate(tables):
    if i % 50 == 0 or i == total_tables - 1:
        print(f"Processing table {i + 1}/{total_tables}: {table['Id']}")
    try:
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
    except Exception as e:
        print(f"Error processing table {table['Id']}: {str(e)}")
        failed_tables.append(table["Id"])

if failed_tables:
    print(f"\nFailed to process {len(failed_tables)} tables:")
    for table_id in failed_tables:
        print(f"- {table_id}")
else:
    print("\nAll tables processed successfully!")
