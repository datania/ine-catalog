"""Export the INE catalog (base API, table data, series metadata, READMEs) to ./ine.

Every HTTP call is retried. A table that still fails is skipped (its previous
version stays on Hugging Face) and listed in ine/failures.json.
"""

import argparse
import gzip
import json
import random
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import duckdb
import polars as pl

API = "https://servicios.ine.es/wstempus/js/ES"
SERIES_URL = "https://servicios.ine.es/wstempus/jsCache/ES/SERIES_TABLA/{id}?det=1"
CSV_URL = "https://www.ine.es/jaxiT3/files/t/en/csv_bdsc/{id}.csv"
OUT = Path("ine")
TABLES = OUT / "tablas"
ATTEMPTS = 5

README = """# {name}

- **ID**: [`{id}`](https://www.ine.es/jaxiT3/Tabla.htm?t={id})
- **Nombre**: {name}
- **Código**: {code}
- **Periodicidad**: {periodicity_name} ({periodicity_code})
- **Publicación**: {publication_name}
- **Operación**: {operation_name} - `{operation_code}`
- **Periodo Inicial**: {period_ini_name} {period_ini_year}
- **Última Modificación**: {last_modified}
- **Licencia**: Creative Commons Reconocimiento 4.0

Este dataset es elaboración propia con datos extraídos del sitio web del INE: www.ine.es
"""


class Unavailable(Exception):
    """INE refuses to serve this resource; retrying won't help."""


def retry(fn, what):
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return fn()
        except Exception as e:
            # 4xx (other than 429) won't get better by retrying
            status = getattr(e, "code", None) or getattr(e, "status_code", None)
            client_error = status is not None and 400 <= status < 500 and status != 429
            if isinstance(e, Unavailable) or client_error or attempt == ATTEMPTS:
                raise
            wait = 3 * 2**attempt + random.random()
            print(
                f"  retry {attempt}/{ATTEMPTS} {what} in {wait:.0f}s: {e}", flush=True
            )
            time.sleep(wait)


def fetch(url):
    """GET url (gzip) and return the decoded body bytes. Raises on non-2xx."""
    req = Request(url, headers={"Accept-Encoding": "gzip"})
    with urlopen(req, timeout=300) as r:
        body = r.read()
        return (
            gzip.decompress(body)
            if r.headers.get("Content-Encoding") == "gzip"
            else body
        )


def get_json(url):
    return retry(lambda: json.loads(fetch(url)), url)


def ine_list(endpoint):
    data, page = [], 1
    while True:
        rows = get_json(f"{API}/{endpoint}?{urlencode({'det': 10, 'page': page})}")
        data.extend(rows or [])
        if not rows or len(rows) < 500:
            return data
        page += 1


def write_jsonl(rows, path):
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)


def export_base():
    OUT.mkdir(exist_ok=True)
    operations = ine_list("OPERACIONES_DISPONIBLES")
    write_jsonl(operations, OUT / "operaciones.jsonl")
    write_jsonl(ine_list("VARIABLES"), OUT / "variables.jsonl")
    write_jsonl(ine_list("PUBLICACIONES"), OUT / "publicaciones.jsonl")
    with ThreadPoolExecutor(8) as pool:
        per_op = pool.map(
            lambda op: ine_list(f"TABLAS_OPERACION/{op['Id']}"), operations
        )
        tables = [t for ts in per_op for t in ts]
    write_jsonl(tables, OUT / "tablas.jsonl")
    print(f"Base API: {len(operations)} operations, {len(tables)} tables", flush=True)
    return tables


def readme(table):
    pub = table.get("Publicacion") or {}
    op = (pub.get("Operacion") or [{}])[0]
    per = table.get("Periodicidad") or {}
    modified = table.get("Ultima_Modificacion")
    return README.format(
        id=table["Id"],
        name=(table.get("Nombre") or "Desconocido").strip(),
        code=table.get("Codigo", ""),
        periodicity_name=per.get("Nombre", "Desconocido"),
        periodicity_code=per.get("Codigo", ""),
        publication_name=pub.get("Nombre", "Desconocido"),
        operation_name=op.get("Nombre", "Desconocido"),
        operation_code=op.get("Codigo", ""),
        period_ini_name=(table.get("Periodo_ini") or {}).get("Nombre", "Desconocido"),
        period_ini_year=table.get("Anyo_Periodo_ini", "Desconocido"),
        last_modified=datetime.fromtimestamp(modified / 1000, UTC).strftime("%Y-%m-%d")
        if modified
        else "Desconocido",
    )


