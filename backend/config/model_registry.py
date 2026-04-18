from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelConfig:
    context_window: int
    max_output: int
    safe_context: int
    temperature: float


MODEL_REGISTRY: dict[str, ModelConfig] = {
    "gemma2:2b": ModelConfig(context_window=2048, max_output=400, safe_context=1500, temperature=0.1),
    "gemma3:latest": ModelConfig(context_window=128000, max_output=2048, safe_context=100000, temperature=0.1),
    "gemma3:12b": ModelConfig(context_window=128000, max_output=2048, safe_context=100000, temperature=0.1),
    "gemma3: 12b": ModelConfig(context_window=128000, max_output=2048, safe_context=100000, temperature=0.1),
}

MODEL_NAME = os.getenv("LLM_MODEL", "gemma2:2b")
DEFAULT_MODEL_CONFIG = ModelConfig(context_window=2048, max_output=400, safe_context=1500, temperature=0.1)


def get_model_config(model_name: str) -> ModelConfig:
    """Return model config or conservative default."""
    return MODEL_REGISTRY.get(model_name, DEFAULT_MODEL_CONFIG)
