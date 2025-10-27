#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# [tool.uv]
# exclude-newer = "2025-03-13T00:00:00Z"
# ///

import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

INE_BASE_URL = "https://servicios.ine.es/wstempus/js/ES"


def fetch_page(endpoint: str, page: int) -> list:
    params = urlencode({"det": 10, "page": page})
    url = f"{INE_BASE_URL}/{endpoint}?{params}"
    request = Request(url, headers={"Accept": "application/json"})

    with urlopen(request, timeout=120) as response:  # noqa: S310
        if response.status != 200:
            raise RuntimeError(f"INE API returned {response.status} for {endpoint}")

        return json.loads(response.read().decode("utf-8"))


def ine_request(endpoint: str) -> list:
    """Fetch data from INE API endpoint with automatic pagination."""
    page = 1
    data = []

    while True:
        response = fetch_page(endpoint, page)

        if not response:
            break

        data.extend(response)

        if len(response) < 500:
            break

        page += 1

    return data


def save_jsonl(data, filename):
    with open(filename, "w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


data_dir = Path("ine")
data_dir.mkdir(exist_ok=True)

# OPERACIONES_DISPONIBLES
print("Fetching OPERACIONES_DISPONIBLES...")
operations = ine_request("OPERACIONES_DISPONIBLES")
save_jsonl(operations, data_dir / "operaciones.jsonl")
print(f"\t✓ Found {len(operations)} operations")
print(f"\t✓ Operations data saved to {data_dir}/operaciones.jsonl")

# VARIABLES
print("Fetching VARIABLES...")
variables = ine_request("VARIABLES")
save_jsonl(variables, data_dir / "variables.jsonl")
print(f"\t✓ Found {len(variables)} variables")
print(f"\t✓ Variables data saved to {data_dir}/variables.jsonl")

# PUBLICACIONES
print("Fetching PUBLICACIONES...")
publications = ine_request("PUBLICACIONES")
save_jsonl(publications, data_dir / "publicaciones.jsonl")
print(f"\t✓ Found {len(publications)} publications")
print(f"\t✓ Publications data saved to {data_dir}/publicaciones.jsonl")

# TABLAS_OPERACION
print("Fetching TABLAS_OPERACION...")
tables = [
    table
    for operation in operations
    for table in ine_request(f"TABLAS_OPERACION/{operation['Id']}")
]
save_jsonl(tables, data_dir / "tablas.jsonl")
print(f"\t✓ Found {len(tables)} tables")
print(f"\t✓ Tables data saved to {data_dir}/tablas.jsonl")
