import logging
from typing import Dict, Any, List

from huggingface_hub import HfApi, HfFolder, ModelFilter, DatasetFilter
from huggingface_hub.inference._mcp.mcp_client import MCPClient

logger = logging.getLogger("aria.hf_connector")

class HFConnector:
    """
    Conector para Hugging Face en Aria.
    Permite a Aria interactuar con el Hugging Face Hub para buscar modelos, datasets
    y potencialmente ejecutar inferencia.
    """

    def __init__(self):
        self.hf_api = HfApi()
        self.mcp_client = MCPClient() # Usaremos el MCPClient de huggingface_hub si es necesario
        self.token = self._get_hf_token()
        if self.token:
            logger.info("Hugging Face token cargado.")
        else:
            logger.warning("No se encontró token de Hugging Face. Algunas operaciones pueden estar limitadas.")

    def _get_hf_token(self) -> str | None:
        """Intenta obtener el token de Hugging Face desde el entorno o HfFolder."""
        # Primero, intenta desde el SecretsManager de Aria
        # from apps.core.config.secrets_manager import secrets_manager
        # token = secrets_manager.get_secret("HF_TOKEN")
        # if token: return token

        # Si no, intenta desde huggingface_hub
        return HfFolder.get_token()

    async def search_models(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Busca modelos en el Hugging Face Hub."""
        try:
            models = self.hf_api.list_models(
                search=query,
                limit=limit,
                token=self.token
            )
            results = []
            for model in models:
                results.append({
                    "id": model.modelId,
                    "author": model.author,
                    "sha": model.sha,
                    "last_modified": model.lastModified.isoformat(),
                    "tags": model.tags,
                    "downloads": model.downloads,
                    "likes": model.likes,
                    "pipeline_tag": model.pipeline_tag,
                    "url": f"https://huggingface.co/{model.modelId}"
                })
            return results
        except Exception as e:
            logger.error(f"Error al buscar modelos en Hugging Face: {e}")
            return []

    async def search_datasets(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Busca datasets en el Hugging Face Hub."""
        try:
            datasets = self.hf_api.list_datasets(
                search=query,
                limit=limit,
                token=self.token
            )
            results = []
            for dataset in datasets:
                results.append({
                    "id": dataset.id,
                    "author": dataset.author,
                    "last_modified": dataset.lastModified.isoformat(),
                    "tags": dataset.tags,
                    "downloads": dataset.downloads,
                    "likes": dataset.likes,
                    "url": f"https://huggingface.co/datasets/{dataset.id}"
                })
            return results
        except Exception as e:
            logger.error(f"Error al buscar datasets en Hugging Face: {e}")
            return []

    async def download_model(self, model_id: str, local_path: str) -> str | None:
        """Descarga un modelo del Hugging Face Hub."""
        try:
            # Usar snapshot_download para descargar el modelo completo
            from huggingface_hub import snapshot_download
            downloaded_path = snapshot_download(repo_id=model_id, local_dir=local_path, token=self.token)
            logger.info(f"Modelo {model_id} descargado en: {downloaded_path}")
            return downloaded_path
        except Exception as e:
            logger.error(f"Error al descargar modelo {model_id}: {e}")
            return None

    async def download_dataset(self, dataset_id: str, local_path: str) -> str | None:
        """Descarga un dataset del Hugging Face Hub."""
        try:
            # Usar load_dataset para descargar el dataset
            from datasets import load_dataset
            # Esto descargará el dataset a un caché local por defecto, o a local_path si se especifica
            dataset = load_dataset(dataset_id, cache_dir=local_path)
            logger.info(f"Dataset {dataset_id} descargado en: {local_path}")
            return local_path # Retorna la ruta donde se cachea o descarga
        except Exception as e:
            logger.error(f"Error al descargar dataset {dataset_id}: {e}")
            return None

# Instancia global del conector HF
hf_connector = HFConnector()
