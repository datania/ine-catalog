#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["httpx", "tqdm", "asyncio", "polars"]
# [tool.uv]
# exclude-newer = "2025-03-13T00:00:00Z"
# ///
import argparse
import asyncio
import json
from pathlib import Path

import httpx  # type: ignore
import polars as pl  # type: ignore
from tqdm import tqdm  # type: ignore

parser = argparse.ArgumentParser()
parser.add_argument("--split", type=int, default=1, help="Split number to process")
parser.add_argument("--max-splits", type=int, default=1, help="Total number of splits")
args = parser.parse_args()

# Sanity check for split and max_splits arguments
if args.split <= 0:
    raise ValueError("Split number must be greater than 0")

if args.max_splits <= 0:
    raise ValueError("Max splits must be greater than 0")

if args.split > args.max_splits:
    raise ValueError(
        f"Split number ({args.split}) cannot be greater than max splits ({args.max_splits})"
    )

print(f"Processing split {args.split} of {args.max_splits}")

# Load tables data from JSONL file
data_dir = Path("ine")
tables_file = data_dir / "tablas.jsonl"

print(f"Loading tables data from {tables_file}...")
tables = []
with open(tables_file, "r", encoding="utf-8") as f:
    for line in f:
        tables.append(json.loads(line))

tables = tables[args.split - 1 :: args.max_splits]

print(f"\t✓ Loaded {len(tables)} tables")


def save_parquet(data, filename):
    pl.DataFrame(data).write_parquet(
        filename, compression="zstd", row_group_size=1048576
    )


# Create directories for output data
ine_dir = Path("ine/tablas")
ine_dir.mkdir(exist_ok=True, parents=True)


async def fetch_table_metadata(client, table, semaphore, pbar):
    async with semaphore:
        url = f"https://servicios.ine.es/wstempus/jsCache/ES/SERIES_TABLA/{table['Id']}?det=10"
        try:
            # Request gzipped content
            headers = {"Accept-Encoding": "gzip"}
            response = await client.get(url, headers=headers)
            data = response.json()

            directory = ine_dir / str(table["Id"])
            directory.mkdir(exist_ok=True)

            save_parquet(data, directory / "metadatos_series.parquet")
            pbar.update(1)
        except Exception as e:
            print(f"Error processing table {table['Id']}: {e}")
            pbar.update(1)


async def main():
    # Configure client with proper retry and connection limits
    transport = httpx.AsyncHTTPTransport(retries=3)
    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)

    # Create semaphore to limit concurrent requests
    semaphore = asyncio.Semaphore(5)

    # Create progress bar
    pbar = tqdm(total=len(tables), desc="Processing Table Metadata")

    async with httpx.AsyncClient(
        transport=transport, limits=limits, timeout=60
    ) as client:
        # Create tasks for each table
        tasks = [
            fetch_table_metadata(client, table, semaphore, pbar) for table in tables
        ]
        # Execute all tasks concurrently
        await asyncio.gather(*tasks)

    pbar.close()


asyncio.run(main())
