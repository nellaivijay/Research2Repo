"""Gateway adapter — enables Research2Repo to run in dual mode.

When the ``JOB_ID`` environment variable is set, the engine runs in
**gateway mode**: it reads job parameters from env vars, executes the
pipeline, uploads the output artifact to cloud storage, and POSTs a
signed webhook callback to the gateway.

When ``JOB_ID`` is *not* set, the engine behaves exactly as before —
a standalone CLI tool driven by ``argparse``.

This module implements the Any2Repo Engine Protocol v1.0.
See: https://github.com/nellaivijay/Any2Repo-Gateway/blob/main/docs/engine_protocol.md

**Cloud-agnostic:** Supports GCS, S3, Azure Blob Storage, and local
filesystem for artifact delivery.  The storage backend is selected via
the ``ARTIFACT_BACKEND`` environment variable.

**Multi-model:** Provider and model overrides are forwarded from the
gateway's ``ENGINE_OPTIONS`` or dedicated env vars (``R2R_PROVIDER``,
``R2R_MODEL``) to the pipeline.
"""

from __future__ import annotations

import abc
import hashlib
import hmac
import json
import logging
import os
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("research2repo.gateway")


# ── Detection ────────────────────────────────────────────────────────────


def is_gateway_mode() -> bool:
    """Return True if the engine was launched by Any2Repo-Gateway.

    Gateway mode is indicated by the presence of the ``JOB_ID``
    environment variable, which the gateway always injects.
    """
    return bool(os.environ.get("JOB_ID"))


# ── Status file ──────────────────────────────────────────────────────────


def write_status_file(
    output_dir: str,
    job_id: str,
    status: str,
    *,
    output_url: str = "",
    error: str = "",
    files_generated: int = 0,
    elapsed_seconds: float = 0.0,
    artifact_url: str = "",
    artifact_size_bytes: int = 0,
    metadata: Optional[dict] = None,
) -> str:
    """Write ``.any2repo_status.json`` per the Engine Protocol spec.

    Args:
        output_dir: The directory where generated files were written.
        job_id: Unique job identifier (from ``JOB_ID`` env var).
        status: ``"completed"`` or ``"failed"``.
        output_url: URL to the generated output (optional).
        error: Error message (required when status is ``"failed"``).
        files_generated: Number of files produced.
        elapsed_seconds: Wall-clock execution time.
        artifact_url: Pre-signed URL to the zipped output artifact.
        artifact_size_bytes: Size of the zip artifact in bytes.
        metadata: Additional engine-specific metadata.

    Returns:
        Absolute path to the status file.
    """
    os.makedirs(output_dir, exist_ok=True)
    status_path = os.path.join(output_dir, ".any2repo_status.json")

    payload = {
        "job_id": job_id,
        "status": status,
        "engine_id": "research2repo",
        "output_url": output_url,
        "error": error,
        "files_generated": files_generated,
        "elapsed_seconds": round(elapsed_seconds, 2),
        "artifact_url": artifact_url,
        "artifact_size_bytes": artifact_size_bytes,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata or {},
    }

    with open(status_path, "w") as f:
        json.dump(payload, f, indent=2)

    logger.info("Wrote status file: %s (status=%s)", status_path, status)
    return status_path


# ═════════════════════════════════════════════════════════════════════════
# Cloud-Agnostic Artifact Storage
# ═════════════════════════════════════════════════════════════════════════


class BaseArtifactStore(abc.ABC):
    """Abstract interface for uploading artifacts and generating download URLs."""

    @abc.abstractmethod
    def upload(self, local_path: str, remote_key: str) -> str:
        """Upload a file and return its remote URI (gs://, s3://, etc.)."""

    @abc.abstractmethod
    def presigned_url(self, remote_key: str, ttl_seconds: int = 900) -> str:
        """Generate a time-limited download URL."""


