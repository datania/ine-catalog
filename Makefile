.DEFAULT_GOAL := all

IMAGE_NAME := ine-data-exporter
PORT := 8000

HF_DATASET_REPO ?= datania/ine-catalog

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

.PHONY: export-metadata
export-metadata:
	@uv run scripts/03-export-metadata.py

.PHONY: generate-readmes
generate-readmes:
	@uv run scripts/04-generate-readmes.py

.PHONY: upload
upload:
	HF_HUB_ENABLE_HF_TRANSFER=1 hf upload-large-folder --repo-type=dataset $(HF_DATASET_REPO) ine

.PHONY: export
export: export-base-api export-datasets export-metadata generate-readmes