def export_data(table_id, directory):
    # Stream the gzipped CSV to disk first (some are >2GB gzipped). Letting DuckDB read
    # it over HTTP buffers the whole decompressed body in RAM (17GB for table 13884).
    csv = directory / "datos.csv.gz"
    req = Request(CSV_URL.format(id=table_id), headers={"Accept-Encoding": "gzip"})
    try:
        with urlopen(req, timeout=300) as r, open(csv, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
            gzipped = r.headers.get("Content-Encoding") == "gzip"
        with duckdb.connect() as con:
            con.sql("SET threads = 2; SET memory_limit = '1GB'")
            con.sql(f"SET temp_directory = '{directory}/.tmp'")
            con.sql(f"""
                COPY (FROM read_csv('{csv}', delim=';', ignore_errors=true,
                    normalize_names=true, null_padding=true, strict_mode=false,
                    compression='{"gzip" if gzipped else "none"}'))
                TO '{directory / "datos.parquet"}'
                (FORMAT parquet, COMPRESSION zstd, PARQUET_VERSION v2, ROW_GROUP_SIZE 1048576)
            """)
    finally:
        csv.unlink(missing_ok=True)
        shutil.rmtree(directory / ".tmp", ignore_errors=True)


def export_series(table_id, directory):
    data = get_json(SERIES_URL.format(id=table_id))
    if isinstance(data, dict):
        # "Petición en proceso..." is transient; "restricciones de volumen" is permanent
        if "proceso" in str(data.get("status", "")):
            raise RuntimeError(data)
        raise Unavailable(data)
    pl.DataFrame(data).write_parquet(
        directory / "metadatos_series.parquet",
        compression="zstd",
        row_group_size=1048576,
    )


DEADLINE = float("inf")


def export_table(table):
    if time.monotonic() > DEADLINE:
        return table["Id"], {"skipped": "time budget exhausted"}
    directory = TABLES / str(table["Id"])
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "README.md").write_text(readme(table), encoding="utf-8")
    (directory / "metadata.json").write_text(
        json.dumps(table, indent=4), encoding="utf-8"
    )
    errors = {}
    for name, fn in (("datos", export_data), ("metadatos_series", export_series)):
        try:
            retry(partial(fn, table["Id"], directory), f"{name} {table['Id']}")
        except Exception as e:  # noqa: BLE001 - record and move on
            errors[name] = f"{type(e).__name__}: {e}"[:300]
    return table["Id"], errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--limit", type=int, help="Only export the first N tables (testing)"
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--max-minutes",
        type=float,
        default=270,
        help="Stop starting new tables after this",
    )
    args = parser.parse_args()

    started = time.monotonic()
    global DEADLINE
    DEADLINE = started + args.max_minutes * 60
    shutil.rmtree(TABLES, ignore_errors=True)
    tables = list({t["Id"]: t for t in export_base()}.values())[: args.limit]

    failures, done = {}, 0
    with ThreadPoolExecutor(args.workers) as pool:
        for table_id, errors in pool.map(export_table, tables):
            done += 1
            if errors:
                failures[table_id] = errors
                print(f"FAILED {table_id}: {errors}", flush=True)
            if done % 250 == 0 or done == len(tables):
                print(
                    f"[{done}/{len(tables)}] {time.monotonic() - started:.0f}s",
                    flush=True,
                )

    (OUT / "failures.json").write_text(
        json.dumps(failures, indent=2, ensure_ascii=False)
    )
    data_ok = sum(
        1 for t in tables if (TABLES / str(t["Id"]) / "datos.parquet").exists()
    )
    series_ok = sum(
        1
        for t in tables
        if (TABLES / str(t["Id"]) / "metadatos_series.parquet").exists()
    )
    print(
        f"Done in {time.monotonic() - started:.0f}s: {len(tables)} tables, "
        f"datos ok={data_ok}, metadatos_series ok={series_ok}, failed={len(failures)}"
    )
    # Some tables are permanently unavailable upstream; only fail on widespread breakage.
    if data_ok < 0.9 * len(tables):
        sys.exit("Too many tables failed, something is broken")


if __name__ == "__main__":
    main()
