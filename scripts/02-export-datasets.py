#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["duckdb", "tqdm", "asyncio"]
# [tool.uv]
# exclude-newer = "2025-03-13T00:00:00Z"
# ///

import asyncio
import json
from pathlib import Path

import duckdb  # type: ignore
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


# Create directories for output data
ine_dir = Path("ine/tablas")
ine_dir.mkdir(exist_ok=True, parents=True)

print(f"Created output directory: {ine_dir}")

failed_tables = []


async def process_table(table, semaphore, pbar, conn):
    async with semaphore:
        try:
            directory = ine_dir / str(table["Id"])
            directory.mkdir(exist_ok=True)

            # Execute in a separate thread since DuckDB operations are blocking
            await asyncio.to_thread(
                conn.sql,
                f"""
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
                """,
            )
            pbar.update(1)
        except Exception as e:
            print(f"Error processing table {table['Id']}: {str(e)}")
            failed_tables.append(table["Id"])
            pbar.update(1)


async def main():
    # Create DuckDB connection
    conn = duckdb.connect()
    conn.sql("""
    CREATE SECRET http (TYPE http, EXTRA_HTTP_HEADERS MAP {'Accept-Encoding': 'gzip'});
    """)

    # Create semaphore to limit concurrent requests
    semaphore = asyncio.Semaphore(30)

    # Create progress bar
    pbar = tqdm(total=len(tables), desc="Processing INE Tables")

    # Create tasks for each table
    tasks = [process_table(table, semaphore, pbar, conn) for table in tables]

    # Execute all tasks concurrently
    await asyncio.gather(*tasks)

    pbar.close()

    # Report failed tables
    if failed_tables:
        print(f"\nFailed to process {len(failed_tables)} tables:")
        for table_id in failed_tables:
            print(f"- {table_id}")
    else:
        print("\nAll tables processed successfully!")


# Run the main async function
asyncio.run(main())
