"""Entrypoint for the Deepeval MCP bridge service."""

from __future__ import annotations

# MUST BE FIRST: Force UTF-8 encoding before any other imports
import src.encoding_fix  # noqa: F401

import asyncio
import logging
import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, model_validator
from starlette.concurrency import run_in_threadpool

from src import __version__
from src.services import DeepevalWrapperClient, DeepevalWrapperError

# Load environment variables early so the wrapper client sees them.
load_dotenv()

# Configure structured logging for the service.
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("deepeval_mcp")

app = FastAPI(
    title="Deepeval MCP Bridge",
    description=(
        "Expose Deepeval's evaluation logic through a Model Context Protocol interface. "
        "Also provides direct access to the deepeval-wrapper endpoints at /wrapper/*"
    ),
    version=__version__,
)

# Root endpoint with helpful navigation
@app.get("/", include_in_schema=True)
async def root() -> Dict[str, Any]:
    """Root endpoint with links to available APIs."""
    return {
        "service": "DeepEval MCP Bridge",
        "version": __version__,
        "endpoints": {
            "mcp_api": {
                "docs": "/docs",
                "description": "Synchronous evaluation endpoints with MCP-formatted responses",
                "endpoints": {
                    "evaluate": "POST /mcp/evaluate - Run evaluation with MCP formatting",
                    "metrics_list": "GET /mcp/metrics - List all available metrics",
                    "metrics_categories": "GET /mcp/metrics/categories - Get metrics by category",
                    "metric_info": "GET /mcp/metrics/{metric_type} - Get metric details",
                },
            },
            "wrapper_api": {
                "docs": "/wrapper/docs",
                "description": "Direct access to all deepeval-wrapper functionality",
                "synchronous": {
                    "evaluate": "POST /wrapper/evaluate/ - Single evaluation",
                    "bulk": "POST /wrapper/evaluate/bulk - Bulk evaluations",
                    "metrics": "GET /wrapper/metrics/ - List metrics",
                },
                "asynchronous": {
                    "note": "These create jobs and return immediately with job IDs",
                    "evaluate_async": "POST /wrapper/evaluate/async - Async single evaluation",
                    "bulk_async": "POST /wrapper/evaluate/async/bulk - Async bulk evaluation",
                    "dataset": "POST /wrapper/evaluate/dataset - Evaluate dataset file",
                    "jobs": "GET /wrapper/jobs/ - List all jobs",
                    "job_status": "GET /wrapper/jobs/{job_id} - Get job status",
                    "job_cancel": "POST /wrapper/jobs/{job_id}/cancel - Cancel job",
                    "job_delete": "DELETE /wrapper/jobs/{job_id} - Delete job",
                },
            },
        },
        "recommendations": {
            "quick_evaluations": "Use /mcp/* endpoints for immediate results with MCP formatting",
            "batch_processing": "Use /wrapper/evaluate/async/bulk for large batches",
            "direct_access": "Use /wrapper/* for advanced features and job management",
        },
    }

# Simple liveness endpoint to satisfy container/infra health checks
@app.get("/health", include_in_schema=False)
async def health() -> Dict[str, Any]:
    return {"status": "ok"}

wrapper_client: Optional[DeepevalWrapperClient] = None

# Parse API_KEYS as comma-separated list for MCP endpoint authentication
raw_api_keys = os.getenv("API_KEYS", "").strip()
api_keys_list: list[str] = [key.strip() for key in raw_api_keys.split(",") if key.strip()] if raw_api_keys else []


