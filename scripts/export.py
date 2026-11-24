"""Export the INE catalog (base API, table data, series metadata, READMEs) to ./ine.

Every HTTP call is retried. A table step that still fails is listed in
ine/failures.json, and tables not started within --max-minutes are skipped; in
both cases the previous version stays on Hugging Face. The job only fails when
too many tables fail, which means something is broken rather than INE being flaky.
"""

import argparse
import gzip
import json
import random
import shutil
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from urllib.error import HTTPError
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
# A normal run has ~2.5% of tables failing upstream (mostly series metadata that
# INE refuses to serve); more than this fraction means something is broken.
MAX_FAILED_FRACTION = 0.1

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
            client_error = (
                isinstance(e, HTTPError) and 400 <= e.code < 500 and e.code != 429
            )
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


# strptime's %Z doesn't understand CET/CEST
TZ_OFFSETS = {"CET": 1, "CEST": 2}


def last_modified(value):
    """README date (YYYY-MM-DD, UTC) from Ultima_Modificacion.

    INE sent epoch milliseconds until Nov 2026 and now sends Java date strings
    like "Fri Nov 13 09:00:00 CET 2026". Anything else is shown as-is.
    """
    if value in (None, "", "null"):
        return "Desconocido"
    try:
        if isinstance(value, str):
            _, month, day, hms, tz, year = value.split()
            local = datetime.strptime(
                f"{year} {month} {day} {hms}", "%Y %b %d %H:%M:%S"
            )
            utc = local - timedelta(hours=TZ_OFFSETS[tz])
        else:
            utc = datetime.fromtimestamp(value / 1000, UTC)
        return utc.strftime("%Y-%m-%d")
    except (ValueError, KeyError, TypeError, OverflowError):
        print(f"  WARNING unexpected Ultima_Modificacion: {value!r}", flush=True)
        return str(value)


def readme(table):
    pub = table.get("Publicacion") or {}
    op = (pub.get("Operacion") or [{}])[0]
    per = table.get("Periodicidad") or {}
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
        last_modified=last_modified(table.get("Ultima_Modificacion")),
    )


def export_data(table_id, directory):
    # Stream the gzipped CSV to disk first (some are >2GB gzipped). Letting DuckDB read
    # it over HTTP buffers the whole decompressed body in RAM (17GB for table 13884).
    csv = directory / "datos.csv.gz"
    req = Request(CSV_URL.format(id=table_id), headers={"Accept-Encoding": "gzip"})
    try:
        with urlopen(req, timeout=300) as r, open(csv, "wb") as f:
            # While INE prepares a CSV it answers 202 with an HTML page; retry later.
            if r.headers.get_content_type() == "text/html":
                raise RuntimeError(f"INE returned HTTP {r.status} HTML, not the CSV")
            shutil.copyfileobj(r, f, 1 << 20)
            gzipped = r.headers.get("Content-Encoding") == "gzip"
        config = {
            "threads": 2,
            "memory_limit": "1GB",
            "temp_directory": str(directory / ".tmp"),
        }
        with duckdb.connect(config=config) as con:
            con.execute(f"""
                COPY (FROM read_csv('{csv}', delim=';', ignore_errors=true,
                    normalize_names=true, null_padding=true, strict_mode=false,
                    compression='{"gzip" if gzipped else "none"}'))
                TO '{directory / "datos.parquet"}'
                (FORMAT parquet, COMPRESSION zstd, PARQUET_VERSION v2, ROW_GROUP_SIZE 1048576)
            """)
    except BaseException:
        # Never upload a half-written parquet over the previous good one.
        (directory / "datos.parquet").unlink(missing_ok=True)
        raise
    finally:
        csv.unlink(missing_ok=True)
        shutil.rmtree(directory / ".tmp", ignore_errors=True)


def export_series(table_id, directory):
    # fetch, not get_json: export_table already retries this whole step
    data = json.loads(fetch(SERIES_URL.format(id=table_id)))
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


def export_table(table, deadline):
    """Export one table. Returns {step: error} ({} if all ok), or None if skipped."""
    if time.monotonic() > deadline:
        return None
    table_id = table["Id"]
    directory = TABLES / str(table_id)
    directory.mkdir(parents=True, exist_ok=True)
    errors = {}
    try:
        (directory / "metadata.json").write_text(
            json.dumps(table, indent=4), encoding="utf-8"
        )
        (directory / "README.md").write_text(readme(table), encoding="utf-8")
    except Exception as e:  # noqa: BLE001 - still export the data
        errors["readme"] = f"{type(e).__name__}: {e}"[:300]
    for step, fn in (("datos", export_data), ("metadatos_series", export_series)):
        try:
            retry(partial(fn, table_id, directory), f"{step} {table_id}")
        except Exception as e:  # noqa: BLE001 - record and move on
            errors[step] = f"{type(e).__name__}: {e}"[:300]
    return errors


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
    deadline = started + args.max_minutes * 60
    tables = list({t["Id"]: t for t in export_base()}.values())[: args.limit]
    shutil.rmtree(TABLES, ignore_errors=True)  # only once the base API answered

    failures, skipped = {}, 0
    with ThreadPoolExecutor(args.workers) as pool:
        results = pool.map(partial(export_table, deadline=deadline), tables)
        for done, (table, errors) in enumerate(zip(tables, results), 1):
            if errors is None:
                skipped += 1
            elif errors:
                failures[table["Id"]] = errors
                print(f"FAILED {table['Id']}: {errors}", flush=True)
            if done % 250 == 0 or done == len(tables):
                print(
                    f"[{done}/{len(tables)}] {time.monotonic() - started:.0f}s",
                    flush=True,
                )

    (OUT / "failures.json").write_text(
        json.dumps(failures, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    attempted = len(tables) - skipped
    by_step = dict(Counter(step for errors in failures.values() for step in errors))
    print(
        f"Done in {time.monotonic() - started:.0f}s: {attempted} tables exported, "
        f"{len(failures)} with errors {by_step}, {skipped} skipped (time budget)"
    )
    if len(failures) > MAX_FAILED_FRACTION * attempted:
        sys.exit(
            f"{len(failures)} of {attempted} tables failed "
            "(see ine/failures.json), something is broken"
        )


if __name__ == "__main__":
    main()
