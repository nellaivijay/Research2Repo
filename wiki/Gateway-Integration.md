# Gateway Integration & Dual-Mode Architecture

Research2Repo supports two deployment modes: a **standalone CLI** for individual use and a **gateway-managed engine** for platform-scale operation behind [Any2Repo-Gateway](https://github.com/nellaivijay/Any2Repo-Gateway). This page documents the dual-mode architecture, the gateway adapter protocol, environment variable contracts, **cloud-agnostic artifact upload**, **HMAC-signed webhook delivery**, deployment patterns, and worked examples for both modes.

---

## Table of Contents

- [1. Overview](#1-overview)
- [2. Dual-Mode Architecture](#2-dual-mode-architecture)
- [3. gateway_adapter.py Deep Dive](#3-gateway_adapterpy-deep-dive)
- [4. Environment Variable Contract](#4-environment-variable-contract)
- [5. End-to-End Flow: Gateway Mode](#5-end-to-end-flow-gateway-mode)
- [6. Status File Protocol](#6-status-file-protocol)
- [7. Engine Manifest](#7-engine-manifest)
- [8. Supported Backends](#8-supported-backends)
- [9. Worked Examples](#9-worked-examples)
- [10. Docker Deployment for Gateway Mode](#10-docker-deployment-for-gateway-mode)
- [11. Integration with Any2Repo-Gateway](#11-integration-with-any2repo-gateway)

---

## 1. Overview

Research2Repo can be deployed in two distinct modes:

| Mode | Trigger | Typical User | How It Works |
|------|---------|--------------|--------------|
| **Standalone CLI** | `python main.py --pdf_url ...` | Researcher at a terminal | `argparse` parses CLI flags; the user controls every option explicitly. |
| **Gateway-Managed Engine** | `JOB_ID` env var is set | Any2Repo-Gateway platform | The gateway launches R2R inside a container (or subprocess), injecting all parameters as environment variables. R2R reads those env vars, runs the pipeline, writes a status file, and POSTs results back. |

The standalone CLI is documented in [Usage Guide](Usage-Guide). This page focuses on gateway-managed operation and the architectural decisions that make both modes coexist cleanly.

### Why Dual-Mode?

Running R2R as a gateway-managed engine enables:

- **Multi-tenant job queuing** — the gateway handles scheduling, quotas, and isolation.
- **Backend-agnostic deployment** — the same R2R image runs on GCP Vertex AI, AWS Bedrock, Azure ML, or on-prem Docker.
- **Uniform status reporting** — every engine (R2R, Code2Repo, Doc2Repo, etc.) writes the same `.any2repo_status.json` format so the gateway can track all jobs identically.
- **Callback-driven workflows** — the gateway does not need to poll; R2R POSTs results when finished.

---

## 2. Dual-Mode Architecture

### Design Philosophy

The gateway integration follows a **zero-intrusion** principle:

1. **No modifications to the existing CLI interface.** The `run_classic()` and `run_agent()` functions in `main.py` are identical in both modes. They accept the same parameters and produce the same output regardless of who called them.
2. **Single integration point.** All gateway-specific logic lives in one file: `gateway_adapter.py`. No other module imports from it or knows about gateway concepts.
3. **Early mode detection.** In `main.py`, gateway mode is detected *before* `argparse` runs. If `is_gateway_mode()` returns `True`, the adapter takes over immediately and `argparse` is never invoked.
4. **Clean exit semantics.** `run_gateway_mode()` always calls `sys.exit(0)` on success or `sys.exit(1)` on failure, providing a clear exit code to the container runtime.

### Mode Selection Flow

```
main.py
  |
  +-- is_gateway_mode()?
  |     |
  |     Yes --> run_gateway_mode()
  |     |       |
  |     |       +-- Read env vars (JOB_ID, PDF_URL, ...)
  |     |       +-- Parse ENGINE_OPTIONS JSON
  |     |       +-- Resolve input (PDF URL, base64, or raw text)
  |     |       +-- Call run_classic() or run_agent()
  |     |       +-- Count generated files
  |     |       +-- Upload artifact to cloud storage (GCS/S3/Azure/local)
  |     |       +-- Write .any2repo_status.json (incl. artifact_url)
  |     |       +-- POST webhook with HMAC signature (or legacy callback)
  |     |       +-- sys.exit(0 or 1)
  |     |
  |     No --> Standard CLI
  |            |
  |            +-- argparse handles --pdf_url, --mode, etc.
  |            +-- Validate required arguments
  |            +-- Call run_classic() or run_agent()
  |            +-- Print summary, exit normally
```

### Layer Placement

The gateway adapter sits between the Presentation layer (CLI) and the Orchestration layer (pipeline functions). It replaces the CLI's argument parsing with environment variable reading, but delegates all actual work to the same orchestration functions:

```
+================================================================+
|  Layer 0: GATEWAY ADAPTER (gateway_adapter.py)                 |
|  is_gateway_mode(), run_gateway_mode()                         |
|  write_status_file(), post_callback()                          |
+================================================================+
                           |
              (replaces)   |   (or)
                           v
+================================================================+
|  Layer 1: PRESENTATION (main.py CLI)                           |
|  argparse, banner, --list-providers                            |
+================================================================+
                           |
                           v
+================================================================+
|  Layer 2: ORCHESTRATION                                        |
|  run_classic(), run_agent(), AgentOrchestrator                 |
+================================================================+
                           |
                           v
                   (Core, Advanced, Provider layers — unchanged)
```

The key insight: Layer 0 and Layer 1 are **mutually exclusive**. When `JOB_ID` is set, Layer 0 runs and Layer 1 is skipped entirely. When `JOB_ID` is absent, Layer 0 is a no-op and Layer 1 runs as usual.

---

## 3. gateway_adapter.py Deep Dive

The gateway adapter module (`gateway_adapter.py` at the repository root) implements public functions and a cloud-agnostic artifact storage abstraction. It has zero dependencies on `core/`, `advanced/`, or `agents/` — it only imports from `main.py` at runtime when it needs to call `run_classic()` or `run_agent()`.

### 3.1 `is_gateway_mode() -> bool`

```python
def is_gateway_mode() -> bool:
    return bool(os.environ.get("JOB_ID"))
```

Returns `True` if the `JOB_ID` environment variable is set and non-empty. This is the sole signal that the engine was launched by the gateway. The check is intentionally minimal — a single env var lookup — to keep detection fast and deterministic.

Called in `main.py` at line 522, before any argument parsing:

```python
if __name__ == "__main__":
    from gateway_adapter import is_gateway_mode
    if is_gateway_mode():
        from gateway_adapter import run_gateway_mode
        run_gateway_mode()  # does not return (calls sys.exit)
```

### 3.2 `write_status_file(output_dir, job_id, status, ...) -> str`

Writes `.any2repo_status.json` to the output directory per the [Engine Protocol spec](https://github.com/nellaivijay/Any2Repo-Gateway/blob/main/docs/engine_protocol.md). This file is the canonical record of job completion.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `output_dir` | `str` | Directory where generated files were written |
| `job_id` | `str` | Unique job identifier from `JOB_ID` env var |
| `status` | `str` | `"completed"` or `"failed"` |
| `output_url` | `str` | URL to the generated output (optional) |
| `error` | `str` | Error message (required when `status="failed"`) |
| `files_generated` | `int` | Number of files produced |
| `elapsed_seconds` | `float` | Wall-clock execution time |
| `metadata` | `dict` | Additional engine-specific metadata |

**Returns:** Absolute path to the status file.

The function creates the output directory if it does not exist (`os.makedirs(output_dir, exist_ok=True)`) before writing, so it is safe to call even when the pipeline failed before generating any files.

### 3.3 `post_callback(callback_url, payload) -> bool`

Best-effort POST of job results to the gateway callback URL.

```python
def post_callback(callback_url: str, payload: dict) -> bool:
    if not callback_url:
        return False
    try:
        resp = requests.post(callback_url, json=payload, timeout=30)
        resp.raise_for_status()
        return True
    except Exception:
        return False  # never raises
```

Key design decisions:

- **Never raises.** The callback is best-effort. If the gateway is unreachable, the status file on disk is still the authoritative record. The gateway can poll for it or rely on container exit code.
- **30-second timeout.** Prevents the engine from hanging indefinitely if the gateway is slow.
- **Lazy import of `requests`.** The `requests` library is imported inside the function body to avoid adding a hard dependency for CLI-only users.

### 3.4 Cloud-Agnostic Artifact Storage

The adapter includes a pluggable artifact storage system with four backends:

| Class | Backend | URI Format | Pre-signed URL |
|-------|---------|------------|----------------|
| `GCSArtifactStore` | Google Cloud Storage | `gs://bucket/key` | GCS v4 signed URL |
| `S3ArtifactStore` | Amazon S3 | `s3://bucket/key` | S3 pre-signed URL |
| `AzureBlobArtifactStore` | Azure Blob Storage | `https://account.blob.../container/key` | Azure SAS URL |
| `LocalArtifactStore` | Local filesystem | `file:///path` | `file://` path |

All backends implement `BaseArtifactStore` with two methods:
- `upload(local_path, remote_key) -> str` — upload and return URI
- `presigned_url(remote_key, ttl_seconds) -> str` — generate download URL

The `create_artifact_store()` factory selects the backend from the `ARTIFACT_BACKEND` env var, with auto-detection from `GCS_ARTIFACT_BUCKET`, `AWS_REGION`, `AZURE_STORAGE_ACCOUNT_URL`, or `LOCAL_ARTIFACT_DIR`.

### 3.5 `upload_artifact(output_dir, job_id) -> tuple[str, int]`

Orchestrates the artifact upload flow:

1. Creates the artifact store via `create_artifact_store()`
2. Zips `OUTPUT_DIR` into `{OUTPUT_DIR}_artifact.zip`
3. Uploads to `jobs/{JOB_ID}/output.zip`
4. Generates a pre-signed download URL (TTL from `PRESIGNED_URL_TTL`)
5. Returns `(presigned_url, size_bytes)`

Falls back gracefully — returns `("", 0)` if no store is configured or upload fails.

### 3.6 `post_webhook(webhook_url, payload, secret) -> bool`

HMAC-signed webhook POST to the gateway. Preferred over the legacy `post_callback()`.

```python
def post_webhook(webhook_url: str, payload: dict, secret: str = "") -> bool:
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if secret:
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        headers["X-Webhook-Signature"] = sig
    resp = requests.post(webhook_url, data=body, headers=headers, timeout=30)
    resp.raise_for_status()
    return True
```

Key differences from `post_callback()`:
- **HMAC signature** — when `WEBHOOK_SECRET` is set, the payload is signed with SHA-256
- **Gateway webhook endpoint** — POSTs to `/api/v1/webhooks/engine-complete`
- **Same best-effort semantics** — never raises, returns `False` on failure

### 3.7 `run_gateway_mode() -> None`

The main orchestration function for gateway mode. It:

1. **Reads environment variables** — `JOB_ID`, `TENANT_ID`, `PDF_URL`, `PDF_BASE64`, `PAPER_TEXT`, `OUTPUT_DIR`, `ENGINE_OPTIONS`, `CALLBACK_URL`, `R2R_PROVIDER`, `R2R_MODEL`.
2. **Parses `ENGINE_OPTIONS`** — a JSON string containing pipeline options like `{"mode": "agent", "refine": true}`. Falls back to an empty dict on parse failure.
3. **Resolves paper input** — supports three input methods:
   - `PDF_URL`: direct URL, passed to `run_classic()`/`run_agent()` as `pdf_url`.
   - `PDF_BASE64`: base64-decoded to a file at `{OUTPUT_DIR}/input_paper.pdf`.
   - `PAPER_TEXT`: raw text (future support for text-only pipelines).
4. **Calls the appropriate pipeline** — `run_agent()` if `options["mode"] == "agent"`, otherwise `run_classic()`.
5. **Counts generated files** — walks `OUTPUT_DIR` with `Path.rglob("*")`, excluding the status file itself.
6. **Writes status file** — calls `write_status_file()` with `"completed"` or `"failed"`.
7. **POSTs callback** — reads the status file back and POSTs its contents to `CALLBACK_URL`.
8. **Exits** — `sys.exit(0)` on success, `sys.exit(1)` on failure.

The entire function is wrapped in a `try/except Exception` block. Any unhandled exception is caught, logged, written to the status file as an error, and reported via callback before exiting with code 1.

---

## 4. Environment Variable Contract

The gateway injects these environment variables when launching the R2R engine container:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `JOB_ID` | **Yes** | — | Unique job identifier. Triggers gateway mode when present. |
| `TENANT_ID` | No | `""` | Tenant who submitted the job. Included in status metadata. |
| `PDF_URL` | One of three | `""` | URL of the research paper PDF. |
| `PDF_BASE64` | One of three | `""` | Base64-encoded PDF content (for direct upload workflows). |
| `PAPER_TEXT` | One of three | `""` | Raw paper text (for pre-extracted content). |
| `OUTPUT_DIR` | No | `/tmp/r2r-{JOB_ID}` | Directory for generated repository output. |
| `ENGINE_OPTIONS` | No | `"{}"` | JSON string of pipeline options (see below). |
| `CALLBACK_URL` | No | `""` | URL to POST job results on completion. |
| `R2R_PROVIDER` | No | auto-detect | Override LLM provider (`gemini`, `openai`, `anthropic`, `ollama`). |
| `R2R_MODEL` | No | provider default | Override model name (e.g., `gpt-4o`, `gemini-2.5-pro-preview-05-06`). |
| `WEBHOOK_URL` | No | `""` | Gateway webhook endpoint URL (preferred over `CALLBACK_URL`). |
| `WEBHOOK_SECRET` | No | `""` | HMAC-SHA256 secret for signing webhook payloads. |
| `ARTIFACT_BACKEND` | No | auto-detect | Storage backend for artifact upload: `gcs`, `s3`, `azure`, `local`. |
| `ARTIFACT_BUCKET` | No | `""` | Bucket/container name for cloud artifact backends. |
| `GCS_ARTIFACT_BUCKET` | No | `""` | Legacy alias for `ARTIFACT_BUCKET` (GCS-only deploys). |
| `PRESIGNED_URL_TTL` | No | `"900"` | Pre-signed URL lifetime in seconds. |
| `LOCAL_ARTIFACT_DIR` | No | `""` | Base directory for local filesystem artifacts. |
| `AZURE_STORAGE_ACCOUNT_URL` | No | `""` | Azure storage account URL (for Azure backend). |

### Input Priority

At least one of `PDF_URL`, `PDF_BASE64`, or `PAPER_TEXT` must be provided. If multiple are set, priority is:

1. `PDF_URL` (always used if set)
2. `PDF_BASE64` (decoded to disk, used as a local PDF path)
3. `PAPER_TEXT` (passed as raw text — future support)

### ENGINE_OPTIONS Schema

The `ENGINE_OPTIONS` env var accepts a JSON string with these fields:

```json
{
  "mode": "agent",          // "classic" (default) or "agent"
  "refine": true,           // Enable self-refine loops (agent mode)
  "execute": false,         // Enable execution sandbox (agent mode)
  "evaluate": false,        // Enable reference evaluation (agent mode)
  "code_rag": false,        // Enable CodeRAG (agent mode, v3.1)
  "verbose": false,         // Enable verbose logging
  "skip_validation": false, // Skip validation (classic mode)
  "skip_tests": false,      // Skip test generation (classic mode)
  "provider": "gemini",     // LLM provider (overridden by R2R_PROVIDER env var)
  "model": "gemini-2.5-pro" // Model name (overridden by R2R_MODEL env var)
}
```

All fields are optional. Unrecognized fields are ignored. The `R2R_PROVIDER` and `R2R_MODEL` env vars take precedence over the `provider` and `model` fields inside `ENGINE_OPTIONS`.

### LLM API Keys

The gateway must also inject the appropriate LLM provider API key(s):

| Variable | Provider |
|----------|----------|
| `GEMINI_API_KEY` | Google Gemini |
| `OPENAI_API_KEY` | OpenAI GPT-4o/o3 |
| `ANTHROPIC_API_KEY` | Anthropic Claude |
| `OLLAMA_HOST` | Ollama (local/remote) |

These are standard R2R environment variables documented in [Usage Guide § Environment Variables](Usage-Guide#7-environment-variables). The gateway passes them through to the container unchanged.

---

## 5. End-to-End Flow: Gateway Mode

### Sequence Overview

```
Client (browser/API)
  |
  |  POST /api/v1/jobs  { engine: "research2repo", pdf_url: "...", options: {...} }
  |
  v
+------------------+
|  Any2Repo-Gateway|
|  (FastAPI)       |
+--------+---------+
         |
         |  1. Validate request, create Job record (status: "pending")
         |  2. Select backend (GCP, AWS, Azure, on-prem)
         |  3. Launch engine container with env vars:
         |       JOB_ID, TENANT_ID, PDF_URL, ENGINE_OPTIONS,
         |       OUTPUT_DIR, CALLBACK_URL, GEMINI_API_KEY, ...
         |
         v
+------------------+
|  Engine Container|
|  (R2R image)     |
+--------+---------+
         |
         |  ENTRYPOINT: python main.py
         |
         v
+------------------+
|  main.py         |
|  is_gateway_mode()|----> JOB_ID is set --> True
+--------+---------+
         |
         v
+------------------+
|  gateway_adapter |
|  .run_gateway_   |
|   mode()         |
+--------+---------+
         |
         |  Read env vars
         |  Parse ENGINE_OPTIONS
         |  Resolve input (PDF_URL / PDF_BASE64 / PAPER_TEXT)
         |
         v
+------------------+
|  run_agent() or  |
|  run_classic()   |
+--------+---------+
         |
         |  Pipeline stages execute:
         |    PaperAnalyzer -> Planner -> Coder -> Validator -> ...
         |
         v
+------------------+
|  Pipeline output |
|  written to      |
|  OUTPUT_DIR      |
+--------+---------+
         |
         |  Count generated files
         |  Write .any2repo_status.json
         |
         v
+------------------+
|  POST CALLBACK_  |
|  URL (best-      |
|  effort)         |
+--------+---------+
         |
         |  sys.exit(0)
         |
         v
+------------------+
|  Gateway receives|
|  callback or     |
|  detects exit    |
|  code 0          |
+--------+---------+
         |
         |  Update Job record (status: "completed")
         |  Notify client (webhook, poll response, etc.)
         |
         v
     Client gets results
```

### Failure Path

If any exception occurs during pipeline execution:

1. The exception is caught by the `try/except` block in `run_gateway_mode()`.
2. A status file is written with `status: "failed"` and the full error message.
3. The callback URL is POSTed with the failure payload (best-effort).
4. The process exits with code 1.
5. The gateway detects the non-zero exit code and/or the failure callback and updates the job accordingly.

---

## 6. Status File Protocol

The `.any2repo_status.json` file is written to `OUTPUT_DIR` on every gateway-mode run, whether the pipeline succeeds or fails. It follows the Any2Repo Engine Protocol v1.0 format.

### Schema

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | `string` | Unique job identifier (from `JOB_ID` env var) |
| `status` | `string` | `"completed"` or `"failed"` |
| `engine_id` | `string` | Always `"research2repo"` |
| `output_url` | `string` | URL to generated output (empty if not applicable) |
| `error` | `string` | Error description (empty on success) |
| `files_generated` | `int` | Number of files written to `OUTPUT_DIR` |
| `elapsed_seconds` | `float` | Wall-clock execution time |
| `completed_at` | `string` | ISO 8601 UTC timestamp |
| `metadata` | `object` | Engine-specific metadata (tenant, mode, provider) |
| `artifact_url` | `string` | Pre-signed download URL for the zipped artifact |
| `artifact_size_bytes` | `int` | Size of the zip artifact in bytes |

### Example: Successful Run

```json
{
  "job_id": "job-20250715-abc123",
  "status": "completed",
  "engine_id": "research2repo",
  "output_url": "",
  "error": "",
  "files_generated": 14,
  "elapsed_seconds": 187.34,
  "artifact_url": "https://storage.googleapis.com/my-bucket/jobs/job-20250715-abc123/output.zip?X-Goog-Signature=...",
  "artifact_size_bytes": 2457600,
  "completed_at": "2025-07-15T10:23:45.678901+00:00",
  "metadata": {
    "tenant_id": "acme-corp",
    "mode": "agent",
    "provider": "gemini",
    "model": "gemini-2.5-pro"
  }
}
```

### Example: Failed Run

```json
{
  "job_id": "job-20250715-def456",
  "status": "failed",
  "engine_id": "research2repo",
  "output_url": "",
  "error": "ValueError: PDF exceeds 100MB limit.",
  "files_generated": 0,
  "elapsed_seconds": 2.14,
  "completed_at": "2025-07-15T10:25:01.234567+00:00",
  "metadata": {
    "tenant_id": "acme-corp",
    "mode": "classic",
    "provider": "auto"
  }
}
```

### Status File Location

The file is always written to `{OUTPUT_DIR}/.any2repo_status.json`. When `OUTPUT_DIR` is not set, the default is `/tmp/r2r-{JOB_ID}`, so for `JOB_ID=abc123` the path would be `/tmp/r2r-abc123/.any2repo_status.json`.

---

## 7. Engine Manifest

R2R registers itself with the gateway using an engine manifest. This JSON document describes the engine's capabilities, accepted inputs, and container image. The gateway reads this manifest to know how to launch and interact with R2R.

```json
{
  "engine_id": "research2repo",
  "version": "2.0.0",
  "display_name": "Research2Repo",
  "description": "Convert ML/AI research papers into fully functional repositories",
  "protocol_version": "1.0",
  "capabilities": [
    "pdf_input",
    "text_input",
    "github_output",
    "local_output",
    "streaming_logs",
    "incremental_validation"
  ],
  "accepted_inputs": [
    "pdf_url",
    "pdf_base64",
    "paper_text"
  ],
  "container_image": "any2repo/research2repo:latest",
  "supported_backends": [
    "gcp_vertex",
    "aws_bedrock",
    "azure_ml",
    "on_prem"
  ]
}
```

### Manifest Fields

| Field | Description |
|-------|-------------|
| `engine_id` | Unique engine identifier used in API calls (`"research2repo"`). |
| `version` | Engine version following semver. |
| `display_name` | Human-readable name shown in the gateway UI. |
| `description` | Brief description of what the engine does. |
| `protocol_version` | Any2Repo Engine Protocol version this engine implements. |
| `capabilities` | List of capability tags. The gateway uses these for feature discovery. |
| `accepted_inputs` | Input types the engine can process. Maps to env vars (`pdf_url` → `PDF_URL`). |
| `container_image` | Docker image reference for container-based backends. |
| `supported_backends` | Which gateway backends can run this engine. |

### Capability Tags

| Tag | Meaning |
|-----|---------|
| `pdf_input` | Engine accepts PDF files (via URL or base64). |
| `text_input` | Engine accepts raw text input. |
| `github_output` | Engine can push generated repos to GitHub. |
| `local_output` | Engine writes output to a local directory. |
| `streaming_logs` | Engine produces real-time log output (stdout/stderr). |
| `incremental_validation` | Engine validates output against input during generation. |

---

## 8. Supported Backends

The gateway can launch R2R on multiple compute backends. The engine itself is backend-agnostic — it runs identically on all of them. The backend determines how the container is launched, how env vars are injected, and how output is collected.

### GCP Vertex AI

The gateway submits a Vertex AI Custom Job referencing the R2R container image. Environment variables are passed via the `CustomJobSpec.env` field. Output is written to a GCS-mounted volume or collected from the container filesystem after completion.

```
Gateway --> Vertex AI Custom Job API
               |
               +-- Container: any2repo/research2repo:latest
               +-- Env: JOB_ID, PDF_URL, GEMINI_API_KEY, ...
               +-- Machine: n1-standard-4 (or custom)
               +-- Output: /gcs/output/{JOB_ID}/
```

### AWS Bedrock

The gateway invokes R2R via a Bedrock custom model or SageMaker Processing Job. LLM calls from within the container can use Bedrock-hosted models via the `boto3` SDK, or external API keys can be injected as env vars.

```
Gateway --> SageMaker Processing Job
               |
               +-- Container: ECR image of R2R
               +-- Env: JOB_ID, PDF_URL, ...
               +-- Output: s3://bucket/output/{JOB_ID}/
```

### Azure ML

The gateway submits an Azure ML Job using the `azure-ai-ml` SDK. The R2R container runs as a command job with environment variables injected via the job configuration.

```
Gateway --> Azure ML Job
               |
               +-- Container: ACR image of R2R
               +-- Env: JOB_ID, PDF_URL, ...
               +-- Output: azureml://datastores/output/{JOB_ID}/
```

### On-Prem

For self-hosted deployments, the gateway launches R2R as a Docker container on the local machine or a designated worker node. Environment variables are passed via `docker run -e`. Output is mounted from a host directory.

```
Gateway --> docker run -e JOB_ID=... -e PDF_URL=... \
               -v /data/output:/output \
               any2repo/research2repo:latest
```

This is the simplest backend for development and testing.

---

## 9. Worked Examples

### Example 1: Standalone CLI (No Gateway)

The traditional way to run R2R. No gateway involvement, no env vars (other than API keys).

```bash
# Set your LLM provider API key
export GEMINI_API_KEY="your_key"

# Run with agent mode and self-refine
python main.py \
  --pdf_url "https://arxiv.org/pdf/1706.03762.pdf" \
  --mode agent \
  --refine

# Output is written to ./generated_repo/ by default
ls generated_repo/
```

What happens internally:
1. `main.py` checks `is_gateway_mode()` → `False` (no `JOB_ID`).
2. `argparse` processes `--pdf_url`, `--mode agent`, `--refine`.
3. `run_agent()` is called with the parsed arguments.
4. Pipeline runs the 10 agent stages.
5. Files are written to `./generated_repo/`.

### Example 2: Gateway Mode via Env Vars (Direct Execution)

Simulate gateway mode by setting env vars manually. Useful for local testing of the gateway integration without running the full gateway stack.

```bash
# Set LLM provider key
export GEMINI_API_KEY="your_key"

# Launch in gateway mode
JOB_ID=test-job-001 \
  TENANT_ID=acme-corp \
  PDF_URL="https://arxiv.org/pdf/1706.03762.pdf" \
  OUTPUT_DIR=/tmp/r2r-test-output \
  ENGINE_OPTIONS='{"mode":"agent","refine":true}' \
  python main.py
```

What happens internally:
1. `main.py` checks `is_gateway_mode()` → `True` (`JOB_ID` is set).
2. `run_gateway_mode()` is called — `argparse` is never invoked.
3. Env vars are read: `JOB_ID=test-job-001`, `PDF_URL=https://...`, etc.
4. `ENGINE_OPTIONS` is parsed: `{"mode": "agent", "refine": true}`.
5. `run_agent()` is called with `pdf_url`, `output_dir=/tmp/r2r-test-output`, `refine=True`.
6. Pipeline runs the 10 agent stages.
7. Files are written to `/tmp/r2r-test-output/`.
8. `.any2repo_status.json` is written to `/tmp/r2r-test-output/`.
9. No callback POST (no `CALLBACK_URL` set).
10. Process exits with code 0.

Verify the status file:

```bash
cat /tmp/r2r-test-output/.any2repo_status.json | python -m json.tool
```

### Example 3: Full Gateway Flow (API Call)

Submit a job through the gateway API. The gateway handles container orchestration, env var injection, and status tracking.

```bash
# Submit a job to the gateway
curl -X POST http://gateway:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-gateway-api-key" \
  -H "X-Tenant-ID: default" \
  -d '{
    "engine": "research2repo",
    "pdf_url": "https://arxiv.org/pdf/1706.03762.pdf",
    "options": {
      "mode": "agent",
      "refine": true
    }
  }'
```

Response:

```json
{
  "job_id": "job-20250715-abc123",
  "status": "pending",
  "engine": "research2repo",
  "created_at": "2025-07-15T10:20:00Z"
}
```

The gateway then:
1. Creates a job record with status `"pending"`.
2. Selects a backend (e.g., on-prem Docker).
3. Launches the R2R container with env vars:
   ```
   JOB_ID=job-20250715-abc123
   TENANT_ID=default
   PDF_URL=https://arxiv.org/pdf/1706.03762.pdf
   OUTPUT_DIR=/data/jobs/job-20250715-abc123/output
   ENGINE_OPTIONS={"mode":"agent","refine":true}
   CALLBACK_URL=http://gateway:8000/internal/callbacks/job-20250715-abc123
   GEMINI_API_KEY=...
   ```
4. R2R runs the pipeline, writes status file, POSTs callback.
5. Gateway updates job record to `"completed"`.

Poll for results:

```bash
curl http://gateway:8000/api/v1/jobs/job-20250715-abc123 \
  -H "X-API-Key: your-gateway-api-key"
```

---

## 10. Docker Deployment for Gateway Mode

### Dockerfile Considerations

When deploying R2R as a gateway-managed engine, the Docker image must satisfy these requirements:

1. **All R2R dependencies installed** — the container runs without network access to PyPI at runtime.
2. **ENTRYPOINT set to `python main.py`** — the gateway does not specify a command; it relies on the image entrypoint.
3. **No hardcoded API keys** — keys are injected as env vars at launch time.
4. **Writable `/tmp`** — the default `OUTPUT_DIR` is `/tmp/r2r-{JOB_ID}`.

### Sample Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for PDF processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install all provider SDKs
RUN pip install --no-cache-dir \
    google-generativeai \
    openai \
    anthropic \
    PyMuPDF \
    requests

# Copy application code
COPY . .

# Gateway injects env vars at launch time
# No API keys baked into the image
ENTRYPOINT ["python", "main.py"]
```

### Building and Tagging

```bash
# Build the image
docker build -t any2repo/research2repo:latest .

# Tag for a specific version
docker tag any2repo/research2repo:latest any2repo/research2repo:2.0.0

# Push to registry (for cloud backends)
docker push any2repo/research2repo:latest
docker push any2repo/research2repo:2.0.0
```

### Local Testing with Docker

```bash
docker run --rm \
  -e JOB_ID=docker-test-001 \
  -e PDF_URL="https://arxiv.org/pdf/1706.03762.pdf" \
  -e ENGINE_OPTIONS='{"mode":"classic"}' \
  -e GEMINI_API_KEY="your_key" \
  -e OUTPUT_DIR=/output \
  -v /tmp/r2r-docker-test:/output \
  any2repo/research2repo:latest
```

After the container exits, inspect the output:

```bash
ls /tmp/r2r-docker-test/
cat /tmp/r2r-docker-test/.any2repo_status.json
```

### Image Size Optimization

For production deployments, consider a multi-stage build to reduce image size:

```dockerfile
FROM python:3.11-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt
RUN pip install --no-cache-dir --prefix=/install \
    google-generativeai openai anthropic PyMuPDF requests

FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /install /usr/local
COPY . .
ENTRYPOINT ["python", "main.py"]
```

---

## 11. Integration with Any2Repo-Gateway

### Gateway Repository

The Any2Repo-Gateway is a separate project that provides the platform layer:

- **Repository:** [github.com/nellaivijay/Any2Repo-Gateway](https://github.com/nellaivijay/Any2Repo-Gateway)
- **Protocol Spec:** [Engine Protocol v1.0](https://github.com/nellaivijay/Any2Repo-Gateway/blob/main/docs/engine_protocol.md)
- **API Docs:** [Gateway API Reference](https://github.com/nellaivijay/Any2Repo-Gateway/blob/main/docs/api_reference.md)

### How R2R Registers as an Engine

The gateway discovers engines through manifest files or API registration. To register R2R:

**Option A: Manifest file placement**

Place the engine manifest (see [Section 7](#7-engine-manifest)) at a well-known path inside the gateway's engine directory:

```
gateway/engines/research2repo/manifest.json
```

The gateway scans this directory on startup and registers all discovered engines.

**Option B: API registration**

```bash
curl -X POST http://gateway:8000/api/v1/engines \
  -H "X-API-Key: admin-key" \
  -H "Content-Type: application/json" \
  -d @engine_manifest.json
```

### Gateway-Engine Communication

The gateway and R2R communicate exclusively through environment variables (input) and two output channels (status file + callback POST). There is no persistent connection, no gRPC stream, and no shared memory. This design makes the integration simple, debuggable, and compatible with any container runtime.

```
+------------------+          +------------------+         +------------------+
|  Any2Repo-       |          |  Research2Repo   |         |  Cloud Storage   |
|  Gateway         |          |  Engine          |         |  (GCS/S3/Azure)  |
+--------+---------+          +--------+---------+         +--------+---------+
         |                             |                            |
         |  ENV VARS (input)           |                            |
         |---------------------------->|                            |
         |                             |                            |
         |                             |  (pipeline runs)           |
         |                             |                            |
         |                             |  ARTIFACT UPLOAD           |
         |                             |--------------------------->|
         |                             |                            |
         |                             |  PRE-SIGNED URL            |
         |                             |<---------------------------|
         |                             |                            |
         |  WEBHOOK POST (HMAC signed) |                            |
         |  (includes artifact_url)    |                            |
         |<----------------------------|                            |
         |                             |                            |
         |  STATUS FILE (output)       |                            |
         |<----------------------------|                            |
         |                             |                            |
         |  EXIT CODE (signal)         |                            |
         |<----------------------------|                            |
+--------+---------+          +--------+---------+         +--------+---------+
```

### Multi-Engine Architecture

R2R is one of potentially many engines behind the gateway. Each engine implements the same protocol, enabling a unified API for diverse conversion tasks:

```
                    +------------------+
                    |  Any2Repo-       |
                    |  Gateway         |
                    +--------+---------+
                             |
              +--------------+--------------+
              |              |              |
              v              v              v
     +--------+---+  +------+-----+  +-----+------+
     | Research2  |  | Code2Repo  |  | Doc2Repo   |
     | Repo       |  | (code      |  | (docs      |
     | (papers    |  |  transform)|  |  to repos) |
     |  to repos) |  |            |  |            |
     +------------+  +------------+  +------------+
```

All engines share the same env var contract, status file format, and callback protocol. The gateway routes jobs to the correct engine based on the `engine` field in the job submission request.

---

## Related Pages

- [Architecture Overview](Architecture-Overview) — system architecture and component diagram
- [High-Level Design](High-Level-Design) — module responsibilities and pipeline architecture
- [Usage Guide](Usage-Guide) — CLI reference and standalone usage examples
- [Deployment & DevOps](Deployment-and-DevOps) — Docker deployment and CI/CD for R2R itself
- [Provider System & Configuration](Provider-System-and-Configuration) — LLM provider setup and capability routing
