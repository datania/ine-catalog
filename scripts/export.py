"""Export the INE catalog (base API, table data, series metadata, READMEs) to ./ine.

Every HTTP call is retried. A table that still fails is skipped (its previous
version stays on Hugging Face) and listed in ine/failures.json.
"""

import argparse
import gzip
import json
import random
import re
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
# Fail the job if more than this fraction of tables fail (some are permanently
# unavailable upstream, so a few failures are expected).
MAX_FAILED_FRACTION = 0.1
# Set by main(): tables not started by then are skipped.
DEADLINE = float("inf")

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


# INE dates come either as epoch milliseconds (old API) or as Java Date.toString()
# strings such as "Fri Nov 13 09:00:00 CET 2026" (since Nov 2026).
# Explicit offsets: strptime's %Z doesn't understand CET/CEST.
TZ_OFFSETS = {"UTC": 0, "GMT": 0, "WET": 0, "WEST": 1, "CET": 1, "CEST": 2}


def parse_ine_date(value):
    """Parse an INE date (epoch ms number/string or Java date string) to aware UTC.

    Returns None for missing values; raises ValueError/TypeError for anything else.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise TypeError(f"unsupported INE date type: {value!r}")
    if not isinstance(value, str):
        return datetime.fromtimestamp(value / 1000, UTC)
    text = value.strip()
    if text in ("", "null"):
        return None
    if re.fullmatch(r"-?\d+(\.\d+)?", text):
        return datetime.fromtimestamp(float(text) / 1000, UTC)
    parts = text.split()
    if len(parts) != 6 or parts[4] not in TZ_OFFSETS:
        raise ValueError(f"unsupported INE date: {value!r}")
    tz = parts.pop(4)
    local = datetime.strptime(" ".join(parts), "%a %b %d %H:%M:%S %Y")
    return (local - timedelta(hours=TZ_OFFSETS[tz])).replace(tzinfo=UTC)


def format_ine_date(value):
    """YYYY-MM-DD (UTC, as before the API change), 'Desconocido' if missing."""
    try:
        parsed = parse_ine_date(value)
    except (ValueError, TypeError, OverflowError) as e:
        # Don't lose the table over a README field; show the raw value instead.
        print(f"  WARNING {e}", flush=True)
        return str(value)
    return parsed.strftime("%Y-%m-%d") if parsed else "Desconocido"


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
        last_modified=format_ine_date(table.get("Ultima_Modificacion")),
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
        # Don't count (or upload over the good one) a half-written parquet. DuckDB 2
        # already removes it when COPY fails; this also covers other failure modes.
        (directory / "datos.parquet").unlink(missing_ok=True)
        raise
    finally:
        csv.unlink(missing_ok=True)
        shutil.rmtree(directory / ".tmp", ignore_errors=True)


def export_series(table_id, directory):
    # No get_json: the caller already retries this whole step.
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


def error_text(e):
    return f"{type(e).__name__}: {e}"[:300]


def export_table(table):
    """Export one table. Never raises: problems are returned as {step: error}."""
    table_id = table.get("Id")
    try:
        return table_id, _export_table(table)
    except Exception as e:  # noqa: BLE001 - one bad table must not kill the job
        return table_id, {"table": error_text(e)}


def _export_table(table):
    if time.monotonic() > DEADLINE:
        return {"skipped": "time budget exhausted"}
    directory = TABLES / str(table["Id"])
    directory.mkdir(parents=True, exist_ok=True)
    errors = {}
    try:
        (directory / "metadata.json").write_text(
            json.dumps(table, indent=4), encoding="utf-8"
        )
        (directory / "README.md").write_text(readme(table), encoding="utf-8")
    except Exception as e:  # noqa: BLE001 - still try to export the data
        errors["readme"] = error_text(e)
    for name, fn in (("datos", export_data), ("metadatos_series", export_series)):
        try:
            retry(partial(fn, table["Id"], directory), f"{name} {table['Id']}")
        except Exception as e:  # noqa: BLE001 - record and move on
            errors[name] = error_text(e)
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
    global DEADLINE
    DEADLINE = started + args.max_minutes * 60
    tables = list({t["Id"]: t for t in export_base()}.values())[: args.limit]
    # Only wipe the previous output once the base API has answered.
    shutil.rmtree(TABLES, ignore_errors=True)

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
        json.dumps(failures, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    def exported(name):
        return sum((TABLES / str(t["Id"]) / name).exists() for t in tables)

    data_ok = exported("datos.parquet")
    series_ok = exported("metadatos_series.parquet")
    by_step = dict(Counter(step for errors in failures.values() for step in errors))
    print(
        f"Done in {time.monotonic() - started:.0f}s: {len(tables)} tables, "
        f"datos ok={data_ok}, metadatos_series ok={series_ok}, "
        f"failed={len(failures)} {by_step}"
    )
    # Some tables are permanently unavailable upstream; only fail on widespread
    # breakage. README/whole-table errors are our bugs, so they count separately:
    # the data could all be fine while every README is missing.
    limit = MAX_FAILED_FRACTION * len(tables)
    broken = sum(1 for e in failures.values() if "readme" in e or "table" in e)
    if len(tables) - data_ok > limit or broken > limit:
        sys.exit(
            f"Too many tables failed ({len(tables) - data_ok} without datos, "
            f"{broken} with readme/table errors; see ine/failures.json), "
            "something is broken"
        )


if __name__ == "__main__":
    main()
