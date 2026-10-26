# INE Data Exporter 📁

Tools to export metadata and datasets from [Spain's National Institute of Statistics](https://www.ine.es) to [HuggingFace](https://huggingface.co/datasets/datania/ine-catalog).

> [!NOTE]  
> Access all the latest datasets on [HuggingFace](https://huggingface.co/datasets/datania/ine-catalog)!

## 🔍 Resources

- [API JSON](https://www.ine.es/dyngs/DAB/index.htm?cid=1099) - INE JSON API
- [INE Tables](https://www.ine.es/dyngs/INEbase/listaoperaciones.htm) - List of statistical operations
- [INE Microdata](https://www.ine.es/dyngs/INEbase/es/operacion.htm?c=Estadistica_C&cid=1254736176918&menu=resultados&idp=1254735976595) - Access to survey microdata
- [INE API](https://www.ine.es/dyngs/DataLab/es/manual.html?cid=1259945948443) - API documentation
- [Tempus3](https://www.ine.es/dyngs/IOE/es/operacion.htm?numinv=30714) - Statistical information dissemination system

You can explore the API documentation in Markdown in the [docs](docs) folder.


## 🚀 Usage

A single weekly GitHub Action ([`export.yml`](.github/workflows/export.yml)) runs `scripts/export.py` and uploads `ine/` with `hf upload`.

```bash
make export             # export everything into ./ine (uv run --locked scripts/export.py)
uv run scripts/export.py --limit 50   # quick smoke test
make upload             # needs HF_TOKEN
```

Every request is retried with backoff. Tables that INE refuses to serve are skipped (the previous version stays on Hugging Face) and listed in `ine/failures.json`.

## 📝 License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
