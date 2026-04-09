# Research2Repo v3.0

**Multi-model agentic framework that converts ML research papers into production-ready GitHub repositories.**

Inspired by [PaperCoder](https://arxiv.org/abs/2504.17192) — implements decomposed planning, per-file analysis, self-refine loops, execution sandbox, and multi-agent orchestration on top of Research2Repo's multi-model provider system.

Supports **Google Gemini**, **OpenAI GPT-4o/o3**, **Anthropic Claude**, and **Ollama** (local models). Uses long-context single-pass architecture — no RAG, no chunking, no lost context.

---

## What's New in v3.1 (DeepCode-Inspired)

| Feature | Description |
|---------|-------------|
| **CodeRAG** | Mine GitHub for reference implementations; LLM-scored file-to-file relevance mappings with confidence scores |
| **Document Segmentation** | Content-aware paper chunking for papers exceeding token limits; preserves algorithm blocks and equation chains |
| **Context Manager** | Clean-slate context with cumulative code summaries — prevents context overflow during multi-file generation |

## What's New in v3.0

| Feature | Description |
|---------|-------------|
| **Decomposed Planning** | 4-stage planning: overall plan, architecture design (UML), logic design, config generation |
| **Per-File Analysis** | Deep per-file specification before code generation (+0.23 ablation improvement per PaperCoder) |
| **Self-Refine Loops** | Verify/refine cycles at every pipeline stage to catch errors early |
| **Execution Sandbox** | Docker/local sandbox to actually run generated code |
| **Auto-Debug** | Iterative error analysis + fix when execution fails (supports 19+ Python error types) |
| **DevOps Generation** | Auto-generates Dockerfile, docker-compose, Makefile, GitHub Actions CI, setup.py |
| **Reference Evaluation** | Score generated repo against a reference implementation |
| **Interactive Mode** | Pause after planning to review architecture before code generation |
| **Structured Paper Parsing** | Multi-backend PDF parsing (GROBID, doc2json, PyMuPDF, PyPDF2) |
| **Multi-Agent Architecture** | Pluggable agent system with base class, message passing, orchestrator |

---

## Architecture

### Classic Mode (v2.0 compatible)

```
PDF --> [Analyzer] --> [Equation Extractor] --> [Architect] --> [Coder] --> [Validator] --> Repo
           |                    |                    |              |             |
      Long-Context         Vision/LaTeX         Structured     Rolling       Self-Review
      + Multimodal         Extraction           JSON Output    Context       + Auto-Fix
```

### Agent Mode (v3.0 + v3.1)

```
PDF --> [Paper Parser] --> [Decomposed Planner] --> [Per-File Analyzer] --> [Doc Segmenter]
           |                    |                        |                       |
       Multi-backend     4-stage decomposed        Deep per-file          Auto-segments
       (GROBID/PyMuPDF)  + UML diagrams            specification         large papers
                                |                        |                       |
                         [Self-Refine]             [Self-Refine]          [CodeRAG (opt)]
                                                                              |
                                                                    GitHub ref mining
                                                                              |
                                                                    [Context-Managed Coder]
                                                                              |
                                                                    Clean-slate context
                                                                    + cumulative summaries
                                                                              |
                                                                       [Validator]
                                                                              |
                                                                    [Execution Sandbox]
                                                                              |
                                                                    [Auto-Debugger]
                                                                              |
                                                                    [DevOps Generator]
                                                                              |
                                                                    [Evaluator] --> Repository
```

### Agent Mode Pipeline Stages

| Stage | Module | What It Does |
|-------|--------|-------------|
| 1 | `PaperAnalyzer` | Long-context analysis + vision diagram extraction |
| 2 | `DecomposedPlanner` | 4-stage planning: overall -> architecture (UML) -> logic -> config |
| 3 | `FileAnalyzer` | Per-file deep analysis with accumulated context |
| 3b | `DocumentSegmenter` | Semantic segmentation for papers exceeding token limits (v3.1) |
| 3c | `CodeRAG` | Mine GitHub for reference implementations with confidence-scored mappings (v3.1) |
| 4 | `CodeSynthesizer` + `ContextManager` | File-by-file generation with clean-slate context + cumulative summaries (v3.1) |
| 5 | `TestGenerator` | Auto-generated pytest suite |
| 6 | `CodeValidator` | Self-review + iterative auto-fix loop |
| 7 | `ExecutionSandbox` + `AutoDebugger` | Run code in Docker/local sandbox, auto-debug failures |
| 8 | `DevOpsGenerator` | Generate Dockerfile, Makefile, CI, docker-compose, setup.py |
| 9 | `ReferenceEvaluator` | Score against reference implementation (1-5 scale) |
| 10 | Save | Write all files + metadata to output directory |

### Self-Refine at Every Stage

Each planning/analysis artifact goes through a verify-then-refine loop:

```
Artifact --> [Verify] --> issues found? --> [Refine] --> re-verify --> ... (up to N iterations)
                |
                no issues --> pass through unchanged
```

### Multi-Model Provider System

```
providers/
  base.py              # Abstract interface + capabilities enum
  gemini.py            # Google Gemini (2.5 Pro, 2.0 Flash, 1.5 Pro)
  openai_provider.py   # OpenAI (GPT-4o, GPT-4-turbo, o3, o1)
  anthropic_provider.py # Anthropic (Claude Sonnet 4, Opus 4, 3.5 Sonnet)
  ollama.py            # Local models (DeepSeek, Llama, CodeLlama, Mistral)
  registry.py          # Auto-detection, fallback chains, cost estimation
```

**Key design:** Each provider implements `generate()`, `generate_structured()`, and optionally `upload_file()` + `generate_with_file()`. The registry auto-detects available providers from environment variables and picks the best one for each capability (long-context, vision, code generation, structured output).

---

## Installation

```bash
git clone https://github.com/nellaivijay/Research2Repo.git
cd Research2Repo
pip install -r requirements.txt
```

### Provider Setup (pick one or more)

```bash
# Google Gemini (recommended — 2M token context + vision)
export GEMINI_API_KEY="your_key_here"

# OpenAI GPT-4o
export OPENAI_API_KEY="your_key_here"
pip install openai

# Anthropic Claude
export ANTHROPIC_API_KEY="your_key_here"
pip install anthropic

# Ollama (local, free)
# Install from https://ollama.ai, then:
ollama pull deepseek-coder-v2
```

### Optional: Enhanced Vision (diagram extraction from PDF pages)

```bash
pip install PyMuPDF
```

### Install all providers at once

```bash
pip install -e ".[all]"
```

---

## Usage

### Classic Mode (v2.0 compatible)

```bash
# Auto-detect provider
python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf"

# Use a local PDF file
python main.py --pdf_path ./papers/attention.pdf

# Specific provider and model
python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf" --provider openai --model gpt-4o

# Mix providers
python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf" --provider gemini --vision-provider anthropic

# Fast run (skip validation and tests)
python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf" --skip-validation --skip-tests
```

### Agent Mode (v3.0)

```bash
# Basic agent mode with decomposed planning
python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf" --mode agent

# With self-refine loops (verify/refine each stage)
python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf" --mode agent --refine

# With execution sandbox + auto-debug
python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf" --mode agent --execute

# Interactive planning review
python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf" --mode agent --interactive

# Full pipeline with all features
python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf" --mode agent \
  --refine --execute --evaluate --reference-dir ./reference_impl

# Enable CodeRAG: mine GitHub for reference code (v3.1)
python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf" --mode agent --code-rag

# Full v3.1 pipeline with CodeRAG + all features
python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf" --mode agent \
  --code-rag --refine --execute

# Disable context manager (use legacy rolling-window context)
python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf" --mode agent --no-context-manager

# Evaluate against reference implementation
python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf" --mode agent \
  --evaluate --reference-dir ./path/to/reference/repo
```

### Utility Commands

```bash
python main.py --list-providers     # List available providers and models
python main.py --clear-cache        # Clear all cached data
```

---

## Project Structure

```
Research2Repo/
  main.py                          # CLI entry point: classic + agent modes
  config.py                        # Global configuration

  providers/                       # Multi-model abstraction layer
    __init__.py
    base.py                        # BaseProvider ABC + ModelCapability enum
    gemini.py                      # Google Gemini provider
    openai_provider.py             # OpenAI GPT provider
    anthropic_provider.py          # Anthropic Claude provider
    ollama.py                      # Local Ollama provider
    registry.py                    # Auto-detection + factory

  core/                            # Pipeline stages
    __init__.py
    analyzer.py                    # PaperAnalyzer — PDF ingestion + structured analysis
    architect.py                   # SystemArchitect — repo structure design
    coder.py                       # CodeSynthesizer — file-by-file code generation
    validator.py                   # CodeValidator — self-review + auto-fix
    planner.py                     # DecomposedPlanner — 4-stage planning (v3.0)
    file_analyzer.py               # FileAnalyzer — per-file deep analysis (v3.0)
    refiner.py                     # SelfRefiner — verify/refine loops (v3.0)
    paper_parser.py                # PaperParser — multi-backend PDF parsing (v3.0)

  advanced/                        # Advanced capabilities
    __init__.py
    equation_extractor.py          # Dedicated equation extraction (LaTeX + PyTorch)
    config_generator.py            # YAML config from hyperparameters
    test_generator.py              # Auto pytest suite generation
    cache.py                       # Content-addressed pipeline cache
    executor.py                    # ExecutionSandbox — Docker/local runner (v3.0)
    debugger.py                    # AutoDebugger — iterative error fixing (v3.0)
    evaluator.py                   # ReferenceEvaluator — scoring (v3.0)
    devops.py                      # DevOpsGenerator — Dockerfile, CI, Makefile (v3.0)
    code_rag.py                    # CodeRAG — GitHub reference mining + indexing (v3.1)
    document_segmenter.py          # DocumentSegmenter — semantic paper chunking (v3.1)
    context_manager.py             # ContextManager — clean-slate context + summaries (v3.1)

  agents/                          # Multi-agent architecture (v3.0)
    __init__.py
    base.py                        # BaseAgent ABC + AgentMessage
    orchestrator.py                # AgentOrchestrator — master 10-stage controller

  prompts/                         # Externalized prompt templates
    analyzer.txt                   # Paper analysis prompt
    architect.txt                  # Repo design prompt
    coder.txt                      # Code generation prompt
    validator.txt                  # Validation prompt
    diagram_extractor.txt          # Vision diagram extraction prompt
    equation_extractor.txt         # Equation extraction prompt
    test_generator.txt             # Test generation prompt
    overall_plan.txt               # Overall plan extraction (v3.0)
    architecture_design.txt        # Architecture design with UML (v3.0)
    logic_design.txt               # Logic design + dependency graph (v3.0)
    file_analysis.txt              # Per-file analysis prompt (v3.0)
    self_refine_verify.txt         # Self-refine verification (v3.0)
    self_refine_refine.txt         # Self-refine refinement (v3.0)
    auto_debug.txt                 # Auto-debug prompt (v3.0)
    reference_eval.txt             # Reference evaluation prompt (v3.0)
    devops.txt                     # DevOps generation prompt (v3.0)

  tests/                           # Project tests
    __init__.py

  pyproject.toml                   # Package metadata + optional deps
  requirements.txt                 # Dependencies
  .gitignore
  LICENSE                          # Apache 2.0
```

---

## How It Works

### 1. Zero-RAG Long-Context Analysis

Traditional paper-to-code tools chunk the paper and use RAG, which disconnects hyperparameters (appendix) from equations (Section 3). Research2Repo sends the **entire paper** to the model in a single pass:

- **Gemini:** Uploads PDF via File API (2M+ token context)
- **OpenAI/Anthropic:** Extracts text via PyPDF2, fits within 128K-200K context
- **Ollama:** Extracts text, uses what fits in the local model's context window

### 2. Decomposed Planning (v3.0)

Instead of a single architecture pass, the planner decomposes into 4 stages:

1. **Overall Plan** — Extract core components, methods, training objectives, evaluation protocols
2. **Architecture Design** — File list + Mermaid class/sequence diagrams + module relationships
3. **Logic Design** — Execution order, dependency graph, per-file specifications
4. **Config Generation** — Structured YAML from hyperparameters

Each stage can be independently refined through the self-refine loop.

### 3. Per-File Analysis

Before code generation, each file in the plan gets a deep analysis that includes:
- Classes and functions to implement
- Import dependencies (internal + external)
- Algorithms from the paper to implement
- Input/output specifications
- Test criteria

This accumulated context feeds into the code generation stage, improving output quality (+0.23 in PaperCoder ablation studies).

### 4. Self-Refine Loops

Every artifact (plan, file analysis, generated code) can be verified and refined:

1. **Verify** — Critique the artifact for issues (with severity assessment)
2. **Refine** — If issues found, generate an improved version
3. **Iterate** — Repeat up to N times or until no issues remain

### 5. Execution Sandbox + Auto-Debug

Generated code is actually executed in a sandboxed environment:

- **Docker mode** — Builds a container, runs with resource limits
- **Local mode** — Fallback with subprocess isolation
- **Auto-debug** — When execution fails, analyzes the error, generates targeted fixes, and re-runs (supports 19+ Python error types including ImportError, TypeError, CudaOOMError)

### 6. Rolling Context Code Generation

Files are generated in dependency order (config -> utils -> model components -> training -> tests). Each file receives:
- Full paper analysis (equations, hyperparameters, architecture)
- Previously generated dependency files
- Architecture plan with file descriptions
- Per-file analysis results
- Mermaid diagrams

### 6b. Context Manager (v3.1) — Clean-Slate Generation

The v3.1 ContextManager replaces the rolling-window approach with a "clean-slate" strategy inspired by DeepCode's memory agent:

1. **After each file**, a compact summary is generated (classes, functions, key algorithms)
2. **Before each new file**, the context is rebuilt from scratch:
   - Architecture plan (always)
   - Cumulative code summary (compressed representation of all prior files)
   - Full source of direct dependencies only
   - Reference code from CodeRAG (if enabled)
   - File-specific generation instructions
3. This prevents context overflow when generating 20+ files while maintaining cross-file coherence.

### 6c. CodeRAG (v3.1) — Reference Code Mining

When `--code-rag` is enabled, the pipeline:

1. **Generates search queries** from the paper (title, key components, algorithms)
2. **Searches GitHub** for relevant reference implementations (sorted by stars)
3. **Downloads and indexes** source files from top repositories
4. **Scores relevance** using the LLM: each reference file is mapped to target files with confidence scores:
   - `direct_match` (1.0): implements the same component
   - `partial_match` (0.8): related component
   - `reference` (0.6): useful architectural pattern
   - `utility` (0.4): adaptable helper code
5. During code generation, relevant reference snippets are injected as context.

### 6d. Document Segmentation (v3.1) — Large Paper Support

Papers exceeding token limits are automatically segmented using content-aware strategies:

- **Algorithm preservation**: Algorithm blocks are never split mid-procedure
- **Equation chain grouping**: Related equations stay together
- **Section-aware splitting**: Respects logical section boundaries with overlap
- **4 strategies** selected automatically based on document characteristics:
  - `semantic_research_focused`: Default for standard papers
  - `algorithm_preserve_integrity`: For algorithm-heavy papers
  - `concept_implementation_hybrid`: For papers with both algorithms and heavy math
  - `content_aware_segmentation`: For ML/DL-specific papers

### 7. Self-Review Validation Loop

After generation, a separate validation pass compares every generated file against the paper:
- **Equation fidelity:** Every paper equation has a code counterpart
- **Dimension consistency:** Tensor shapes match the paper
- **Hyperparameter completeness:** All values are configurable, not hardcoded
- **Loss function accuracy:** Matches the paper's formulation

Critical issues are auto-fixed up to N iterations (default: 2).

---

## Supported Models

| Provider | Models | Context | Vision | Cost |
|----------|--------|---------|--------|------|
| **Gemini** | 2.5 Pro, 2.0 Flash, 1.5 Pro | 1M-2M | Yes | $0.0001-$0.01/1K |
| **OpenAI** | GPT-4o, GPT-4-turbo, o3, o1 | 128K-200K | Yes | $0.0025-$0.06/1K |
| **Anthropic** | Claude Sonnet 4, Opus 4, 3.5 Sonnet | 200K | Yes | $0.003-$0.075/1K |
| **Ollama** | DeepSeek, Llama 3.1, CodeLlama, Mistral, LLaVA | 4K-128K | Partial | Free |

---

## CLI Reference

```
python main.py [OPTIONS]

Required (one of):
  --pdf_url URL                URL of the research paper PDF
  --pdf_path PATH              Path to a local PDF file

Mode:
  --mode MODE                  classic (default) | agent

Provider:
  --provider NAME              gemini | openai | anthropic | ollama
  --model NAME                 Specific model name
  --vision-provider NAME       Separate provider for vision tasks
  --vision-model NAME          Specific vision model

Classic Pipeline Options:
  --output_dir DIR             Output directory (default: ./generated_repo)
  --skip-validation            Skip validation pass
  --skip-tests                 Skip test generation
  --skip-equations             Skip equation extraction
  --max-fix-iterations N       Max auto-fix attempts (default: 2)

Agent Pipeline Options (--mode agent):
  --refine                     Enable self-refine loops at each stage
  --execute                    Enable execution sandbox + auto-debug
  --evaluate                   Enable reference-based evaluation
  --no-tests                   Disable test generation
  --no-devops                  Disable DevOps file generation
  --interactive                Pause after planning for user review
  --reference-dir DIR          Reference implementation for evaluation
  --max-refine-iterations N    Max self-refine iterations (default: 2)
  --max-debug-iterations N     Max auto-debug iterations (default: 3)

Advanced Features (v3.1):
  --code-rag                   Enable CodeRAG: mine GitHub for reference implementations
  --no-segmentation            Disable automatic document segmentation
  --no-context-manager         Disable context manager (use legacy rolling-window)

Cache:
  --no-cache                   Disable caching
  --cache-dir DIR              Custom cache directory
  --clear-cache                Clear all cached data

Misc:
  --list-providers             Show available providers and models
  --verbose, -v                Verbose output
```

---

## Environment Variables

| Variable | Description | Required |
|----------|------------|----------|
| `GEMINI_API_KEY` | Google Gemini API key | For Gemini provider |
| `OPENAI_API_KEY` | OpenAI API key | For OpenAI provider |
| `ANTHROPIC_API_KEY` | Anthropic API key | For Anthropic provider |
| `OLLAMA_HOST` | Ollama server URL (default: `http://localhost:11434`) | For Ollama |
| `R2R_PROVIDER` | Default provider override | No |
| `R2R_MODEL` | Default model override | No |
| `R2R_CACHE_DIR` | Custom cache directory | No |

---

## Comparison with PaperCoder & DeepCode

| Feature | Research2Repo v3.1 | PaperCoder | DeepCode |
|---------|-------------------|------------|----------|
| Multi-model support | Gemini, OpenAI, Anthropic, Ollama | GPT-4o only | Claude, GPT, Gemini |
| Decomposed planning | 4-stage (overall/arch/logic/config) | 3-stage (overall/arch/logic) | Requirement analysis |
| Per-file analysis | Yes | Yes | Memory agent context |
| Self-refine loops | All stages | Plan + code | No |
| UML diagrams | Mermaid class + sequence | PlantUML class + sequence | No |
| Vision/diagram extraction | Yes (multimodal) | No | No |
| Equation extraction | Dedicated pipeline | No | No |
| Execution sandbox | Docker + local | No | Execute + debug |
| Auto-debug | Yes (19+ error types) | No | Yes |
| DevOps generation | Dockerfile, CI, Makefile | No | No |
| Reference evaluation | LLM-based scoring | No | No |
| Caching | Content-addressed | No | No |
| Local models | Ollama support | No | No |
| CodeRAG (ref mining) | GitHub search + LLM indexing | No | Codebase indexing |
| Document segmentation | 4 strategies, algorithm-preserving | No | 5 strategies |
| Context management | Clean-slate + cumulative summaries | Rolling window | Concise memory agent |

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
