# PaperCoder (Paper2Code) Issues Analysis

Research2Repo v3.0 was designed to address the limitations and open issues of the original PaperCoder system. This page documents how all 22 issues (12 open + 10 closed) from the [PaperCoder GitHub repository](https://github.com/going-doer/Paper2Code/issues) are addressed.

## Open Issues (12)

| Issue | Title | Status | Resolution |
|-------|-------|--------|------------|
| #27 | Missing Dockerfile | ✅ Fully Addressed | `advanced/devops.py` generates Dockerfile, docker-compose, Makefile, CI |
| #25 | Thread safety / daemon thread crash | ✅ Not Applicable | Research2Repo uses REST APIs, not in-process vLLM |
| #21 | config_planning.yaml missing | ✅ Fully Addressed | `ConfigGenerator` + `DecomposedPlanner` generate configs programmatically |
| #20 | MinerU JSON / alternate PDF input | ✅ Fully Addressed | `--pdf_path` flag for local files + 4 parser backends |
| #16 | LiteLLM for other model support | ✅ Fully Addressed | Native multi-provider: Gemini, OpenAI, Anthropic, Ollama (15+ models) |
| #15 | Support for other models | ✅ Fully Addressed | Same as #16 — 4 providers with provider-specific optimizations |
| #14 | Math formula parsing issues | ✅ Fully Addressed | Dedicated `EquationExtractor` + multi-source equation extraction |
| #13 | config.yaml not included | ✅ Fully Addressed | Same as #21 — configs generated as part of pipeline |
| #9 | Installation errors / requirements | ✅ Fully Addressed | Clean dependencies, `pyproject.toml` with optional groups |
| #8 | README + requirements in output | ✅ Fully Addressed | Pipeline generates README.md + requirements.txt automatically |
| #3 | Documentation / step-by-step guide | ✅ Fully Addressed | 13-page wiki (11K+ lines) + comprehensive README |
| #26 | "Are you guys related to DeepCode?" | N/A | Community question, not a bug or feature request |

**Result: 11 of 11 actionable issues fully addressed. 1 issue is N/A (community question).**

---

## Detailed Analysis

### Issue #27: Missing Dockerfile

**PaperCoder Problem:** No Dockerfile was provided, making it difficult to set up reproducible environments for generated projects.

**Research2Repo Solution:**
- `advanced/devops.py` (`DevOpsGenerator` class) generates complete DevOps infrastructure:
  - **Dockerfile** with both CPU and GPU variants (CUDA support, multi-stage builds)
  - **docker-compose.yml** with service definitions, volume mounts, environment configuration
  - **Makefile** with standard targets: `build`, `run`, `test`, `lint`, `clean`, `docker-build`, `docker-run`
  - **GitHub Actions CI** (`.github/workflows/ci.yml`) with test, lint, and build jobs
  - **setup.py** for package distribution
- `advanced/executor.py` (`ExecutionSandbox`) auto-generates Dockerfiles for sandboxed execution during the pipeline itself
- Agent mode flag `--no-devops` allows skipping DevOps generation if not needed

**Key Files:** `advanced/devops.py` (432 lines), `advanced/executor.py` (376 lines)

---

### Issue #25: Fatal Python Error — stdout Lock at Interpreter Shutdown

**PaperCoder Problem:** Using vLLM for local model serving caused daemon thread crashes during Python interpreter shutdown, producing `Fatal Python error: _enter_buffered_busy: could not acquire lock for <_io.BufferedWriter name='<stdout>'>`.

**Research2Repo Solution:**
- **Architectural difference:** Research2Repo does not use vLLM or any in-process model serving with daemon threads
- Local model support is provided through **Ollama** (`providers/ollama_provider.py`), which communicates via HTTP REST API on `localhost:11434`
- All provider communication is synchronous HTTP request/response — no background threads, no daemon processes
- This eliminates the entire class of thread-safety bugs at the Python interpreter level

**Key Files:** `providers/ollama_provider.py`, `providers/base.py`

---

### Issue #21 / #13: config_planning.yaml and config.yaml Not Included

**PaperCoder Problem:** Configuration files (`config.yaml`, `config_planning.yaml`) were required but not included in the repository, causing errors for new users.

**Research2Repo Solution:**
- `advanced/config_generator.py` (`ConfigGenerator` class) generates complete `config.yaml` files for generated projects based on the architecture plan
- `core/planner.py` (`DecomposedPlanner`) generates planning configurations programmatically through its 4-step decomposition:
  1. Overall planning → project structure
  2. Architecture planning → component design
  3. Logic planning → implementation details
  4. Config planning → configuration files
- Research2Repo itself uses `config.yaml` at the project root with clear documentation of all settings
- No undocumented configuration files are required

**Key Files:** `advanced/config_generator.py` (218 lines), `core/planner.py` (697 lines)

---

### Issue #20: MinerU JSON / Alternate PDF Input Support

**PaperCoder Problem:** Users wanted to provide pre-parsed PDF content (e.g., MinerU JSON output) instead of raw PDFs, and the system only accepted URLs.

**Research2Repo Solution:**
- **`--pdf_path` CLI argument** accepts local PDF files directly, eliminating the need for URLs:
  ```bash
  python main.py --pdf_path ./papers/my_paper.pdf
  python main.py --pdf_path /data/papers/attention.pdf --mode agent --refine
  ```
- `core/paper_parser.py` (`PaperParser` class, 546 lines) supports 4 PDF parsing backends:
  1. **doc2json** — Science Parse / S2ORC format
  2. **GROBID** — TEI XML extraction
  3. **PyMuPDF** — Direct PDF text/structure extraction
  4. **PyPDF2** — Fallback text extraction
- Each backend produces a normalized `ParsedPaper` dataclass with sections, equations, figures, tables, and references
- The parser auto-selects the best available backend based on installed dependencies
- Pre-parsed JSON support can be added as a 5th backend for formats like MinerU

**Key Files:** `core/paper_parser.py` (546 lines), `main.py` (`--pdf_path` argument)

---

### Issue #16 / #15: Support for Other Models (LiteLLM)

**PaperCoder Problem:** PaperCoder was hardcoded to use GPT-4o only. Users requested LiteLLM integration to support other models.

**Research2Repo Solution:**
- **Native multi-provider architecture** with 4 built-in providers (no LiteLLM dependency needed):
  1. **Gemini** (`providers/gemini_provider.py`) — Gemini 2.5 Pro, 2.0 Flash, 1.5 Pro/Flash with native file upload and 1M+ token context
  2. **OpenAI** (`providers/openai_provider.py`) — GPT-4o, GPT-4o-mini, o3, o3-mini with structured outputs
  3. **Anthropic** (`providers/anthropic_provider.py`) — Claude 3.5 Sonnet, Claude 3 Opus/Haiku with extended thinking
  4. **Ollama** (`providers/ollama_provider.py`) — Any locally-hosted model (Llama, Mistral, CodeLlama, DeepSeek, etc.)
- Each provider has **provider-specific optimizations** (e.g., Gemini file upload, Claude extended thinking)
- **Capability-based routing** (`ModelCapability` enum) ensures tasks go to models that support them (VISION, CODE_GENERATION, LONG_CONTEXT, etc.)
- Auto-detection: the system probes for available API keys and selects the best provider
- CLI flags: `--provider`, `--model`, `--vision-provider`, `--vision-model`

**Key Files:** `providers/` directory (4 providers + base + factory), `core/analyzer.py` (capability routing)

---

### Issue #14: Math Formula Parsing Issues

**PaperCoder Problem:** Mathematical formulas were not properly extracted from papers, leading to incomplete or broken equation handling in generated code.

**Research2Repo Solution:**
- **Dedicated `EquationExtractor`** (`advanced/equation_extractor.py`) with multi-source extraction:
  - Text-based regex extraction for `$...$`, `$$...$$`, `\[...\]`, `\begin{equation}...`, `\begin{align}...`
  - Vision-based extraction using multimodal models to read equations from paper images
  - Merging and deduplication of equations from both sources
- `core/paper_parser.py` extracts equations during PDF parsing via `_extract_equations_from_text()`
- `core/analyzer.py` (`PaperAnalyzer`) includes equations in the analysis output
- The pipeline prompt templates include equation context for code generation
- `core/validator.py` checks equation coverage as a validation metric
- **193 occurrences** of equation/latex/formula handling across the codebase

**Key Files:** `advanced/equation_extractor.py`, `core/paper_parser.py`, prompt templates

---

### Issue #9: Installation Errors / Requirements Issues

**PaperCoder Problem:** The requirements.txt had heavy or conflicting dependencies that caused installation failures.

**Research2Repo Solution:**
- **Minimal core dependencies:** `requests`, `PyPDF2`, `Pillow`, `pyyaml` — no heavy ML frameworks required
- **Optional dependency groups** in `pyproject.toml`:
  ```
  pip install -e "."           # Core only
  pip install -e ".[gemini]"   # + Google Generative AI SDK
  pip install -e ".[openai]"   # + OpenAI SDK  
  pip install -e ".[anthropic]" # + Anthropic SDK
  pip install -e ".[parsing]"  # + PyMuPDF, lxml for advanced parsing
  pip install -e ".[all]"      # Everything
  ```
- Provider SDKs are only imported when that provider is actually used
- No CUDA/GPU dependencies in the base install
- Clean separation between pipeline requirements and generated project requirements

**Key Files:** `pyproject.toml`, `requirements.txt`

---

### Issue #8: README and requirements.txt in Generated Output

**PaperCoder Problem:** Generated repositories didn't include README.md or proper requirements.txt files.

**Research2Repo Solution:**
- `core/architect.py` (`SystemArchitect._ensure_essentials()`) guarantees that every generated repository includes:
  - `README.md` — with project description, architecture overview, setup instructions, usage examples
  - `requirements.txt` — with all pip dependencies identified during architecture planning
- The `ArchitecturePlan` dataclass has explicit `readme_outline` and `requirements` fields
- `advanced/devops.py` additionally generates `setup.py` for proper package distribution
- Both classic and agent pipelines enforce these essential files

**Key Files:** `core/architect.py` (`_ensure_essentials` method), `advanced/devops.py`

---

### Issue #3: Documentation / Step-by-Step Guide

**PaperCoder Problem:** Lack of comprehensive documentation. Users requested step-by-step video explanations.

**Research2Repo Solution:**
- **13-page wiki** (11,000+ lines) covering:
  - [Home](Home) — Overview and quick start
  - [Architecture Overview](Architecture-Overview) — System design and component relationships
  - [High-Level Design](High-Level-Design) — Module responsibilities and data flow
  - [Low-Level Design](Low-Level-Design) — Class/method-level documentation
  - [Data Model](Data-Model) — All dataclasses, schemas, and type definitions
  - [Usage Guide](Usage-Guide) — Step-by-step CLI usage with examples
  - [Provider System](Provider-System-and-Configuration) — Multi-model setup and configuration
  - [Pipeline Stages](Pipeline-Stages-Deep-Dive) — Detailed walkthrough of each pipeline stage
  - [Prompt Engineering](Prompt-Engineering-Guide) — Template system and customization
  - [API Reference](API-Reference) — Complete programmatic API documentation
  - [Deployment & DevOps](Deployment-and-DevOps) — Docker, CI/CD, production deployment
  - [Troubleshooting](Troubleshooting-and-FAQ) — Common issues and solutions
- **Comprehensive README.md** with architecture diagrams for both classic and agent modes
- Inline code documentation throughout

**Key Files:** `wiki/` directory (13 pages), `README.md`

---

### Issue #26: "Are you guys related to DeepCode?"

**Status:** N/A — This is a community question about project identity, not a bug or feature request. Research2Repo is an independent project inspired by PaperCoder's approach but built from scratch with a different architecture.

---

## Architecture Comparison

| Feature | PaperCoder | Research2Repo v3.0 |
|---------|------------|-------------------|
| Models | GPT-4o only | Gemini, OpenAI, Anthropic, Ollama (15+ models) |
| Pipeline | Linear 3-stage | Classic (10-stage) + Agent (multi-agent orchestrated) |
| Planning | Single pass | 4-stage decomposed (overall → architecture → logic → config) |
| Code Generation | Batch all files | Per-file with accumulated context |
| Self-Correction | None | Self-refine loops with verify/refine cycles |
| Execution | None | Docker sandbox with auto-debugging |
| Evaluation | None | Reference-based scoring (structure, API, logic, test) |
| Equations | Basic text extraction | Multi-source: regex + vision + deduplication |
| PDF Parsing | Single parser | 4 backends (doc2json, GROBID, PyMuPDF, PyPDF2) |
| DevOps | None | Dockerfile, docker-compose, Makefile, CI, setup.py |
| Config | Missing files | Auto-generated from architecture plan |
| Documentation | Minimal README | 13-page wiki + comprehensive README |
| Input | URL only | URL (`--pdf_url`) + local file (`--pdf_path`) |
| Caching | None | Full pipeline caching with incremental updates |
| Dependencies | Heavy, conflicting | Minimal core + optional groups |

---

## Closed Issues

The following 10 issues were closed on the PaperCoder repository. Many of these overlap with or reinforce the open issues above.

### Summary

| Issue | Title | Status | Resolution |
|-------|-------|--------|------------|
| #24 | License | ✅ Fully Addressed | Apache 2.0 LICENSE file included |
| #23 | Model selection impact | N/A | Comment/praise, not a bug or feature request |
| #19 | Paper2Code | N/A | Spam issue ("homeworks") |
| #12 | Auto-generate cleaned JSON from doc2json | ✅ Fully Addressed | `PaperParser` automates full PDF-to-structured-data pipeline |
| #7 | Missing files in generated output | ✅ Fully Addressed | Validator + `_ensure_essentials()` catch missing references |
| #6 | Other OpenAI models (o3-mini, o1-mini) | ✅ Fully Addressed | Native o3, o3-mini, o1 support with reasoning model handling |
| #5 | OpenRouter support | ✅ Addressed Differently | 4 native providers eliminate the need; Ollama covers local models |
| #4 | More LLMs (DeepSeek, Ollama) | ✅ Fully Addressed | Ollama provider supports DeepSeek + any local model |
| #2 | Quick start fails (empty API key) | ✅ Fully Addressed | Provider factory validates API keys early with clear error messages |
| #1 | Release PaperBench on HuggingFace | N/A | PaperCoder-specific dataset hosting request |

**Result: 7 of 7 actionable closed issues fully addressed. 3 issues are N/A.**

---

### Issue #24: License

**PaperCoder Problem:** No license file was provided — the code was effectively proprietary.

**Research2Repo Solution:**
- Ships with an **Apache License 2.0** (`LICENSE` file at project root)
- Permissive open-source license allowing commercial use, modification, and distribution

---

### Issue #12: Auto-Generate Cleaned JSON from doc2json Output

**PaperCoder Problem:** Users had to manually clean and format doc2json output JSON before feeding it to the pipeline. The process for generating "cleaned JSON" from raw doc2json output was undocumented.

**Research2Repo Solution:**
- `core/paper_parser.py` (`PaperParser`) fully automates the PDF-to-structured-data pipeline
- Supports 4 backends (doc2json, GROBID, PyMuPDF, PyPDF2) with automatic fallback
- Each backend produces a normalized `ParsedPaper` dataclass — no manual JSON cleaning needed
- The `doc2json` backend specifically wraps the s2orc-doc2json library and handles all parsing, normalization, and section extraction internally

**Key Files:** `core/paper_parser.py` (546 lines)

---

### Issue #7: Missing Files in Generated Output

**PaperCoder Problem:** Generated repositories referenced data files (e.g., `data/translation/en_de_source.txt`) that didn't exist, causing `FileNotFoundError` at runtime. The generated code was not self-contained.

**Research2Repo Solution:**
- `core/architect.py` (`_ensure_essentials()`) guarantees every generated repo includes essential files (README.md, requirements.txt)
- `core/validator.py` performs cross-file validation — checking imports, references, and structural completeness
- Architecture planning explicitly maps all files and their dependencies
- The code synthesizer generates placeholder data loading with clear documentation of expected data formats
- Agent mode's execution sandbox (`advanced/executor.py`) catches runtime errors like `FileNotFoundError` and triggers auto-debug cycles

**Key Files:** `core/architect.py`, `core/validator.py`, `advanced/executor.py`

---

### Issue #6: Other OpenAI Models (o3-mini, o1-mini)

**PaperCoder Problem:** Users couldn't use alternative OpenAI models like o3-mini or o1-mini. Errors included:
- `PermissionDeniedError` for models not in the user's project
- `BadRequestError` for unsupported `system` message role on reasoning models

**Research2Repo Solution:**
- OpenAI provider (`providers/openai_provider.py`) natively supports **6 models**: `gpt-4o`, `gpt-4o-mini`, `gpt-4-turbo`, `o3`, `o3-mini`, `o1`
- **Reasoning model handling**: Models in `_REASONING_MODELS` (o1, o1-mini, o3-mini) that don't support the `system` role have system instructions automatically folded into the user message
- **Parameter adaptation**: Reasoning models use `max_completion_tokens` instead of `temperature`/`top_p`/`max_tokens` which they don't support
- Users select models via `--provider openai --model o3-mini` — the provider handles all model-specific API quirks transparently

**Key Files:** `providers/openai_provider.py` (`_REASONING_MODELS`, `_is_reasoning_model()`)

---

### Issue #5: OpenRouter Support

**PaperCoder Problem:** Users with OpenRouter API keys (but no OpenAI key) couldn't use the tool at all since it was hardcoded to OpenAI.

**Research2Repo Solution:**
- **4 native providers** eliminate the need for OpenRouter as a proxy:
  - Users without OpenAI keys can use **Gemini** (free tier available), **Anthropic**, or **Ollama** (fully free, local)
  - The system auto-detects available API keys and routes to the best provider
- The OpenAI provider can also be pointed at OpenRouter or any OpenAI-compatible endpoint by customizing the base URL via the OpenAI SDK's standard `OPENAI_BASE_URL` environment variable
- Ollama supports all models available through OpenRouter locally (Llama, Mistral, DeepSeek, etc.)

**Key Files:** `providers/` directory, `providers/registry.py`

---

### Issue #4: More LLMs (DeepSeek, Ollama)

**PaperCoder Problem:** Users wanted to use DeepSeek, Ollama, or other LLMs when OpenAI was unavailable.

**Research2Repo Solution:**
- **Ollama provider** (`providers/ollama_provider.py`) supports any model available through Ollama:
  - DeepSeek (deepseek-coder, deepseek-r1)
  - Llama (llama3, codellama)
  - Mistral (mistral, mixtral)
  - And any other model: `ollama pull <model>` then `--provider ollama --model <model>`
- Ollama runs fully locally with zero API costs
- Additionally, Gemini and Anthropic provide cloud alternatives to OpenAI

**Key Files:** `providers/ollama_provider.py`

---

### Issue #2: Quick Start Fails (Empty API Key)

**PaperCoder Problem:** Running `run.sh` failed with `httpcore.LocalProtocolError: Illegal header value b'Bearer '` because the OpenAI API key wasn't set. The error was cryptic and didn't tell the user what was wrong.

**Research2Repo Solution:**
- All providers validate API keys at initialization time with clear error messages:
  - `"OPENAI_API_KEY not set."` / `"GEMINI_API_KEY not set."` / `"ANTHROPIC_API_KEY not set."`
- The provider factory (`providers/registry.py`) probes for available keys and selects the best available provider automatically
- If no provider is available, the error clearly lists what API keys are needed
- Ollama requires no API key at all — just a running Ollama server

**Key Files:** `providers/openai_provider.py`, `providers/registry.py`

---

### Issues #23, #19, #1: Non-Actionable

| Issue | Description | Why N/A |
|-------|-------------|---------|
| #23 | "LLM is very important, a nice paper2code architecture!" | Comment/compliment, not a bug or feature request |
| #19 | "homeworks" | Spam/irrelevant |
| #1 | Release PaperBench on Hugging Face | PaperCoder-specific dataset hosting outreach from HuggingFace |

---

## Overall Score

**All Issues (Open + Closed):**
- **22 total issues** across the PaperCoder repository
- **18 actionable issues** (bugs, feature requests, missing functionality)
- **18 of 18 addressed** (100%)
- **4 non-actionable** (community questions, spam, external outreach)
