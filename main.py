"""
Research2Repo v3.0: Multi-Model Agentic Pipeline
=================================================
Converts ML research papers into production-ready GitHub repositories.

Supports: Google Gemini, OpenAI GPT-4o/o3, Anthropic Claude, Ollama (local).

Modes:
  classic  — Original 10-stage linear pipeline (v2.0 compatible)
  agent    — Enhanced multi-agent pipeline with decomposed planning,
             per-file analysis, self-refine loops, execution sandbox,
             DevOps generation, and reference-based evaluation

Usage:
  python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf"
  python main.py --pdf_path ./papers/attention.pdf --mode agent --refine
  python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf" --mode agent --refine --execute
  python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf" --mode agent --interactive
"""

import argparse
import os
import sys
import time
from datetime import datetime
from typing import Optional

import requests

from providers import ProviderRegistry, get_provider
from providers.base import ModelCapability, GenerationConfig


# ── PDF Download ──────────────────────────────────────────────────────────

def download_pdf(url: str, save_path: str, timeout: int = 120, max_size_mb: int = 100) -> str:
    """
    Download a research paper PDF with validation.

    Args:
        url: URL of the PDF (arXiv, OpenReview, etc.).
        save_path: Local path to save the file.
        timeout: Request timeout in seconds.
        max_size_mb: Maximum file size to download.

    Returns:
        Path to the saved PDF.
    """
    print(f"  Downloading PDF from {url}...")

    headers = {
        "User-Agent": "Research2Repo/3.0 (Academic Tool; +https://github.com/nellaivijay/Research2Repo)"
    }
    response = requests.get(url, stream=True, timeout=timeout, headers=headers)
    response.raise_for_status()

    # Validate content type
    content_type = response.headers.get("content-type", "")
    if "pdf" not in content_type and not url.endswith(".pdf"):
        print(f"  Warning: Content-Type is '{content_type}', expected PDF.")

    # Download with size check
    total_size = 0
    max_bytes = max_size_mb * 1024 * 1024
    with open(save_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            total_size += len(chunk)
            if total_size > max_bytes:
                raise ValueError(f"PDF exceeds {max_size_mb}MB limit.")
            f.write(chunk)

    size_mb = total_size / (1024 * 1024)
    print(f"  Downloaded: {size_mb:.1f} MB -> {save_path}")
    return save_path


# ── Banner ────────────────────────────────────────────────────────────────

def print_banner(provider_name: str, model_name: str, mode: str) -> None:
    """Print provider and model information."""
    print(f"\n{'='*60}")
    print(f"  Research2Repo v3.0 — {'Agent' if mode == 'agent' else 'Classic'} Pipeline")
    print(f"  Provider: {provider_name}")
    print(f"  Model: {model_name}")
    print(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")


# ── Classic Pipeline (v2.0 compatible) ────────────────────────────────────

def run_classic(
    pdf_url: str,
    output_dir: str,
    provider_name: Optional[str] = None,
    model_name: Optional[str] = None,
    vision_provider_name: Optional[str] = None,
    vision_model_name: Optional[str] = None,
    skip_validation: bool = False,
    skip_tests: bool = False,
    skip_equations: bool = False,
    max_fix_iterations: int = 2,
    use_cache: bool = True,
    cache_dir: Optional[str] = None,
    verbose: bool = False,
    local_pdf_path: Optional[str] = None,
) -> None:
    """
    Run the classic 10-stage Research2Repo pipeline.

    This is the original v2.0 pipeline, kept for backward compatibility.
    """
    from core.analyzer import PaperAnalyzer
    from core.architect import SystemArchitect
    from core.coder import CodeSynthesizer
    from core.validator import CodeValidator
    from advanced.equation_extractor import EquationExtractor
    from advanced.config_generator import ConfigGenerator
    from advanced.test_generator import TestGenerator
    from advanced.cache import PipelineCache

    start_time = time.time()
    os.makedirs(output_dir, exist_ok=True)
    temp_pdf_path = os.path.join(output_dir, "source_paper.pdf")

    # --- Initialize providers ---
    primary_provider = get_provider(
        provider_name=provider_name,
        model_name=model_name,
    )
    actual_provider = provider_name or primary_provider.__class__.__name__.replace("Provider", "").lower()
    actual_model = primary_provider.model_name
    print_banner(actual_provider, actual_model, "classic")

    # Vision provider (may differ from primary)
    vision_provider = None
    if vision_provider_name:
        vision_provider = get_provider(
            provider_name=vision_provider_name,
            model_name=vision_model_name,
        )
    elif primary_provider.supports(ModelCapability.VISION):
        vision_provider = primary_provider

    # Cache
    cache = PipelineCache(cache_dir) if use_cache else None

    try:
        # ============================================================
        # STAGE 1: Obtain PDF
        # ============================================================
        if local_pdf_path:
            print(f"[1/10] Using local PDF: {local_pdf_path}")
            import shutil
            shutil.copy2(local_pdf_path, temp_pdf_path)
        else:
            print(f"[1/10] Download PDF")
            download_pdf(pdf_url, temp_pdf_path)

        # Check cache
        if cache and cache.has_generated_files(temp_pdf_path):
            cached_meta = cache.load_metadata(temp_pdf_path)
            if cached_meta:
                print(f"\n[Cache] Found cached run from {cached_meta.get('timestamp', 'unknown')}")
                print(f"[Cache] Provider: {cached_meta.get('provider', 'unknown')}")
                print("[Cache] To force re-run, use --no-cache\n")

        # ============================================================
        # STAGE 2: Analyze Paper
        # ============================================================
        print(f"\n[2/10] Analyzing paper (long-context + multimodal)...")
        analyzer = PaperAnalyzer(
            provider=primary_provider,
            vision_provider=vision_provider,
        )

        # Upload/extract document
        uploaded_doc = analyzer.upload_document(temp_pdf_path)

        # Extract diagrams via vision
        diagrams = analyzer.extract_diagrams_to_mermaid(temp_pdf_path)

        # Run structured analysis
        if cache and cache.has_analysis(temp_pdf_path):
            analysis = cache.load_analysis(temp_pdf_path)
        else:
            analysis = analyzer.analyze(uploaded_doc, diagrams)
            if cache:
                cache.save_analysis(temp_pdf_path, analysis)

        print(f"  Paper: {analysis.title}")
        print(f"  Authors: {', '.join(analysis.authors[:5])}")
        print(f"  Equations: {len(analysis.equations)} | Hyperparams: {len(analysis.hyperparameters)}")
        print(f"  Diagrams: {len(diagrams)} | Sections: {len(analysis.sections)}")

        # ============================================================
        # STAGE 3: Extract Equations (Advanced)
        # ============================================================
        if not skip_equations:
            print(f"\n[3/10] Running dedicated equation extraction...")
            eq_extractor = EquationExtractor(provider=vision_provider or primary_provider)
            paper_text = analysis.full_text or (uploaded_doc if isinstance(uploaded_doc, str) else "")
            extracted_eqs = eq_extractor.extract(paper_text)

            # Merge with analysis equations
            existing_latex = set(analysis.equations)
            for eq in extracted_eqs:
                if eq.latex and eq.latex not in existing_latex:
                    analysis.equations.append(eq.latex)
                    existing_latex.add(eq.latex)
            print(f"  Total equations after merge: {len(analysis.equations)}")
        else:
            print(f"\n[3/10] Skipping equation extraction (--skip-equations)")

        # ============================================================
        # STAGE 4: Architect Repository
        # ============================================================
        print(f"\n[4/10] Designing repository architecture...")
        if cache and cache.has_architecture(temp_pdf_path):
            plan = cache.load_architecture(temp_pdf_path)
        else:
            architect = SystemArchitect(provider=primary_provider)
            plan = architect.design_system(
                analysis=analysis,
                document=uploaded_doc,
                vision_context=diagrams,
            )
            if cache:
                cache.save_architecture(temp_pdf_path, plan)

        print(f"  Repo: {plan.repo_name}")
        print(f"  Files: {len(plan.files)} | Dependencies: {len(plan.requirements)}")
        if verbose:
            print(f"\n{plan.directory_tree}")

        # ============================================================
        # STAGE 5: Generate Config
        # ============================================================
        print(f"\n[5/10] Generating config.yaml from hyperparameters...")
        config_gen = ConfigGenerator(provider=primary_provider)
        config_content = config_gen.generate(analysis)

        # ============================================================
        # STAGE 6: Synthesize Code
        # ============================================================
        print(f"\n[6/10] Synthesizing code ({len(plan.files)} files)...")
        if cache and cache.has_generated_files(temp_pdf_path):
            generated_files = cache.load_generated_files(temp_pdf_path)
        else:
            coder = CodeSynthesizer(provider=primary_provider)
            generated_files = coder.generate_codebase(
                analysis=analysis,
                plan=plan,
                document=uploaded_doc,
            )
            if cache:
                cache.save_generated_files(temp_pdf_path, generated_files)

        # Inject the generated config
        generated_files["config.yaml"] = config_content

        # Write requirements.txt
        generated_files["requirements.txt"] = "\n".join(plan.requirements) + "\n"

        # ============================================================
        # STAGE 7: Generate Tests
        # ============================================================
        if not skip_tests:
            print(f"\n[7/10] Generating test suite...")
            test_gen = TestGenerator(provider=primary_provider)
            test_files = test_gen.generate_tests(generated_files, analysis, plan)
            generated_files.update(test_files)
            print(f"  Generated {len(test_files)} test files")
        else:
            print(f"\n[7/10] Skipping test generation (--skip-tests)")

        # ============================================================
        # STAGE 8: Validate
        # ============================================================
        if not skip_validation:
            print(f"\n[8/10] Validating code against paper...")
            validator = CodeValidator(provider=primary_provider)
            report = validator.validate(generated_files, analysis, plan)

            print(f"  Score: {report.score}/100")
            print(f"  Equation Coverage: {report.equation_coverage}%")
            print(f"  Hyperparam Coverage: {report.hyperparam_coverage}%")
            print(f"  Critical Issues: {report.critical_count}")
            print(f"  Warnings: {report.warning_count}")

            if verbose and report.issues:
                print("\n  Issues:")
                for issue in report.issues[:10]:
                    print(f"    [{issue.severity}] {issue.file_path}: {issue.description}")

            # ============================================================
            # STAGE 9: Auto-Fix Critical Issues
            # ============================================================
            iteration = 0
            while report.critical_count > 0 and iteration < max_fix_iterations:
                iteration += 1
                print(f"\n[9/10] Auto-fix iteration {iteration}/{max_fix_iterations}...")
                generated_files = validator.fix_issues(generated_files, report, analysis)

                # Re-validate
                report = validator.validate(generated_files, analysis, plan)
                print(f"  Score after fix: {report.score}/100 | Critical: {report.critical_count}")

            if report.passed:
                print(f"\n  Validation PASSED (score: {report.score}/100)")
            else:
                print(f"\n  Validation completed with score {report.score}/100")
                if report.critical_count > 0:
                    print(f"  Warning: {report.critical_count} critical issue(s) remain.")

            if cache:
                cache.save_validation(temp_pdf_path, report)
        else:
            print(f"\n[8/10] Skipping validation (--skip-validation)")
            print(f"[9/10] Skipping auto-fix (validation skipped)")

        # ============================================================
        # STAGE 10: Save Repository
        # ============================================================
        print(f"\n[10/10] Writing repository to {output_dir}...")
        files_written = 0
        for filepath, content in generated_files.items():
            full_path = os.path.join(output_dir, filepath)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w") as f:
                f.write(content)
            files_written += 1
            if verbose:
                print(f"  -> {filepath}")

        # Save pipeline metadata
        elapsed = time.time() - start_time
        metadata = {
            "pdf_url": pdf_url,
            "provider": actual_provider,
            "model": actual_model,
            "timestamp": datetime.now().isoformat(),
            "elapsed_seconds": round(elapsed, 1),
            "files_generated": files_written,
            "paper_title": analysis.title,
            "equations_found": len(analysis.equations),
            "hyperparams_found": len(analysis.hyperparameters),
        }
        if cache:
            cache.save_metadata(temp_pdf_path, metadata)

        # Save metadata to output dir too
        import json
        with open(os.path.join(output_dir, ".r2r_metadata.json"), "w") as f:
            json.dump(metadata, f, indent=2)

        # ============================================================
        # Summary
        # ============================================================
        print(f"\n{'='*60}")
        print(f"  PIPELINE COMPLETE")
        print(f"  Paper: {analysis.title}")
        print(f"  Provider: {actual_provider} / {actual_model}")
        print(f"  Files Generated: {files_written}")
        print(f"  Output: {os.path.abspath(output_dir)}")
        print(f"  Time: {elapsed:.1f}s")
        print(f"{'='*60}\n")

    finally:
        # Cleanup temp PDF (keep it if caching is enabled)
        if not use_cache and os.path.exists(temp_pdf_path):
            os.remove(temp_pdf_path)


# ── Agent Pipeline (v3.0) ────────────────────────────────────────────────

def run_agent(
    pdf_url: str,
    output_dir: str,
    provider_name: Optional[str] = None,
    model_name: Optional[str] = None,
    enable_refine: bool = False,
    enable_execution: bool = False,
    enable_tests: bool = True,
    enable_evaluation: bool = False,
    enable_devops: bool = True,
    enable_code_rag: bool = False,
    enable_segmentation: bool = True,
    enable_context_manager: bool = True,
    interactive: bool = False,
    max_fix_iterations: int = 2,
    max_refine_iterations: int = 2,
    max_debug_iterations: int = 3,
    reference_dir: Optional[str] = None,
    verbose: bool = False,
    local_pdf_path: Optional[str] = None,
) -> None:
    """
    Run the enhanced v3.0 agent pipeline.

    Features beyond classic mode:
      - 4-stage decomposed planning (overall -> architecture -> logic -> config)
      - Per-file analysis with accumulated context
      - Self-refine verify/refine loops at each stage
      - Execution sandbox with auto-debugging
      - DevOps generation (Dockerfile, Makefile, CI)
      - Reference-based evaluation scoring
      - Interactive planning review mode
      - CodeRAG: reference code mining from GitHub (v3.1)
      - Document segmentation for large papers (v3.1)
      - Context manager with cumulative code summaries (v3.1)
    """
    from agents.orchestrator import AgentOrchestrator

    # Initialize provider
    primary_provider = get_provider(
        provider_name=provider_name,
        model_name=model_name,
    )
    actual_provider = provider_name or primary_provider.__class__.__name__.replace("Provider", "").lower()
    actual_model = primary_provider.model_name
    print_banner(actual_provider, actual_model, "agent")

    os.makedirs(output_dir, exist_ok=True)
    temp_pdf_path = os.path.join(output_dir, "source_paper.pdf")

    # Obtain PDF
    if local_pdf_path:
        print(f"[PDF] Using local file: {local_pdf_path}")
        import shutil
        shutil.copy2(local_pdf_path, temp_pdf_path)
    else:
        print(f"[Download] Fetching paper...")
        download_pdf(pdf_url, temp_pdf_path)

    # Build orchestrator config
    config = {
        "enable_refine": enable_refine,
        "enable_execution": enable_execution,
        "enable_tests": enable_tests,
        "enable_evaluation": enable_evaluation,
        "enable_devops": enable_devops,
        "enable_code_rag": enable_code_rag,
        "enable_segmentation": enable_segmentation,
        "enable_context_manager": enable_context_manager,
        "interactive": interactive,
        "max_fix_iterations": max_fix_iterations,
        "max_refine_iterations": max_refine_iterations,
        "max_debug_iterations": max_debug_iterations,
        "reference_dir": reference_dir,
        "verbose": verbose,
    }

    # Run the full agent pipeline
    orchestrator = AgentOrchestrator(provider=primary_provider, config=config)
    result = orchestrator.run(
        pdf_path=temp_pdf_path,
        output_dir=output_dir,
    )

    return result


# ── Provider Listing ──────────────────────────────────────────────────────

def list_providers_cmd() -> None:
    """List available providers and models."""
    print("\nAvailable Providers:")
    print("-" * 60)

    available = ProviderRegistry.detect_available()
    all_providers = ProviderRegistry.list_providers()

    for name in all_providers:
        status = "READY" if name in available else "NOT CONFIGURED"
        print(f"\n  {name.upper()} [{status}]")

        if name in available:
            try:
                provider = ProviderRegistry.create(name)
                for model in provider.available_models():
                    caps = ", ".join(c.name for c in model.capabilities)
                    cost = f"${model.cost_per_1k_input}/{model.cost_per_1k_output} per 1K tok"
                    if model.cost_per_1k_input == 0:
                        cost = "FREE (local)"
                    ctx = f"{model.max_context_tokens:,} ctx"
                    default = " (default)" if model.name == provider.model_name else ""
                    print(f"    - {model.name}{default}")
                    print(f"      {ctx} | {cost}")
                    print(f"      Capabilities: {caps}")
            except Exception as e:
                print(f"    Error listing models: {e}")
        else:
            env_keys = {
                "gemini": "GEMINI_API_KEY",
                "openai": "OPENAI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
                "ollama": "(start Ollama server)",
            }
            print(f"    Set {env_keys.get(name, 'API key')} to enable.")

    print()


# ── CLI Entry Point ───────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Research2Repo v3.0: Convert ML papers to GitHub repositories.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Classic mode (v2.0 compatible)
  python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf"

  # Use a local PDF file instead of a URL
  python main.py --pdf_path ./papers/attention.pdf

  # Agent mode with decomposed planning + self-refine
  python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf" --mode agent --refine

  # Agent mode with execution sandbox + auto-debug
  python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf" --mode agent --execute

  # Interactive planning review (agent mode)
  python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf" --mode agent --interactive

  # Full agent pipeline with all features
  python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf" --mode agent \\
    --refine --execute --evaluate --reference-dir ./reference_impl

  # Enable CodeRAG: mine GitHub for reference implementations
  python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf" --mode agent --code-rag

  # Agent mode with all v3.1 features
  python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf" --mode agent \\
    --code-rag --refine --execute

  # Use specific provider and model
  python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf" --provider openai --model gpt-4o

  # List available providers
  python main.py --list-providers
        """,
    )

    # Core arguments
    parser.add_argument("--pdf_url", type=str, help="URL of the research paper PDF.")
    parser.add_argument("--pdf_path", type=str,
                        help="Path to a local PDF file (alternative to --pdf_url)")
    parser.add_argument("--output_dir", type=str, default="./generated_repo",
                        help="Target directory for generated repo (default: ./generated_repo)")
    parser.add_argument("--mode", type=str, default="classic",
                        choices=["classic", "agent"],
                        help="Pipeline mode: 'classic' (v2.0) or 'agent' (v3.0, default: classic)")

    # Provider selection
    provider_group = parser.add_argument_group("Model Provider")
    provider_group.add_argument("--provider", type=str, default=None,
                                choices=["gemini", "openai", "anthropic", "ollama"],
                                help="LLM provider to use (auto-detected if not set)")
    provider_group.add_argument("--model", type=str, default=None,
                                help="Specific model name (e.g., gpt-4o, gemini-2.5-pro-preview-05-06)")
    provider_group.add_argument("--vision-provider", type=str, default=None,
                                choices=["gemini", "openai", "anthropic", "ollama"],
                                help="Provider for vision/diagram tasks (defaults to primary)")
    provider_group.add_argument("--vision-model", type=str, default=None,
                                help="Model for vision tasks")

    # Classic pipeline control
    classic_group = parser.add_argument_group("Classic Pipeline Options")
    classic_group.add_argument("--skip-validation", action="store_true",
                               help="Skip the validation pass (classic mode)")
    classic_group.add_argument("--skip-tests", action="store_true",
                               help="Skip test generation (classic mode)")
    classic_group.add_argument("--skip-equations", action="store_true",
                               help="Skip dedicated equation extraction (classic mode)")
    classic_group.add_argument("--max-fix-iterations", type=int, default=2,
                               help="Max auto-fix attempts (default: 2)")

    # Agent pipeline control
    agent_group = parser.add_argument_group("Agent Pipeline Options (--mode agent)")
    agent_group.add_argument("--refine", action="store_true",
                             help="Enable self-refine loops at each stage")
    agent_group.add_argument("--execute", action="store_true",
                             help="Enable execution sandbox + auto-debug")
    agent_group.add_argument("--evaluate", action="store_true",
                             help="Enable reference-based evaluation scoring")
    agent_group.add_argument("--no-tests", action="store_true",
                             help="Disable test generation (agent mode)")
    agent_group.add_argument("--no-devops", action="store_true",
                             help="Disable DevOps file generation")
    agent_group.add_argument("--interactive", action="store_true",
                             help="Pause after planning for user review")
    agent_group.add_argument("--reference-dir", type=str, default=None,
                             help="Reference implementation directory for evaluation")
    agent_group.add_argument("--max-refine-iterations", type=int, default=2,
                             help="Max self-refine iterations per stage (default: 2)")
    agent_group.add_argument("--max-debug-iterations", type=int, default=3,
                             help="Max auto-debug iterations (default: 3)")

    # Advanced features (v3.1)
    advanced_group = parser.add_argument_group("Advanced Features (v3.1)")
    advanced_group.add_argument("--code-rag", action="store_true",
                                help="Enable CodeRAG: mine GitHub for reference implementations")
    advanced_group.add_argument("--no-segmentation", action="store_true",
                                help="Disable automatic document segmentation for large papers")
    advanced_group.add_argument("--no-context-manager", action="store_true",
                                help="Disable context manager (use legacy rolling-window context)")

    # Cache control
    cache_group = parser.add_argument_group("Cache")
    cache_group.add_argument("--no-cache", action="store_true",
                             help="Disable pipeline caching")
    cache_group.add_argument("--cache-dir", type=str, default=None,
                             help="Custom cache directory")
    cache_group.add_argument("--clear-cache", action="store_true",
                             help="Clear all cached data and exit")

    # Misc
    parser.add_argument("--list-providers", action="store_true",
                        help="List available providers and models")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose output")

    args = parser.parse_args()

    # Handle utility commands
    if args.list_providers:
        list_providers_cmd()
        sys.exit(0)

    if args.clear_cache:
        from advanced.cache import PipelineCache
        cache = PipelineCache(args.cache_dir)
        cache.clear()
        print("Cache cleared.")
        sys.exit(0)

    # Validate required args — accept either --pdf_url or --pdf_path
    if not args.pdf_url and not args.pdf_path:
        parser.error("--pdf_url or --pdf_path is required (or use --list-providers / --clear-cache)")
    if args.pdf_url and args.pdf_path:
        parser.error("Specify either --pdf_url or --pdf_path, not both")

    # Resolve local PDF: if --pdf_path given, convert to a file:// URL so
    # the downstream download_pdf helper copies the local file.
    pdf_source = args.pdf_url
    local_pdf_path = None
    if args.pdf_path:
        local_pdf_path = os.path.abspath(args.pdf_path)
        if not os.path.isfile(local_pdf_path):
            parser.error(f"Local PDF not found: {local_pdf_path}")
        pdf_source = local_pdf_path  # pass path directly; pipelines handle it

    # Route to the appropriate pipeline
    if args.mode == "agent":
        run_agent(
            pdf_url=pdf_source,
            output_dir=args.output_dir,
            provider_name=args.provider,
            model_name=args.model,
            enable_refine=args.refine,
            enable_execution=args.execute,
            enable_tests=not args.no_tests,
            enable_evaluation=args.evaluate,
            enable_devops=not args.no_devops,
            enable_code_rag=args.code_rag,
            enable_segmentation=not args.no_segmentation,
            enable_context_manager=not args.no_context_manager,
            interactive=args.interactive,
            max_fix_iterations=args.max_fix_iterations,
            max_refine_iterations=args.max_refine_iterations,
            max_debug_iterations=args.max_debug_iterations,
            reference_dir=args.reference_dir,
            verbose=args.verbose,
            local_pdf_path=local_pdf_path,
        )
    else:
        run_classic(
            pdf_url=pdf_source,
            output_dir=args.output_dir,
            provider_name=args.provider,
            model_name=args.model,
            vision_provider_name=args.vision_provider,
            vision_model_name=args.vision_model,
            skip_validation=args.skip_validation,
            skip_tests=args.skip_tests,
            skip_equations=args.skip_equations,
            max_fix_iterations=args.max_fix_iterations,
            use_cache=not args.no_cache,
            cache_dir=args.cache_dir,
            verbose=args.verbose,
            local_pdf_path=local_pdf_path,
        )
