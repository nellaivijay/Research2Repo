# Deployment and DevOps

This document covers local development setup, Docker deployment, the DevOps files Research2Repo generates for output repositories, CI/CD pipelines, and operational considerations for running Research2Repo at scale.

---

## Table of Contents

- [1. Local Development Setup](#1-local-development-setup)
- [2. Docker Deployment](#2-docker-deployment)
- [3. Generated Repository DevOps](#3-generated-repository-devops)
- [4. CI/CD Pipeline for Research2Repo](#4-cicd-pipeline-for-research2repo)
- [5. Execution Sandbox Architecture](#5-execution-sandbox-architecture)
- [6. Scaling Considerations](#6-scaling-considerations)
- [7. Monitoring and Observability](#7-monitoring-and-observability)
- [8. Gateway-Managed Deployment](#8-gateway-managed-deployment)

---

## 1. Local Development Setup

### Prerequisites

- **Python 3.10+** (3.10, 3.11, and 3.12 are supported)
- **pip** (latest recommended)
- **Git** for version control
- At least one LLM provider configured (API key or local Ollama)

### Setting Up a Virtual Environment

```bash
# Clone the repository
git clone https://github.com/nellaivijay/Research2Repo.git
cd Research2Repo

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Verify Python version
python --version  # Should be 3.10+
```

### Installing Dependencies

**Minimal install (core only):**

```bash
pip install -r requirements.txt
```

This installs: `requests`, `PyPDF2`, `Pillow`, `pyyaml`, and the Gemini SDK (`google-generativeai`).

**Full install with all providers and extras:**

```bash
pip install -e ".[all]"
```

**Install with development dependencies:**

```bash
pip install -e ".[dev]"
```

This adds: `pytest`, `pytest-cov`, `ruff`.

**Selective provider install:**

```bash
# Gemini only (default, recommended for best cost/quality)
pip install -e ".[gemini]"

# OpenAI
pip install -e ".[openai]"

# Anthropic
pip install -e ".[anthropic]"

# Vision support (PyMuPDF for diagram extraction)
pip install -e ".[vision]"

# Structured paper parsing
pip install -e ".[parsing]"
```

### Configuring Provider API Keys

Set the appropriate environment variable for your chosen provider:

```bash
# Google Gemini (recommended)
export GEMINI_API_KEY="your-api-key-here"

# OpenAI
export OPENAI_API_KEY="sk-..."

# Anthropic Claude
export ANTHROPIC_API_KEY="sk-ant-..."

# Ollama (no key needed -- just start the server)
ollama serve
```

You can also set optional configuration via environment variables:

```bash
export R2R_PROVIDER="gemini"          # Default provider (auto, gemini, openai, anthropic, ollama)
export R2R_MODEL=""                   # Override default model
export R2R_CACHE_DIR=".r2r_cache"     # Cache directory
export R2R_VERBOSE="true"             # Verbose output
export R2R_NO_CACHE="true"            # Disable caching
export R2R_SKIP_VALIDATION="true"     # Skip validation stage
export R2R_SKIP_TESTS="true"          # Skip test generation
```

### Running Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v --tb=short

# Run with coverage
pytest --cov=. --cov-report=term-missing
```

### Linting

```bash
# Run ruff linter
ruff check .

# Auto-fix linting issues
ruff check . --fix
```

### Verifying Your Setup

```bash
# Check which providers are available
python main.py --list-providers

# Run a quick test with a small paper
python main.py --pdf_url "https://arxiv.org/pdf/1706.03762.pdf" --output_dir ./test_output
```

---

## 2. Docker Deployment

### Running Research2Repo in Docker

You can containerize Research2Repo itself for reproducible runs. This is useful for CI pipelines or batch processing.

#### Dockerfile for Research2Repo

```dockerfile
FROM python:3.10-slim

LABEL maintainer="Vijayakumar Ramdoss"
LABEL description="Research2Repo v3.0 - ML Paper to Repository Pipeline"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        git build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application
COPY . .

# API keys are passed as environment variables at runtime
ENV GEMINI_API_KEY=""
ENV OPENAI_API_KEY=""
ENV ANTHROPIC_API_KEY=""

ENTRYPOINT ["python", "main.py"]
```

#### Building and Running

```bash
# Build the image
docker build -t research2repo:latest .

# Run with Gemini API key
docker run --rm \
    -e GEMINI_API_KEY="your-key-here" \
    -v $(pwd)/output:/app/output \
    research2repo:latest \
    --pdf_url "https://arxiv.org/pdf/1706.03762.pdf" \
    --output_dir /app/output

# Run in agent mode with all features
docker run --rm \
    -e GEMINI_API_KEY="your-key-here" \
    -v $(pwd)/output:/app/output \
    research2repo:latest \
    --pdf_url "https://arxiv.org/pdf/1706.03762.pdf" \
    --mode agent \
    --refine \
    --output_dir /app/output
```

#### docker-compose for Research2Repo

```yaml
version: "3.8"

services:
  research2repo:
    build:
      context: .
      dockerfile: Dockerfile
    image: research2repo:latest
    container_name: r2r-pipeline
    environment:
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - OPENAI_API_KEY=${OPENAI_API_KEY:-}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}
    volumes:
      - ./output:/app/output
      - ./papers:/app/papers        # Mount local PDFs
      - ./cache:/app/.r2r_cache     # Persist cache between runs
    entrypoint: ["python", "main.py"]
    command: [
      "--pdf_url", "https://arxiv.org/pdf/1706.03762.pdf",
      "--mode", "agent",
      "--refine",
      "--output_dir", "/app/output"
    ]
```

Run with:

```bash
# Using .env file for API keys
echo "GEMINI_API_KEY=your-key" > .env
docker-compose up
```

---

## 3. Generated Repository DevOps

When Research2Repo generates a repository (especially in agent mode with `--devops`), the `DevOpsGenerator` creates a complete set of infrastructure files. These files allow users to immediately build, train, test, and deploy the generated codebase.

### Dockerfile

The generator produces a multi-stage Dockerfile:

**CPU variant** (always generated):

```dockerfile
# -- CPU image --
FROM python:3.10-slim AS cpu

LABEL maintainer="Research2Repo"
LABEL description="<paper title>"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        git build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "train.py"]
```

**GPU variant** (generated when `torch`, `tensorflow`, `jax`, or `cupy` are in requirements):

```dockerfile
# -- GPU image --
FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04 AS gpu

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 python3-pip git build-essential \
    && ln -sf /usr/bin/python3.10 /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "train.py"]
```

The generator automatically detects if extra system packages are needed (e.g., `libgl1-mesa-glx` for OpenCV).

### docker-compose.yml

Defines training and inference services with appropriate volume mounts:

```yaml
version: "3.8"

services:
  train:
    build:
      context: .
      target: gpu       # or "cpu" if no GPU packages detected
    image: <repo-name>:latest
    container_name: <repo-name>-train
    command: ["python", "train.py"]
    volumes:
      - ./data:/app/data
      - ./checkpoints:/app/checkpoints
      - ./logs:/app/logs
    deploy:             # Only included for GPU repos
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]

  inference:
    build:
      context: .
      target: gpu
    image: <repo-name>:latest
    container_name: <repo-name>-inference
    command: ["python", "inference.py"]
    ports:
      - "8000:8000"
    volumes:
      - ./checkpoints:/app/checkpoints
```

### Makefile

Provides standard developer targets:

```makefile
.PHONY: install train evaluate test lint clean docker-build docker-run help

PYTHON   ?= python
PIP      ?= pip
IMAGE    ?= <repo-name>:latest

help:           ## Show this help message
install:        ## Install Python dependencies
train:          ## Run the training entrypoint
evaluate:       ## Run the inference / evaluation script
test:           ## Run the test suite with pytest
lint:           ## Run linters (ruff + mypy)
clean:          ## Remove build artefacts and caches
docker-build:   ## Build the Docker image
docker-run:     ## Run training inside Docker
```

Usage:

```bash
make install    # pip install -r requirements.txt
make train      # python train.py
make test       # pytest tests/ -v --tb=short
make lint       # ruff check . && mypy --ignore-missing-imports .
make clean      # rm -rf __pycache__ .pytest_cache build dist
make docker-build  # docker build -t <image> .
make docker-run    # docker run --rm -v volumes... <image>
```

### GitHub Actions CI

The generated `.github/workflows/ci.yml` provides a complete CI pipeline:

```yaml
name: CI

on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10"]

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pytest ruff mypy

      - name: Lint with ruff
        run: ruff check . --output-format=github

      - name: Type-check with mypy
        run: mypy --ignore-missing-imports . || true

      - name: Run tests
        run: pytest tests/ -v --tb=short
```

This pipeline runs on every push and pull request to main/master, performing linting, type checking, and testing.

### setup.py

A pip-installable package configuration:

```python
from setuptools import setup, find_packages

setup(
    name="<repo-name>",
    version="0.1.0",
    description="<paper title or plan description>",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="Research2Repo",
    python_requires=">=3.10",
    packages=find_packages(exclude=["tests", "tests.*"]),
    install_requires=_read_requirements(),
    extras_require={
        "dev": ["pytest>=7.0", "ruff>=0.1", "mypy>=1.0"],
    },
    entry_points={
        "console_scripts": ["<repo-name>=train:main"],
    },
)
```

---

## 4. CI/CD Pipeline for Research2Repo

### Suggested GitHub Actions for Research2Repo Itself

If you are contributing to or maintaining Research2Repo, here is a recommended CI workflow:

```yaml
name: Research2Repo CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read

jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12"]

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev,all]"

      - name: Lint with ruff
        run: ruff check . --output-format=github

      - name: Syntax check all Python files
        run: python -m py_compile main.py && find . -name "*.py" -exec python -m py_compile {} +

      - name: Run unit tests
        run: pytest tests/ -v --tb=short --cov=. --cov-report=xml

      - name: Upload coverage
        if: matrix.python-version == '3.10'
        uses: codecov/codecov-action@v4
        with:
          file: ./coverage.xml

  provider-integration:
    runs-on: ubuntu-latest
    needs: lint-and-test

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.10"

      - name: Install dependencies
        run: pip install -e ".[dev,all]"

      - name: Test provider registry (no API keys needed)
        run: |
          python -c "
          from providers.registry import ProviderRegistry
          providers = ProviderRegistry.list_providers()
          assert 'gemini' in providers
          assert 'openai' in providers
          assert 'anthropic' in providers
          assert 'ollama' in providers
          print(f'Registered providers: {providers}')
          "

      - name: Test data classes
        run: |
          python -c "
          from providers.base import ModelCapability, ModelInfo, GenerationConfig, GenerationResult
          from core.analyzer import PaperAnalysis
          from core.architect import ArchitecturePlan, FileSpec
          from core.validator import ValidationReport, ValidationIssue
          from core.refiner import RefinementResult
          from core.planner import PlanningResult, OverallPlan
          from advanced.executor import ExecutionResult
          from advanced.evaluator import EvaluationScore
          print('All data classes import successfully')
          "
```

### Running Syntax Checks on All Python Files

```bash
# Check all Python files compile without syntax errors
find . -name "*.py" -exec python -m py_compile {} +

# Or use ruff for more comprehensive linting
ruff check .
```

### Mock-Based Provider Testing

For testing pipeline stages without real API calls:

```python
# tests/test_pipeline.py
from unittest.mock import MagicMock
from providers.base import BaseProvider, GenerationResult, ModelInfo, ModelCapability

def make_mock_provider(response_text="{}"):
    """Create a mock provider that returns a fixed response."""
    provider = MagicMock(spec=BaseProvider)
    provider.model_name = "mock-model"
    provider.generate.return_value = GenerationResult(
        text=response_text, model="mock-model",
        input_tokens=100, output_tokens=50,
    )
    provider.generate_structured.return_value = {}
    provider.supports.return_value = True
    provider.available_models.return_value = [
        ModelInfo(name="mock-model", provider="mock",
                  max_context_tokens=128000, max_output_tokens=8192,
                  capabilities=[ModelCapability.TEXT_GENERATION]),
    ]
    provider.model_info.return_value = provider.available_models()[0]
    return provider
```

---

## 5. Execution Sandbox Architecture

The `ExecutionSandbox` (in `advanced/executor.py`) provides a controlled environment for running generated code to verify it executes correctly.

### Docker Mode (Default)

When Docker is available, the sandbox operates as follows:

```
1. Check for existing Dockerfile in the generated repo
   |
   +--> If missing: auto-generate a Dockerfile
   |      - Base: python:3.10-slim
   |      - COPY all files into /app
   |      - pip install requirements.txt (if present)
   |      - CMD ["python", "train.py"]
   |
2. Build Docker image
   |   docker build -t r2r-sandbox:<name> .
   |   (10-minute build timeout)
   |
3. Run container
   |   docker run --rm
   |     --memory 8g        # Memory limit
   |     --cpus 4           # CPU limit
   |     [--gpus all]       # GPU flag (if enabled)
   |     <image> python <entrypoint> [args...]
   |   (configurable execution timeout, default 300s)
   |
4. Capture output
   |   stdout, stderr, exit code, duration
   |
5. Classify errors
       Parse stderr for known Python exception patterns
       Return ExecutionResult with error_type classification
```

### Local Mode (Fallback)

When Docker is not available or not desired:

```
1. Snapshot file modification times in repo directory
   |
2. Run entrypoint via subprocess
   |   python <entrypoint> [args...]
   |   cwd = repo_dir
   |   (configurable timeout)
   |
3. Capture output
   |   stdout, stderr, exit code, duration
   |
4. Detect modified files
   |   Compare post-execution mtimes vs pre-execution snapshot
   |
5. Classify errors and return ExecutionResult
```

### GPU Support

GPU support is activated via the `gpu` parameter:

```python
sandbox = ExecutionSandbox(use_docker=True, gpu=True)
```

In Docker mode, this adds `--gpus all` to the `docker run` command, which requires the NVIDIA Container Toolkit (nvidia-docker) to be installed on the host.

### Security Measures

The sandbox applies these security measures:

| Measure | Docker Mode | Local Mode |
|---|---|---|
| Container removed after execution | `--rm` flag | N/A |
| Memory limit | `--memory 8g` | No limit |
| CPU limit | `--cpus 4` | No limit |
| Execution timeout | Configurable (default 300s) | Configurable (default 300s) |
| File isolation | Full container isolation | Runs in repo directory |
| Network access | Default Docker networking | Full host access |

### Integration with AutoDebugger

The `AutoDebugger` uses a local `ExecutionSandbox` (with `use_docker=False` and `timeout=120`) internally for its fix-and-retry loop. The full integration flow is:

```
ExecutionSandbox.execute() -> ExecutionResult (failed)
  |
  v
AutoDebugger.debug(repo_dir, exec_result, files)
  |
  +--> For each iteration (max 5):
  |      1. Analyze error with LLM (extract traceback, identify files)
  |      2. Generate targeted fixes (DebugFix objects)
  |      3. Apply fixes to in-memory file dict
  |      4. Write updated files to disk
  |      5. Re-execute via local sandbox
  |      6. If success: break
  |
  +--> Return (fixed_files, debug_reports)
```

---

## 6. Scaling Considerations

### Pipeline Execution Model

The Research2Repo pipeline is sequential and LLM-bound rather than CPU-bound. Each stage depends on the output of the previous stage:

```
Parse -> Plan -> File Analysis -> Code Gen -> Tests -> Validate -> Execute -> DevOps -> Evaluate -> Save
```

This means:
- **Stages run sequentially** (each stage needs the prior stage's output), **but within stages, parallel execution is used**:
  - **Code generation** uses dependency-depth parallelism (`ThreadPoolExecutor`, up to 4 workers) — files at the same dependency depth are generated concurrently.
  - **File analysis** runs in batches of 4 concurrently.
  - **Stages 3b (segmentation) and 3c (CodeRAG)** run in background threads alongside Stage 3, overlapping their work with code generation.
- **Bottleneck is LLM latency**, not local compute.
- A typical paper takes 2-10 minutes depending on provider, paper length, and enabled features.

### Caching Strategy

The `PipelineCache` avoids re-running expensive stages on repeat runs:

| Stage | Cache Key | Typical Cost Without Cache |
|---|---|---|
| Paper Analysis | SHA-256 of PDF file | 1-3 LLM calls |
| Architecture Plan | Same PDF hash | 1-4 LLM calls |
| Generated Files | Same PDF hash | 10-30+ LLM calls |
| Validation Report | Same PDF hash | 1-2 LLM calls |

To force a fresh run:

```bash
python main.py --pdf_url "..." --no-cache
```

To clear all cached data:

```bash
python main.py --clear-cache
```

### Cost Estimation

Before running a full pipeline, you can estimate costs:

```python
from providers.registry import ProviderRegistry

# Estimate for a typical paper (~50K input tokens, ~30K output tokens per stage)
cost = ProviderRegistry.estimate_cost(
    provider_name="openai",
    model_name="gpt-4o",
    input_tokens=500_000,   # Approximate total across all stages
    output_tokens=200_000,
)
print(f"Estimated cost: ${cost:.2f}")
```

**Approximate costs per paper run (agent mode, all features):**

| Provider | Model | Approximate Cost |
|---|---|---|
| Gemini | gemini-2.5-pro | $0.05-0.50 (free tier available) |
| OpenAI | gpt-4o | $0.50-5.00 |
| Anthropic | claude-3.5-sonnet | $1.00-10.00 |
| Ollama | Any local model | Free (hardware costs only) |

### Batching Multiple Papers

For processing multiple papers, run them sequentially with caching enabled:

```bash
for url in $(cat paper_urls.txt); do
    python main.py --pdf_url "$url" --mode agent --output_dir "./output/$(basename $url .pdf)"
done
```

Or programmatically:

```python
from agents.orchestrator import AgentOrchestrator
from providers import get_provider

provider = get_provider()
orchestrator = AgentOrchestrator(provider=provider)

papers = ["paper1.pdf", "paper2.pdf", "paper3.pdf"]
for pdf_path in papers:
    result = orchestrator.run(
        pdf_path=pdf_path,
        output_dir=f"./output/{pdf_path.replace('.pdf', '')}",
    )
    print(f"{pdf_path}: {result['metadata']['elapsed_seconds']}s")
```

---

## 7. Monitoring and Observability

### Run Metadata

Every pipeline run (in agent mode) produces a `.r2r_metadata.json` file in the output directory:

```json
{
  "pdf_path": "paper.pdf",
  "output_dir": "/absolute/path/to/output",
  "provider": "GeminiProvider",
  "model": "gemini-2.5-pro",
  "timestamp": "2025-01-15T10:30:00.000000",
  "elapsed_seconds": 185.3,
  "files_generated": 18,
  "paper_title": "Attention Is All You Need",
  "timings": {
    "parse": "12.3s",
    "plan": "25.1s",
    "file_analysis": "45.2s",
    "codegen": "62.8s",
    "tests": "15.4s",
    "validation": "18.7s",
    "devops": "3.2s",
    "save": "0.4s"
  },
  "config": {
    "enable_refine": true,
    "enable_execution": false,
    "enable_tests": true,
    "enable_evaluation": false,
    "enable_devops": true,
    "max_debug_iterations": 3,
    "max_refine_iterations": 2,
    "max_fix_iterations": 2
  }
}
```

### Stage Timings

In agent mode, the orchestrator tracks wall-clock time for each stage. These timings are available in:

- The console output during execution (printed after each stage).
- The `result["metadata"]["timings"]` dict in the Python API return value.
- The `.r2r_metadata.json` file in the output directory.

Use timings to identify bottlenecks:

```python
result = orchestrator.run(pdf_path="paper.pdf", output_dir="./output")
for stage, duration in result["metadata"]["timings"].items():
    print(f"  {stage}: {duration}")
```

### Validation Scores as Quality Metrics

The `ValidationReport` provides quantitative quality metrics:

| Metric | Range | Description |
|---|---|---|
| `score` | 0-100 | Overall fidelity score |
| `equation_coverage` | 0-100 | Percentage of paper equations found in code |
| `hyperparam_coverage` | 0-100 | Percentage of hyperparameters that are configurable |
| `critical_count` | 0+ | Number of critical issues |
| `warning_count` | 0+ | Number of warning-level issues |
| `passed` | bool | True if score >= 80 and no critical issues |

Track these across runs to monitor quality:

```python
report = result["validation_report"]
print(f"Score: {report.score}/100")
print(f"Equation coverage: {report.equation_coverage}%")
print(f"Hyperparam coverage: {report.hyperparam_coverage}%")
print(f"Critical issues: {report.critical_count}")
print(f"Passed: {report.passed}")
```

### Token Usage Tracking

Every LLM call returns a `GenerationResult` with token counts:

```python
result = provider.generate(prompt="...", system_prompt="...")
print(f"Input tokens: {result.input_tokens}")
print(f"Output tokens: {result.output_tokens}")
print(f"Model: {result.model}")
```

The `raw_token_count` field on `PaperAnalysis` captures the total tokens used during the analysis stage. For comprehensive token tracking across all stages, inspect the `GenerationResult` objects from each provider call.

### Logging and Verbose Output

Enable verbose output for debugging:

```bash
# CLI
python main.py --pdf_url "..." --verbose

# Environment variable
export R2R_VERBOSE="true"
```

All pipeline stages print progress messages to stdout with prefixed tags:

```
[Analyzer]      Paper analysis messages
[Architect]     Architecture design messages
[Planner]       Decomposed planning messages (Step 1/4, 2/4, ...)
[FileAnalyzer]  Per-file analysis messages
[Coder]         Code generation progress (file N/M)
[Validator]     Validation scores and issue counts
[SelfRefiner]   Verify/refine loop progress
[ExecutionSandbox]  Execution status and error classification
[AutoDebugger]  Debug iteration progress
[DevOps]        Infrastructure file generation
[ReferenceEvaluator]  Evaluation scores
[Cache]         Cache hit/miss messages
[Orchestrator]  Stage headers and auto-fix iterations
```

### Health Checks

Verify the system is correctly configured:

```bash
# List available providers and their status
python main.py --list-providers

# Verify specific provider
python -c "
from providers import get_provider
p = get_provider(provider_name='gemini')
info = p.model_info()
print(f'Provider: {p.__class__.__name__}')
print(f'Model: {info.name}')
print(f'Context: {info.max_context_tokens} tokens')
"
```

---

## 8. Gateway-Managed Deployment

Research2Repo can be deployed as a **managed engine** behind the [Any2Repo-Gateway](https://github.com/nellaivijay/Any2Repo-Gateway), which handles multi-tenant authentication, backend routing, and job lifecycle management across GCP Vertex AI, AWS Bedrock, Azure ML, and on-premise infrastructure.

For full details, see the [Gateway Integration](Gateway-Integration) wiki page.

### How It Works

In gateway mode, the gateway launches the R2R container with environment variables. The `gateway_adapter.py` module detects `JOB_ID` and runs the pipeline automatically:

```
Gateway                          R2R Container
  |                                    |
  |  docker run -e JOB_ID=abc123       |
  |  -e PDF_URL=https://arxiv.org/...  |
  |  -e ENGINE_OPTIONS='{"mode":...}'  |
  |  any2repo/research2repo:latest     |
  |----------------------------------->|
  |                                    |
  |                           main.py starts
  |                           is_gateway_mode() = True
  |                           run_gateway_mode()
  |                              |
  |                              v
  |                           Run pipeline
  |                           (classic or agent)
  |                              |
  |                              v
  |                           Write .any2repo_status.json
  |                           POST to CALLBACK_URL
  |                           exit 0
  |                                    |
  |  Poll job status                   |
  |  GET /api/v1/jobs/abc123           |
  |<-----------------------------------|
```

### Building the Gateway-Compatible Docker Image

```dockerfile
FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        git build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENTRYPOINT ["python", "main.py"]
```

```bash
docker build -t any2repo/research2repo:latest .
docker push any2repo/research2repo:latest
```

### Testing Gateway Mode Locally

You can test gateway mode without a running gateway by setting the environment variables directly:

```bash
JOB_ID=local-test-001 \
  PDF_URL="https://arxiv.org/pdf/1706.03762.pdf" \
  OUTPUT_DIR=/tmp/r2r-test \
  ENGINE_OPTIONS='{"mode":"agent","refine":true}' \
  GEMINI_API_KEY="your-key" \
  python main.py
```

Check the status file after completion:

```bash
cat /tmp/r2r-test/.any2repo_status.json
```

### Gateway Configuration for R2R

To register Research2Repo with the gateway, ensure the engine manifest is available. The built-in manifest is registered automatically. For custom deployments, place a manifest in `ENGINE_MANIFESTS_DIR`:

```json
{
  "engine_id": "research2repo",
  "version": "2.0.0",
  "display_name": "Research2Repo",
  "description": "Convert ML/AI research papers into fully functional repositories",
  "protocol_version": "1.0",
  "capabilities": ["pdf_input", "text_input", "github_output", "local_output"],
  "accepted_inputs": ["pdf_url", "pdf_base64", "paper_text"],
  "container_image": "any2repo/research2repo:latest",
  "supported_backends": ["gcp_vertex", "aws_bedrock", "azure_ml", "on_prem"],
  "cpu_request": "4",
  "memory_request": "16Gi",
  "timeout_seconds": 3600
}
```

### Supported Cloud Backends

| Backend | How R2R Is Launched | Status Tracking |
|---|---|---|
| **GCP Vertex AI** | Custom Job (container) | Vertex AI job status API |
| **AWS Bedrock** | Invoke model | Bedrock response |
| **Azure ML** | ML pipeline job | Azure ML job status |
| **On-Prem (Docker)** | `docker run -d` with env vars | `docker inspect` exit code |
| **On-Prem (HTTP)** | POST to running engine service | GET status endpoint |
