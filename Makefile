.DEFAULT_GOAL := all

.PHONY: .uv
.uv:
	@uv -V || echo 'Please install uv: https://docs.astral.sh/uv/getting-started/installation/'

.PHONY: docs
docs:
	@./scripts/export-api-docs.sh