def require_api_key(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")) -> None:
    """Verify that the incoming request carries a valid API key from the configured list."""
    if not api_keys_list:
        # No API keys configured - authentication disabled
        return

    if x_api_key is None:
        logger.warning("API key authentication failed: No X-API-Key header provided.")
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Check if provided key matches any configured key using constant-time comparison
    if not any(secrets.compare_digest(x_api_key, valid_key) for valid_key in api_keys_list):
        logger.warning("API key authentication failed: Key not in authorized list.")
        raise HTTPException(status_code=401, detail="Invalid API key")


class EvaluationRequest(BaseModel):
    """Pydantic model for evaluation requests; wraps arbitrary payloads."""

    model_config = ConfigDict(extra="allow")

    data: Dict[str, Any]

    @model_validator(mode="before")
    @classmethod
    def ensure_data_wrapper(cls, values: Any) -> Any:
        if isinstance(values, dict) and "data" not in values:
            return {"data": values}
        return values


def _get_wrapper() -> DeepevalWrapperClient:
    if wrapper_client is None:
        raise HTTPException(status_code=503, detail="Wrapper client not initialised.")
    return wrapper_client


def _mcp_response(data: Dict[str, Any]) -> tuple[Dict[str, Any], str]:
    """Return a JSON MCP result envelope."""
    request_id = str(uuid.uuid4())
    return {
        "type": "mcp.result",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": "deepeval",
        "request_id": request_id,
        "data": data,
    }, request_id


def print_startup_banner():
    """Print a fancy startup banner with service information."""
    banner = """
╔══════════════════════════════════════════════════════════════════════╗
║                                                                      ║
║              🚀 DeepEval MCP Bridge Server 🚀                        ║
║                                                                      ║
║  A Model Context Protocol server for DeepEval LLM evaluations       ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝

📚 API Documentation:
   • MCP API (wrapped responses):  http://localhost:8000/docs
   • Wrapper API (full access):    http://localhost:8000/wrapper/docs
   • API Discovery:                http://localhost:8000/

🎯 Quick Start:
   • POST /mcp/evaluate           - Run evaluation with MCP formatting
   • GET  /mcp/metrics            - List available metrics
   • POST /wrapper/evaluate/      - Direct wrapper access (all features)

💡 Features:
   ✓ In-process ASGI communication (no network overhead)
   ✓ MCP-formatted responses for protocol compliance
   ✓ Direct wrapper access for advanced features
   ✓ Async job management via /wrapper/jobs/*
   ✓ Comprehensive logging and error handling

"""
    # Print to stdout so it appears in docker logs
    print(banner, flush=True)


@app.on_event("startup")
async def startup() -> None:
    """Initialise the Deepeval wrapper client when the app boots."""
    global wrapper_client

    # Print fancy startup banner
    print_startup_banner()

    # Check for at least one LLM API key
    llm_keys = {
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", "").strip(),
        "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", "").strip(),
        "GOOGLE_API_KEY": os.getenv("GOOGLE_API_KEY", "").strip(),
    }

    configured_keys = [name for name, value in llm_keys.items() if value]

    if not configured_keys:
        logger.error(
            "No LLM API keys configured! DeepEval requires at least one of: "
            "OPENAI_API_KEY, ANTHROPIC_API_KEY, or GOOGLE_API_KEY. "
            "Please set one in your .env file."
        )
        # Keep the process alive so health checks and diagnostics remain reachable
        return

    logger.info("LLM API keys configured: %s", ", ".join(configured_keys))

    # Log API authentication status
    if api_keys_list:
        logger.info("API authentication enabled: %d key(s) configured for /mcp/* and /wrapper/* endpoints", len(api_keys_list))
    else:
        logger.warning(
            "API authentication DISABLED: No API_KEYS configured. "
            "Both /mcp/* and /wrapper/* endpoints are publicly accessible. "
            "Set API_KEYS in your .env file to enable authentication."
        )

    # Log DeepEval version for debugging
    deepeval_version = "unknown"
    try:
        import deepeval
        deepeval_version = deepeval.__version__
        logger.info("DeepEval version: %s", deepeval_version)
    except Exception as e:
        logger.warning("Could not determine DeepEval version: %s", e)

    logger.debug("Initialising wrapper client on startup.")
    try:
        wrapper_client = DeepevalWrapperClient(expose_wrapper_app=True)
        logger.info("Wrapper client initialised.")

        # Mount the wrapper's FastAPI app to expose all its endpoints directly
        if wrapper_client.wrapper_app:
            app.mount("/wrapper", wrapper_client.wrapper_app)
            logger.info("Wrapper app mounted at /wrapper - all wrapper endpoints are now accessible!")
            logger.info("Available wrapper routes: /wrapper/evaluate/, /wrapper/metrics/, /wrapper/jobs/, etc.")
    except Exception:
        # Do not crash the container; surface the failure via logs and /healthz
        logger.exception(
            "Failed to initialise Deepeval wrapper client. "
            "Service will stay up, but /mcp/* and /wrapper/* will return 503."
        )
        wrapper_client = None
        return

    # Print startup completion
    print("\n" + "="*70)
    print("✅ Server initialization complete!")
    print("="*70)
    print(f"🌐 Server will be available at: http://0.0.0.0:8000")
    print(f"📊 Health check endpoint:       http://0.0.0.0:8000/health")
    print(f"🔑 Configured LLM providers:    {', '.join(configured_keys)}")
    print(f"📦 DeepEval version:            {deepeval_version}")
    if api_keys_list:
        print(f"🔐 API authentication:          ENABLED ({len(api_keys_list)} key(s))")
    else:
        print(f"⚠️  API authentication:          DISABLED (set API_KEYS to enable)")
    print("="*70 + "\n", flush=True)


