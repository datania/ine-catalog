#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["polars", "tqdm"]
# [tool.uv]
# exclude-newer = "2025-03-13T00:00:00Z"
# ///

import glob
import os

import polars as pl  # type: ignore
from tqdm import tqdm  # type: ignore

csv_files = glob.glob("data/tablas/*/*.csv")

for file in tqdm(csv_files):
    filename = file.split(".")[-2].split("/")[-1]

    (
        pl.scan_csv(
            file,
            separator=";",
            ignore_errors=True,
            truncate_ragged_lines=True,
        ).sink_parquet(
            f"data/tablas/{filename}/datos.parquet",
            compression="zstd",
            statistics=True,
            maintain_order=False,
            row_group_size=1024**2,
            type_coercion=True,
            predicate_pushdown=True,
            projection_pushdown=True,
        )
    )

    print(f"Converted {file} to data/tablas/{filename}/datos.parquet")
    os.remove(file)
