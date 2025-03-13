.DEFAULT_GOAL := all

IMAGE_NAME := ine-data-exporter
PORT := 8000

.PHONY: .uv
.uv:
	@uv -V || echo 'Please install uv: https://docs.astral.sh/uv/getting-started/installation/'

.PHONY: docs
docs:
	@./scripts/00-export-api-docs.sh

.PHONY: build
build:
	docker build -t $(IMAGE_NAME) .

.PHONY: ensure-data-dir
ensure-data-dir:
	@mkdir -p $(PWD)/data
	@chmod 777 $(PWD)/data

.PHONY: run
run: build ensure-data-dir
	docker run -it --rm --name $(IMAGE_NAME) -p $(PORT):$(PORT) -v $(PWD)/data:/home/user/data:rw -u $(shell id -u):$(shell id -g) $(IMAGE_NAME)

.PHONY: clean
clean:
	rm -rf $(PWD)/data

.PHONY: export-base-api
export-base-api:
	@uv run scripts/01-export-base-api.py

.PHONY: export-datasets
export-datasets:
	@uv run scripts/02-export-datasets.py

.PHONY: transform-to-parquet
transform-to-parquet:
	@uv run scripts/03-transform-to-parquet.py

.PHONY: export
export: export-base-api export-datasets transform-to-parquet