@app.on_event("shutdown")
async def shutdown() -> None:
    """Release wrapper resources during application shutdown."""
    global wrapper_client
    if wrapper_client is None:
        return
    logger.debug("Shutting down wrapper client.")
    try:
        await wrapper_client.close()
    except Exception:  # noqa: BLE001 - best-effort cleanup
        logger.warning("Wrapper client close() failed.", exc_info=True)
    logger.info("Wrapper client shutdown complete.")
    wrapper_client = None


@app.post("/mcp/evaluate")
async def mcp_evaluate(payload: EvaluationRequest, _: None = Depends(require_api_key)) -> JSONResponse:
    """Run a Deepeval evaluation and wrap the result in an MCP response."""
    wrapper = _get_wrapper()
    logger.info("Received evaluation request with data: %s", payload.data)
    try:
        logger.info("Calling wrapper.evaluate() via ASGI...")
        result = await asyncio.wait_for(wrapper.evaluate(payload.data), timeout=30)
        logger.info("Wrapper evaluate completed successfully")
    except DeepevalWrapperError as exc:
        logger.error("Deepeval evaluation failed: %s", str(exc), exc_info=True)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except asyncio.TimeoutError as exc:
        logger.error("Deepeval evaluation timed out after 30s", exc_info=True)
        raise HTTPException(status_code=504, detail="Wrapper call timed out") from exc
    except Exception as exc:
        logger.error("Unexpected error during evaluation: %s", str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Evaluation error: {str(exc)}") from exc

    content, request_id = _mcp_response(result)
    return JSONResponse(
        status_code=200,
        content=content,
        headers={"X-Request-ID": request_id},
    )


@app.get("/mcp/metrics")
async def mcp_metrics(_: None = Depends(require_api_key)) -> JSONResponse:
    """List all available metrics with MCP formatting."""
    wrapper = _get_wrapper()
    try:
        metrics = await asyncio.wait_for(wrapper.available_metrics(), timeout=30)
    except DeepevalWrapperError as exc:
        logger.error("Deepeval metrics lookup failed.", exc_info=True)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except asyncio.TimeoutError as exc:
        logger.error("Deepeval metrics request timed out.", exc_info=True)
        raise HTTPException(status_code=504, detail="Wrapper call timed out") from exc

    content, request_id = _mcp_response(metrics)
    return JSONResponse(
        status_code=200,
        content=content,
        headers={"X-Request-ID": request_id},
    )


@app.get("/mcp/metrics/categories")
async def mcp_metrics_categories(_: None = Depends(require_api_key)) -> JSONResponse:
    """Get metrics organized by category with MCP formatting."""
    wrapper = _get_wrapper()
    try:
        response = await wrapper._asgi_request("GET", "/metrics/categories")
    except DeepevalWrapperError as exc:
        logger.error("Metrics categories lookup failed.", exc_info=True)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    content, request_id = _mcp_response(response)
    return JSONResponse(
        status_code=200,
        content=content,
        headers={"X-Request-ID": request_id},
    )


@app.get("/mcp/metrics/{metric_type}")
async def mcp_metric_info(metric_type: str, _: None = Depends(require_api_key)) -> JSONResponse:
    """Get detailed information about a specific metric with MCP formatting."""
    wrapper = _get_wrapper()
    try:
        response = await wrapper._asgi_request("GET", f"/metrics/{metric_type}")
    except DeepevalWrapperError as exc:
        logger.error("Metric info lookup failed for %s.", metric_type, exc_info=True)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    content, request_id = _mcp_response(response)
    return JSONResponse(
        status_code=200,
        content=content,
        headers={"X-Request-ID": request_id},
    )


@app.get("/healthz", include_in_schema=False)
async def healthz() -> Dict[str, Any]:
    """Lightweight container liveness probe."""
    wrapper_status: Dict[str, Any] = {"status": "uninitialised"}
    if wrapper_client is not None:
        wrapper_status = {"status": "ready"}
        ping_callable = getattr(wrapper_client, "ping", None)
        if callable(ping_callable):
            try:
                ping_result = await run_in_threadpool(ping_callable)
                wrapper_status["result"] = ping_result
            except DeepevalWrapperError as exc:
                logger.error("Wrapper ping failed.", exc_info=True)
                wrapper_status = {"status": "error", "detail": str(exc)}
            except Exception as exc:  # noqa: BLE001 - surface unexpected failures
                logger.error("Unexpected wrapper ping failure.", exc_info=True)
                wrapper_status = {"status": "error", "detail": str(exc)}

    return {"status": "ok", "wrapper": wrapper_status}