class GCSArtifactStore(BaseArtifactStore):
    """Google Cloud Storage artifact store."""

    def __init__(self, bucket: str) -> None:
        self._bucket_name = bucket

    def upload(self, local_path: str, remote_key: str) -> str:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(self._bucket_name)
        blob = bucket.blob(remote_key)
        blob.upload_from_filename(local_path)
        uri = f"gs://{self._bucket_name}/{remote_key}"
        logger.info("Uploaded artifact to %s", uri)
        return uri

    def presigned_url(self, remote_key: str, ttl_seconds: int = 900) -> str:
        from google.cloud import storage
        client = storage.Client()
        blob = client.bucket(self._bucket_name).blob(remote_key)
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=ttl_seconds),
            method="GET",
        )
        logger.info("Generated GCS pre-signed URL (ttl=%ds)", ttl_seconds)
        return url


class S3ArtifactStore(BaseArtifactStore):
    """AWS S3 artifact store."""

    def __init__(self, bucket: str, region: str = "") -> None:
        self._bucket_name = bucket
        self._region = region or os.environ.get("AWS_REGION", "us-east-1")

    def _client(self):
        import boto3
        return boto3.client("s3", region_name=self._region)

    def upload(self, local_path: str, remote_key: str) -> str:
        self._client().upload_file(local_path, self._bucket_name, remote_key)
        uri = f"s3://{self._bucket_name}/{remote_key}"
        logger.info("Uploaded artifact to %s", uri)
        return uri

    def presigned_url(self, remote_key: str, ttl_seconds: int = 900) -> str:
        url = self._client().generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket_name, "Key": remote_key},
            ExpiresIn=ttl_seconds,
        )
        logger.info("Generated S3 pre-signed URL (ttl=%ds)", ttl_seconds)
        return url


class AzureBlobArtifactStore(BaseArtifactStore):
    """Azure Blob Storage artifact store."""

    def __init__(self, container: str, account_url: str = "") -> None:
        self._container_name = container
        self._account_url = account_url or os.environ.get(
            "AZURE_STORAGE_ACCOUNT_URL", ""
        )

    def _container_client(self):
        from azure.storage.blob import ContainerClient
        from azure.identity import DefaultAzureCredential
        return ContainerClient(
            self._account_url,
            self._container_name,
            credential=DefaultAzureCredential(),
        )

    def upload(self, local_path: str, remote_key: str) -> str:
        container = self._container_client()
        with open(local_path, "rb") as f:
            container.upload_blob(name=remote_key, data=f, overwrite=True)
        uri = f"https://{self._account_url}/{self._container_name}/{remote_key}"
        logger.info("Uploaded artifact to Azure Blob: %s", uri)
        return uri

    def presigned_url(self, remote_key: str, ttl_seconds: int = 900) -> str:
        from azure.storage.blob import BlobSasPermissions, generate_blob_sas
        from azure.identity import DefaultAzureCredential
        # Extract account name from URL
        account_name = self._account_url.split("//")[1].split(".")[0] if "//" in self._account_url else ""
        sas = generate_blob_sas(
            account_name=account_name,
            container_name=self._container_name,
            blob_name=remote_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
        )
        url = f"{self._account_url}/{self._container_name}/{remote_key}?{sas}"
        logger.info("Generated Azure SAS URL (ttl=%ds)", ttl_seconds)
        return url


class LocalArtifactStore(BaseArtifactStore):
    """Local filesystem artifact store for on-prem / dev use.

    Copies the artifact to a shared directory and returns a file:// URL.
    """

    def __init__(self, base_dir: str = "") -> None:
        self._base_dir = base_dir or os.environ.get(
            "LOCAL_ARTIFACT_DIR", "/tmp/any2repo-artifacts"
        )

    def upload(self, local_path: str, remote_key: str) -> str:
        dest = os.path.join(self._base_dir, remote_key)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(local_path, dest)
        logger.info("Copied artifact to %s", dest)
        return f"file://{dest}"

    def presigned_url(self, remote_key: str, ttl_seconds: int = 900) -> str:
        # Local store doesn't need signed URLs — return the file path
        path = os.path.join(self._base_dir, remote_key)
        return f"file://{path}"


