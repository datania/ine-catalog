.DEFAULT_GOAL := export

HF_DATASET_REPO ?= datania/ine-catalog

.PHONY: docs
docs:
	@./scripts/00-export-api-docs.sh

.PHONY: export
export:
	uv run --locked scripts/export.py

.PHONY: upload
upload:
	uv run --locked hf upload --repo-type dataset $(HF_DATASET_REPO) ine .

.PHONY: clean
clean:
	rm -rf ine/tablas ine/*.jsonl ine/failures.json
