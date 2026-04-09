"""
Global configuration for Research2Repo.
"""

import os
from dataclasses import dataclass, field


@dataclass
class R2RConfig:
    """Top-level configuration for the Research2Repo pipeline."""

    # Provider defaults
    default_provider: str = "auto"  # auto, gemini, openai, anthropic, ollama
    default_model: str = ""         # Empty = use provider default

    # Pipeline toggles
    enable_validation: bool = True
    enable_test_generation: bool = True
    enable_equation_extraction: bool = True
    enable_caching: bool = True
    max_fix_iterations: int = 2

    # Download settings
    pdf_timeout: int = 120
    pdf_max_size_mb: int = 100

    # Generation settings
    code_temperature: float = 0.15
    analysis_temperature: float = 0.1
    max_code_tokens: int = 16384
    max_analysis_tokens: int = 8192

    # Vision settings
    max_diagram_pages: int = 30
    diagram_dpi: int = 150
    vision_batch_size: int = 4

    # CodeRAG settings
    enable_code_rag: bool = False
    code_rag_max_repos: int = 3
    code_rag_max_files: int = 20

    # Document segmentation settings
    enable_segmentation: bool = True  # auto-enabled when paper exceeds token limit
    segmentation_max_chars: int = 12000
    segmentation_overlap: int = 500

    # Context management settings
    enable_context_manager: bool = True
    context_max_chars: int = 80000
    context_use_llm_summaries: bool = True

    # Cache settings
    cache_dir: str = ".r2r_cache"

    # Output settings
    verbose: bool = False

    @classmethod
    def from_env(cls) -> "R2RConfig":
        """Create config from environment variables."""
        return cls(
            default_provider=os.environ.get("R2R_PROVIDER", "auto"),
            default_model=os.environ.get("R2R_MODEL", ""),
            enable_validation=os.environ.get("R2R_SKIP_VALIDATION", "").lower() != "true",
            enable_test_generation=os.environ.get("R2R_SKIP_TESTS", "").lower() != "true",
            enable_caching=os.environ.get("R2R_NO_CACHE", "").lower() != "true",
            cache_dir=os.environ.get("R2R_CACHE_DIR", ".r2r_cache"),
            verbose=os.environ.get("R2R_VERBOSE", "").lower() == "true",
        )