def create_artifact_store() -> Optional[BaseArtifactStore]:
    """Factory: create the appropriate artifact store from env vars.

    Environment variables:
        ARTIFACT_BACKEND        — "gcs", "s3", "azure", "local" (auto-detected if not set)
        ARTIFACT_BUCKET         — Bucket / container name (required for cloud backends)
        GCS_ARTIFACT_BUCKET     — Legacy alias for ARTIFACT_BUCKET (GCS)
        AWS_REGION              — AWS region for S3
        AZURE_STORAGE_ACCOUNT_URL — Azure storage account URL
        LOCAL_ARTIFACT_DIR      — Base directory for local artifacts

    Returns None if no artifact storage is configured.
    """
    backend = os.environ.get("ARTIFACT_BACKEND", "").lower()
    bucket = os.environ.get("ARTIFACT_BUCKET", "") or os.environ.get("GCS_ARTIFACT_BUCKET", "")

    # Auto-detect backend from bucket name pattern
    if not backend and bucket:
        if os.environ.get("GCS_ARTIFACT_BUCKET"):
            backend = "gcs"
        elif os.environ.get("AWS_REGION") or bucket.startswith("s3://"):
            backend = "s3"
        elif os.environ.get("AZURE_STORAGE_ACCOUNT_URL"):
            backend = "azure"
        else:
            backend = "gcs"  # default cloud backend

    if not backend:
        # Check for local artifact directory
        if os.environ.get("LOCAL_ARTIFACT_DIR"):
            backend = "local"
        else:
            return None

    if backend == "gcs":
        if not bucket:
            logger.warning("ARTIFACT_BUCKET not set for GCS backend — skipping")
            return None
        return GCSArtifactStore(bucket)
    elif backend == "s3":
        if not bucket:
            logger.warning("ARTIFACT_BUCKET not set for S3 backend — skipping")
            return None
        return S3ArtifactStore(bucket, region=os.environ.get("AWS_REGION", ""))
    elif backend == "azure":
        if not bucket:
            logger.warning("ARTIFACT_BUCKET not set for Azure backend — skipping")
            return None
        return AzureBlobArtifactStore(
            container=bucket,
            account_url=os.environ.get("AZURE_STORAGE_ACCOUNT_URL", ""),
        )
    elif backend == "local":
        return LocalArtifactStore()
    else:
        logger.warning("Unknown ARTIFACT_BACKEND '%s' — skipping artifact upload", backend)
        return None


# ── Artifact upload orchestrator ─────────────────────────────────────────


def zip_output(output_dir: str) -> str:
    """Zip the output directory into a .zip archive.

    Returns the path to the zip file.
    """
    archive_base = output_dir.rstrip("/") + "_artifact"
    archive_path = shutil.make_archive(archive_base, "zip", output_dir)
    logger.info(
        "Zipped output: %s (%.2f MB)",
        archive_path,
        os.path.getsize(archive_path) / 1_048_576,
    )
    return archive_path


def upload_artifact(output_dir: str, job_id: str) -> tuple[str, int]:
    """Zip output, upload to cloud storage, return (presigned_url, size_bytes).

    Uses the ``ARTIFACT_BACKEND`` env var to select the storage backend.
    Falls back gracefully if storage is unavailable — returns empty string
    and zero size, allowing the status file to still be written.
    """
    ttl = int(os.environ.get("PRESIGNED_URL_TTL", "900"))
    store = create_artifact_store()

    if store is None:
        logger.warning("No artifact store configured — skipping artifact upload")
        return "", 0

    try:
        zip_path = zip_output(output_dir)
        size_bytes = os.path.getsize(zip_path)
        remote_key = f"jobs/{job_id}/output.zip"

        store.upload(zip_path, remote_key)
        presigned = store.presigned_url(remote_key, ttl_seconds=ttl)

        # Clean up local zip
        os.remove(zip_path)

        return presigned, size_bytes
    except Exception as exc:
        logger.error("Artifact upload failed: %s", exc, exc_info=True)
        return "", 0


