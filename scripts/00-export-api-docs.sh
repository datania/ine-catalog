#!/usr/bin/env bash
set -euo pipefail

# Create docs folder if it doesn't exist
mkdir -p docs

# Start downloading documentation files
echo "Downloading documentation files..."

download_doc() {
  local url="$1"
  local output_file="$2"

  # --fail: on an HTTP error, abort instead of committing an error page
  curl "$url" \
    --fail --silent --show-error \
    --output "$output_file" \
    -H "X-Base: final" \
    -H "X-Locale: es-ES" \
    -H "X-No-Cache: true" \
    -H "X-Return-Format: markdown" \
    -H "X-Timeout: 120"

  echo "Downloaded $output_file"
}

# Download each documentation file
download_doc "https://r.jina.ai/https://www.ine.es/dyngs/DAB/index.htm?cid=1099" "docs/API JSON.md"
download_doc "https://r.jina.ai/https://www.ine.es/dyngs/DAB/index.htm?cid=1100" "docs/Referencia de la API.md"
download_doc "https://r.jina.ai/https://www.ine.es/dyngs/DAB/index.htm?cid=1102" "docs/Obtener datos de una tabla.md"
download_doc "https://r.jina.ai/https://www.ine.es/dyngs/DAB/index.htm?cid=1103" "docs/Otros casos de uso.md"
download_doc "https://r.jina.ai/https://www.ine.es/dyngs/DAB/index.htm?cid=1104" "docs/Códigos identificadores de tablas y series.md"
download_doc "https://r.jina.ai/https://www.ine.es/dyngs/DAB/index.htm?cid=1105" "docs/Base de datos Tempus3.md"

echo "Documentation files downloaded successfully!"
