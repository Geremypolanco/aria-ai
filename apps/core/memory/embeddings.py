"""
embeddings.py — shared HF Inference API embedding helper.

apps/core/cognition/episodic_memory.py and apps/core/memory/semantic_memory.py
each already implement their own near-identical version of this HTTP call.
This file is not a refactor of either of them (touching live, working
modules purely for de-duplication has its own regression risk, for no
functional benefit) — it exists so new code, starting with
apps/core/memory/user_facts.py, has one place to get embeddings from
instead of writing a fourth copy of the same HF request-shape handling.
"""

from __future__ import annotations

import logging

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.embeddings")

HF_EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


async def embed_text(text: str) -> list[float] | None:
    """384-dim embedding for `text`, or None if no HF token is configured or
    the call fails. Callers must treat None as a soft failure and fall back
    to keyword search — embeddings are a quality improvement, never a
    dependency the rest of the system can block on."""
    hf_token = getattr(settings, "HF_TOKEN", None) or getattr(settings, "HF_API_KEY", None)
    if not hf_token or not text:
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"https://api-inference.huggingface.co/pipeline/feature-extraction/{HF_EMBED_MODEL}",
                headers={"Authorization": f"Bearer {hf_token}"},
                json={"inputs": text[:512], "options": {"wait_for_model": True}},
            )
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and data:
                    if isinstance(data[0], float):
                        return data
                    if isinstance(data[0], list):
                        # Sentence-level output (token vectors) — mean-pool to
                        # a single vector.
                        vectors = data[0] if isinstance(data[0][0], float) else data
                        return [sum(col) / len(col) for col in zip(*vectors, strict=False)]
    except Exception as exc:
        logger.debug("[Embeddings] embed_text failed: %s", exc)
    return None