# ── Webhook callback ─────────────────────────────────────────────────────


def post_callback(callback_url: str, payload: dict) -> bool:
    """POST job results to the gateway callback URL (best-effort).

    Returns True on success, False on failure (never raises).
    """
    if not callback_url:
        return False
    try:
        import requests
        resp = requests.post(callback_url, json=payload, timeout=30)
        resp.raise_for_status()
        logger.info("Callback POST to %s succeeded (HTTP %d)", callback_url, resp.status_code)
        return True
    except Exception as exc:
        logger.warning("Callback POST to %s failed: %s", callback_url, exc)
        return False


def post_webhook(webhook_url: str, payload: dict, secret: str = "") -> bool:
    """POST to the gateway webhook endpoint with optional HMAC signature.

    Args:
        webhook_url: Full URL (e.g. https://gateway/api/v1/webhooks/engine-complete).
        payload: The EngineWebhookPayload-shaped dict.
        secret: HMAC-SHA256 secret for signing. Empty = unsigned.

    Returns True on success, False on failure (never raises).
    """
    if not webhook_url:
        return False

    try:
        import requests

        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}

        if secret:
            sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            headers["X-Webhook-Signature"] = sig

        resp = requests.post(webhook_url, data=body, headers=headers, timeout=30)
        resp.raise_for_status()
        logger.info(
            "Webhook POST to %s succeeded (HTTP %d, signed=%s)",
            webhook_url, resp.status_code, bool(secret),
        )
        return True
    except Exception as exc:
        logger.warning("Webhook POST to %s failed: %s", webhook_url, exc)
        return False


# ── Gateway entry point ──────────────────────────────────────────────────


