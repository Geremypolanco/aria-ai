import logging
from typing import Any

try:
    from huggingface_hub import HfApi, HfFolder

    _HF_AVAILABLE = True
except ImportError:
    _HF_AVAILABLE = False
    HfApi = None
    HfFolder = None

logger = logging.getLogger("aria.hf_connector")


class HFConnector:
    """
    Conector para Hugging Face en Aria.
    Permite a Aria interactuar con el Hugging Face Hub para buscar modelos, datasets
    y potencialmente ejecutar inferencia.
    Degrades gracefully when huggingface_hub is not installed.
    """

    def __init__(self):
        self.hf_api = HfApi() if _HF_AVAILABLE else None
        self.token = self._get_hf_token()
        if self.token:
            logger.info("Hugging Face token cargado.")
        elif not _HF_AVAILABLE:
            logger.warning("huggingface_hub no instalado — HFConnector deshabilitado.")
        else:
            logger.warning(
                "No se encontró token de Hugging Face. Algunas operaciones pueden estar limitadas."
            )

    def _get_hf_token(self) -> str | None:
        if not _HF_AVAILABLE:
            return None
        try:
            return HfFolder.get_token()
        except Exception:
            return None

    async def search_models(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        if not _HF_AVAILABLE or not self.hf_api:
            return []
        try:
            models = self.hf_api.list_models(search=query, limit=limit, token=self.token)
            results = []
            for model in models:
                results.append(
                    {
                        "id": model.modelId,
                        "author": model.author,
                        "tags": model.tags,
                        "downloads": model.downloads,
                        "likes": model.likes,
                        "pipeline_tag": model.pipeline_tag,
                        "url": f"https://huggingface.co/{model.modelId}",
                    }
                )
            return results
        except Exception as e:
            logger.error(f"Error al buscar modelos en Hugging Face: {e}")
            return []

    async def search_datasets(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        if not _HF_AVAILABLE or not self.hf_api:
            return []
        try:
            datasets = self.hf_api.list_datasets(search=query, limit=limit, token=self.token)
            results = []
            for dataset in datasets:
                results.append(
                    {
                        "id": dataset.id,
                        "author": dataset.author,
                        "tags": dataset.tags,
                        "downloads": dataset.downloads,
                        "likes": dataset.likes,
                        "url": f"https://huggingface.co/datasets/{dataset.id}",
                    }
                )
            return results
        except Exception as e:
            logger.error(f"Error al buscar datasets en Hugging Face: {e}")
            return []

    async def download_model(self, model_id: str, local_path: str) -> str | None:
        if not _HF_AVAILABLE:
            return None
        try:
            from huggingface_hub import snapshot_download

            downloaded_path = snapshot_download(
                repo_id=model_id, local_dir=local_path, token=self.token
            )
            logger.info(f"Modelo {model_id} descargado en: {downloaded_path}")
            return downloaded_path
        except Exception as e:
            logger.error(f"Error al descargar modelo {model_id}: {e}")
            return None

    async def download_dataset(self, dataset_id: str, local_path: str) -> str | None:
        if not _HF_AVAILABLE:
            return None
        try:
            from datasets import load_dataset

            load_dataset(dataset_id, cache_dir=local_path)
            logger.info(f"Dataset {dataset_id} descargado en: {local_path}")
            return local_path
        except Exception as e:
            logger.error(f"Error al descargar dataset {dataset_id}: {e}")
            return None


hf_connector = HFConnector()
