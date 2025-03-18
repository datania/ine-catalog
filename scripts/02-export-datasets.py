#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["duckdb", "tqdm"]
# [tool.uv]
# exclude-newer = "2025-03-13T00:00:00Z"
# ///

import json
from pathlib import Path

import duckdb  # type: ignore
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


c = duckdb.connect()
c.sql("""
CREATE SECRET http (TYPE http, EXTRA_HTTP_HEADERS MAP {'Accept-Encoding': 'gzip'});
""")

# Create directories for output data
ine_dir = Path("ine/tablas")
ine_dir.mkdir(exist_ok=True, parents=True)

print(f"Created output directory: {ine_dir}")

failed_tables = []

for table in tqdm(tables, desc="Processing INE Tables"):
    try:
        directory = ine_dir / str(table["Id"])
        directory.mkdir(exist_ok=True)
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
            to 'ine/tablas/{table["Id"]}/datos.parquet' (
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