def run_gateway_mode() -> None:
    """Execute Research2Repo in gateway mode.

    Reads all parameters from environment variables:
        JOB_ID              — Unique job identifier (required)
        TENANT_ID           — Tenant who submitted the job
        PDF_URL             — URL of the research paper
        PDF_BASE64          — Base64-encoded PDF (alternative)
        PAPER_TEXT          — Raw paper text (alternative)
        OUTPUT_DIR          — Where to write generated files (default: /tmp/r2r-{JOB_ID})
        ENGINE_OPTIONS      — JSON string of additional options
        CALLBACK_URL        — Legacy: URL to POST results to on completion
        WEBHOOK_URL         — New: Gateway webhook endpoint URL
        WEBHOOK_SECRET      — HMAC secret for signing webhook payloads
        ARTIFACT_BACKEND    — Storage backend: "gcs", "s3", "azure", "local"
        ARTIFACT_BUCKET     — Bucket/container name for artifact upload
        GCS_ARTIFACT_BUCKET — Legacy alias for ARTIFACT_BUCKET (GCS)
        PRESIGNED_URL_TTL   — Pre-signed URL lifetime in seconds
        LOCAL_ARTIFACT_DIR  — Base directory for local artifact storage
        AZURE_STORAGE_ACCOUNT_URL — Azure storage account URL
        R2R_PROVIDER        — LLM provider override
        R2R_MODEL           — Model name override

    The function:
    1. Parses env vars into pipeline arguments
    2. Runs the appropriate pipeline (classic or agent)
    3. Zips and uploads the output to cloud storage (if configured)
    4. Writes ``.any2repo_status.json``
    5. POSTs a signed webhook to the gateway (or legacy callback)
    6. Exits with code 0 (success) or 1 (failure)
    """
    job_id = os.environ.get("JOB_ID", "")
    tenant_id = os.environ.get("TENANT_ID", "")
    pdf_url = os.environ.get("PDF_URL", "")
    pdf_base64 = os.environ.get("PDF_BASE64", "")
    paper_text = os.environ.get("PAPER_TEXT", "")
    output_dir = os.environ.get("OUTPUT_DIR", f"/tmp/r2r-{job_id}")
    callback_url = os.environ.get("CALLBACK_URL", "")
    webhook_url = os.environ.get("WEBHOOK_URL", "")
    webhook_secret = os.environ.get("WEBHOOK_SECRET", "")
    options_json = os.environ.get("ENGINE_OPTIONS", "{}")

    logger.info(
        "Gateway mode: job_id=%s tenant_id=%s pdf_url=%s output_dir=%s",
        job_id, tenant_id, pdf_url[:80] if pdf_url else "(none)", output_dir,
    )

    # Parse engine options
    try:
        options = json.loads(options_json) if options_json else {}
    except json.JSONDecodeError:
        options = {}

    mode = options.get("mode", "classic")
    provider_name = os.environ.get("R2R_PROVIDER") or options.get("provider")
    model_name = os.environ.get("R2R_MODEL") or options.get("model")

    # Handle base64 PDF input
    pdf_path = ""
    if pdf_base64 and not pdf_url:
        import base64
        pdf_path = os.path.join(output_dir, "input_paper.pdf")
        os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
        with open(pdf_path, "wb") as f:
            f.write(base64.b64decode(pdf_base64))
        logger.info("Decoded base64 PDF to %s", pdf_path)

    # Handle raw text input
    if paper_text and not pdf_url and not pdf_path:
        pdf_path = ""  # Will pass paper_text directly if supported

    start_time = time.time()
    files_generated = 0

    try:
        if mode == "agent":
            from main import run_agent
            run_agent(
                pdf_url=pdf_url,
                pdf_path=pdf_path,
                output_dir=output_dir,
                provider_name=provider_name,
                model_name=model_name,
                refine=options.get("refine", False),
                execute=options.get("execute", False),
                evaluate=options.get("evaluate", False),
                code_rag=options.get("code_rag", False),
                verbose=options.get("verbose", False),
            )
        else:
            from main import run_classic
            run_classic(
                pdf_url=pdf_url,
                pdf_path=pdf_path,
                output_dir=output_dir,
                provider_name=provider_name,
                model_name=model_name,
                skip_validation=options.get("skip_validation", False),
                skip_tests=options.get("skip_tests", False),
                verbose=options.get("verbose", False),
            )

        # Count generated files
        files_generated = sum(
            1 for _ in Path(output_dir).rglob("*") if _.is_file()
            and _.name != ".any2repo_status.json"
        )

        elapsed = time.time() - start_time
        logger.info("Pipeline completed: %d files in %.1fs", files_generated, elapsed)

        # Upload artifact to cloud storage and generate pre-signed URL
        artifact_url, artifact_size = upload_artifact(output_dir, job_id)

        status_path = write_status_file(
            output_dir=output_dir,
            job_id=job_id,
            status="completed",
            files_generated=files_generated,
            elapsed_seconds=elapsed,
            artifact_url=artifact_url,
            artifact_size_bytes=artifact_size,
            metadata={
                "tenant_id": tenant_id,
                "mode": mode,
                "provider": provider_name or "auto",
                "model": model_name or "default",
            },
        )

        # Notify gateway via webhook (preferred) or legacy callback
        if webhook_url:
            with open(status_path) as f:
                post_webhook(webhook_url, json.load(f), secret=webhook_secret)
        elif callback_url:
            with open(status_path) as f:
                post_callback(callback_url, json.load(f))

        sys.exit(0)

    except Exception as exc:
        elapsed = time.time() - start_time
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error("Pipeline failed: %s", error_msg, exc_info=True)

        status_path = write_status_file(
            output_dir=output_dir,
            job_id=job_id,
            status="failed",
            error=error_msg,
            files_generated=files_generated,
            elapsed_seconds=elapsed,
            metadata={
                "tenant_id": tenant_id,
                "mode": mode,
                "provider": provider_name or "auto",
                "model": model_name or "default",
            },
        )

        # Notify gateway even on failure
        if webhook_url:
            with open(status_path) as f:
                post_webhook(webhook_url, json.load(f), secret=webhook_secret)
        elif callback_url:
            with open(status_path) as f:
                post_callback(callback_url, json.load(f))

        sys.exit(1)
