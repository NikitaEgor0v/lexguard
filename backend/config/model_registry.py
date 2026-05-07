from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelConfig:
    context_window: int
    max_output: int
    safe_context: int
    temperature: float
    # Adaptive limits — scale with model capacity to prevent context overflow.
    # Small models (2B) need strict limits; large models (12B+) can use full context.
    max_segment_chars: int = 600
    max_rag_chars: int = 500
    max_rag_norms: int = 2
    # Whether to use compact (short) prompt format suitable for small models.
    use_compact_prompt: bool = True


MODEL_REGISTRY: dict[str, ModelConfig] = {
    "gemma2:2b": ModelConfig(
        context_window=2048, max_output=512, safe_context=1500,
        temperature=0.1,
        max_segment_chars=600, max_rag_chars=500, max_rag_norms=2,
        use_compact_prompt=True,
    ),
    "gemma3:4b": ModelConfig(
        context_window=4096, max_output=1024, safe_context=3000,
        temperature=0.1,
        max_segment_chars=500, max_rag_chars=800, max_rag_norms=2,
        use_compact_prompt=True,
    ),
    "gemma3:12b": ModelConfig(
        context_window=128000, max_output=2048, safe_context=100000,
        temperature=0.1,
        max_segment_chars=1200, max_rag_chars=2000, max_rag_norms=4,
        use_compact_prompt=False,
    ),
}

MODEL_NAME = os.getenv("LLM_MODEL", "gemma2:2b")
DEFAULT_MODEL_CONFIG = ModelConfig(
    context_window=2048, max_output=512, safe_context=1500,
    temperature=0.1,
    max_segment_chars=600, max_rag_chars=500, max_rag_norms=2,
    use_compact_prompt=True,
)


def get_model_config(model_name: str) -> ModelConfig:
    """Return model config or conservative default."""
    return MODEL_REGISTRY.get(model_name, DEFAULT_MODEL_CONFIG)
