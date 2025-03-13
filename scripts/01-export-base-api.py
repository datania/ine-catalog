#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["httpx"]
# [tool.uv]
# exclude-newer = "2025-03-13T00:00:00Z"
# ///

import json
from pathlib import Path

import httpx  # type: ignore

INE_BASE_URL = "https://servicios.ine.es/wstempus/js/ES"

client = httpx.Client(
    base_url=INE_BASE_URL,
    limits=httpx.Limits(max_keepalive_connections=16),
    transport=httpx.HTTPTransport(retries=5),
)


def ine_request(client: httpx.Client, endpoint):
    """Fetch data from INE API endpoint with automatic pagination."""
    page = 1
    data = []

    while True:
        response = client.get(
            f"/{endpoint}",
            params={"det": 10, "page": page},
            follow_redirects=True,
            timeout=120,
        ).json()

        if not response:
            break

        data.extend(response)

        if len(response) < 500:
            break

        page += 1

    return data


def save_data(data, filename):
    with open(data_dir / filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


data_dir = Path("data")
data_dir.mkdir(exist_ok=True)

# OPERACIONES_DISPONIBLES
print("Fetching OPERACIONES_DISPONIBLES...")
operations = ine_request(client, "OPERACIONES_DISPONIBLES")
save_data(operations, "operaciones.json")
print(f"\t✓ Found {len(operations)} operations")
print(f"\t✓ Operations data saved to {data_dir}/operaciones.json")

# VARIABLES
print("Fetching VARIABLES...")
variables = ine_request(client, "VARIABLES")
save_data(variables, "variables.json")
print(f"\t✓ Found {len(variables)} variables")
print(f"\t✓ Variables data saved to {data_dir}/variables.json")

# PUBLICACIONES
print("Fetching PUBLICACIONES...")
publications = ine_request(client, "PUBLICACIONES")
save_data(publications, "publicaciones.json")
print(f"\t✓ Found {len(publications)} publications")
print(f"\t✓ Publications data saved to {data_dir}/publicaciones.json")

# TABLAS_OPERACION
print("Fetching TABLAS_OPERACION...")
tables = [
    table
    for operation in operations
    for table in ine_request(client, f"TABLAS_OPERACION/{operation['Id']}")
]
save_data(tables, "tablas.json")
print(f"\t✓ Found {len(tables)} tables")
print(f"\t✓ Tables data saved to {data_dir}/tablas.json")
