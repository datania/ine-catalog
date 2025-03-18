#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# [tool.uv]
# exclude-newer = "2025-03-13T00:00:00Z"
# ///

import json
from pathlib import Path

# Load tables data from JSONL file
data_dir = Path("ine")
tables_file = data_dir / "tablas.jsonl"

print(f"Loading tables data from {tables_file}...")
tables = []
with open(tables_file, "r", encoding="utf-8") as f:
    for line in f:
        tables.append(json.loads(line))

print(f"\t✓ Loaded {len(tables)} tables")

tables_dir = data_dir / "tablas"
tables_dir.mkdir(exist_ok=True)

README_TEMPLATE = """# {table_name}

- **ID**: [`{table_id}`](https://www.ine.es/jaxiT3/Tabla.htm?t={table_id})
- **Nombre**: {table_name}
- **Código**: {table_code}
- **Periodicidad**: {periodicity_name} ({periodicity_code})
- **Publicación**: {publication_name}
- **Operación**: {operation_name} - `{operation_code}`
- **Periodo Inicial**: {period_ini_name} {anyo_period_ini}
- **Última Modificación**: {last_modified_date}
"""

for table in tables:
    # Get the ID and name more safely, with error handling
    table_id = table.get("Id") or table.get("id") or "Desconocido"
    table_name = table.get("Nombre") or table.get("nombre") or "Desconocido"

    # Trim the table name to remove any leading/trailing whitespace
    table_name = table_name.strip()

    # Get other metadata with fallbacks
    table_code = table.get("Codigo", "")

    # Handle nested objects safely
    periodicity = table.get("Periodicidad", {})
    periodicity_name = periodicity.get("Nombre", "Desconocido")
    periodicity_code = periodicity.get("Codigo", "")

    publication = table.get("Publicacion", {})
    publication_name = publication.get("Nombre", "Desconocido")

    # Handle nested operation data
    operation = (
        publication.get("Operacion", [{}])[0] if publication.get("Operacion") else {}
    )
    operation_name = operation.get("Nombre", "Desconocido")
    operation_code = operation.get("Codigo", "")

    # Handle period data
    period_ini = table.get("Periodo_ini", {})
    period_ini_name = period_ini.get("Nombre", "Desconocido")
    anyo_period_ini = table.get("Anyo_Periodo_ini", "Desconocido")

    # Format date if available
    last_modified = table.get("Ultima_Modificacion")
    last_modified_date = "Desconocido"
    if last_modified:
        from datetime import datetime

        try:
            # Convert milliseconds to seconds for datetime
            last_modified_date = datetime.fromtimestamp(last_modified / 1000).strftime(
                "%Y-%m-%d"
            )
        except Exception as e:
            print(f"Error formatting date for table {table_id}: {e}")
            pass

    table_dir = tables_dir / str(table_id)
    table_dir.mkdir(exist_ok=True)

    # Get table description
    table_description = table.get("Descripcion", "")

    # Use variables instead of direct dictionary access in the format method
    readme = README_TEMPLATE.format(
        table_id=table_id,
        table_name=table_name,
        table_code=table_code,
        periodicity_name=periodicity_name,
        periodicity_code=periodicity_code,
        publication_name=publication_name,
        operation_name=operation_name,
        operation_code=operation_code,
        period_ini_name=period_ini_name,
        anyo_period_ini=anyo_period_ini,
        last_modified_date=last_modified_date,
        table_description=table_description,
    )

    with open(table_dir / "README.md", "w", encoding="utf-8") as f:
        f.write(readme)

    # Create a JSON file with the table data
    with open(table_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(table, f, indent=4)

    print(f"Generated README for table {table_id}")
