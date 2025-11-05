"""Client helpers for calling into the embedded deepeval-wrapper project.

The client instantiates the wrapper FastAPI application in-process and
executes requests against it via ASGI, avoiding any outbound HTTP sockets.
"""

from __future__ import annotations

import importlib
import logging
import os
import traceback
from types import ModuleType
from typing import Any, Optional

import httpx
from fastapi import FastAPI
from uvicorn.importer import import_from_string

logger = logging.getLogger(__name__)

# SECURITY: Override the wrapper's insecure default API key
# The wrapper defaults to "deepeval-default-key" which is publicly known and insecure.
# If API_KEYS is not set, we set it to empty string to disable wrapper auth entirely.
# This is safer than leaving a known default key active.
if "API_KEYS" not in os.environ:
    logger.warning(
        "API_KEYS not set - disabling wrapper authentication by setting API_KEYS to empty string. "
        "The wrapper's default 'deepeval-default-key' is publicly known and insecure. "
        "Set API_KEYS in your .env file to enable authentication for /wrapper/* endpoints."
    )
    os.environ["API_KEYS"] = ""


class DeepevalWrapperError(RuntimeError):
    """Raised when the deepeval wrapper cannot be reached or returns an error."""


class DeepevalWrapperClient:
    """Thin adapter around the existing deepeval-wrapper project."""

    def __init__(
        self,
        *,
        import_path: Optional[str] = None,
        expose_wrapper_app: bool = False,
    ) -> None:
        import_path_value = import_path or os.getenv(
            "DEEPEVAL_WRAPPER_IMPORT_PATH",
            "app.main",
        )
        self.import_path = import_path_value.strip()
        self._timeout = float(os.getenv("DEEPEVAL_HTTP_TIMEOUT", "30"))
        self._module: Optional[ModuleType] = None
        self._transport: Optional[httpx.ASGITransport] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._base_url = "http://deepeval-wrapper.local"
        self.wrapper_app: Optional[Any] = None  # Expose for mounting

        logger.info("Initialising DeepevalWrapperClient (import path=%s).", self.import_path)
        logger.info("PYTHONPATH: %s", os.environ.get("PYTHONPATH", "not set"))
        logger.info("Current working directory: %s", os.getcwd())

        self._module = self._load_module(self.import_path)
        logger.info("Successfully loaded wrapper module: %s", self._module.__name__ if self._module else "None")

        asgi_target = os.getenv("DEEPEVAL_WRAPPER_ASGI_TARGET")
        wrapper_app: Optional[Any] = None
        if asgi_target:
            try:
                logger.info("Importing ASGI app via environment target '%s'.", asgi_target)
                wrapper_app = import_from_string(asgi_target)
                logger.info("✓ Successfully loaded ASGI app from environment target")
            except Exception as e:
                logger.warning("✗ Failed to import ASGI target '%s': %s", asgi_target, str(e))
                logger.debug("Exception details:", exc_info=True)

        if wrapper_app is None:
            # Try standard target based on import path
            default_target = f"{self.import_path}:app" if self.import_path else None
            if default_target:
                try:
                    logger.info("Trying default ASGI target: %s", default_target)
                    wrapper_app = import_from_string(default_target)
                    logger.info("✓ Successfully loaded ASGI app from default target")
                except Exception as e:
                    logger.warning("✗ Default target '%s' failed: %s", default_target, str(e))

            # Also try common wrapper locations if above failed
            if wrapper_app is None:
                for fallback_target in ["app.main:app", "app:app"]:
                    try:
                        logger.info("Trying fallback ASGI target: %s", fallback_target)
                        wrapper_app = import_from_string(fallback_target)
                        logger.info("✓ Successfully loaded ASGI app from fallback target: %s", fallback_target)
                        break
                    except Exception as e:
                        logger.warning("✗ Fallback target '%s' failed: %s", fallback_target, str(e))

        if wrapper_app is None and self._module is not None:
            logger.info("Attempting to extract ASGI app from module attributes...")
            wrapper_app = self._extract_asgi_app(self._module)
            if wrapper_app:
                logger.info("✓ Extracted ASGI app from module")
            else:
                logger.warning("✗ Could not extract ASGI app from module")

        if wrapper_app is None:
            raise DeepevalWrapperError(
                f"Could not find FastAPI app in wrapper module '{self.import_path}'. "
                "Ensure the wrapper exposes an 'app' attribute or set DEEPEVAL_WRAPPER_ASGI_TARGET."
            )

        logger.debug(
            "Wrapper module exposes FastAPI app. Configuring ASGI transport (timeout=%ss).",
            self._timeout,
        )

        # Store wrapper app for potential mounting
        if expose_wrapper_app:
            self.wrapper_app = wrapper_app
            logger.info("Wrapper app exposed for direct mounting")

        self._transport = httpx.ASGITransport(app=wrapper_app)
        self._client = httpx.AsyncClient(
            transport=self._transport,
            base_url=self._base_url,
            timeout=self._timeout,
        )

    async def evaluate(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute the wrapper evaluate logic via ASGI and return its dictionary payload."""
        response = await self._asgi_request("POST", "/evaluate/", payload)
        if not isinstance(response, dict):
            raise DeepevalWrapperError("Unexpected evaluate response shape from wrapper")
        return response

    async def available_metrics(self) -> dict[str, Any]:
        """Return the available metrics exposed by the wrapper via ASGI."""
        response = await self._asgi_request("GET", "/metrics/")
        if not isinstance(response, dict):
            raise DeepevalWrapperError("Unexpected metrics response shape from wrapper")
        return response

    async def close(self) -> None:
        """Release any transport resources held by the client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        if self._transport is not None:
            await self._transport.aclose()
            self._transport = None

    # Internal helpers --------------------------------------------------

    def _load_module(self, import_path: str) -> ModuleType:
        candidates: list[str] = []
        if import_path:
            candidates.append(import_path)
        # Due to PYTHONPATH=/app:/app/deepeval_wrapper, the wrapper is importable as 'app.main'
        candidates.extend(["app.main", "app", "deepeval_wrapper.app.main"])
        candidates.append("deepeval_wrapper.api")

        last_tb: Optional[str] = None
        for mod in candidates:
            try:
                logger.info("Attempting to import wrapper module: %s", mod)
                module = importlib.import_module(mod)
                logger.info("✓ Successfully imported wrapper module: %s", mod)
                logger.info("Module file location: %s", getattr(module, "__file__", "unknown"))
                logger.info("Module attributes: %s", [x for x in dir(module) if not x.startswith("_")])
                return module
            except Exception as e:
                last_tb = traceback.format_exc()
                logger.warning("✗ Import of '%s' failed: %s", mod, str(e))
                logger.debug("Full traceback for '%s':\n%s", mod, last_tb)

        raise DeepevalWrapperError(
            f"Unable to import deepeval wrapper module. Tried: {candidates}. "
            "Set DEEPEVAL_WRAPPER_IMPORT_PATH to a valid module. "
            f"Last error:\n{last_tb}"
        )

    def _extract_asgi_app(self, module: ModuleType) -> Optional[FastAPI]:
        def _is_asgi(candidate: Any) -> bool:
            return callable(candidate) and hasattr(candidate, "__call__")

        app_attr = getattr(module, "app", None)
        if _is_asgi(app_attr):
            logger.debug("Found ASGI application as 'app' attribute on module '%s'.", module.__name__)
            return app_attr  # type: ignore[return-value]

        for attr_name in dir(module):
            if attr_name.startswith("_"):
                continue
            attr = getattr(module, attr_name)
            if isinstance(attr, FastAPI) or _is_asgi(attr):
                logger.debug(
                    "Detected ASGI-compatible attribute '%s' in module '%s'.",
                    attr_name,
                    module.__name__,
                )
                return attr  # type: ignore[return-value]

        for factory_name in ("create_app", "build_app", "get_app"):  # type: ignore[return-value]
            factory = getattr(module, factory_name, None)
            if callable(factory):
                try:
                    candidate = factory()
                except Exception:  # noqa: BLE001 - log and continue search
                    logger.debug(
                        "Calling potential ASGI factory '%s' on module '%s' failed.",
                        factory_name,
                        module.__name__,
                        exc_info=True,
                    )
                    continue
                if _is_asgi(candidate):
                    logger.debug(
                        "Using ASGI app returned by '%s' in module '%s'.",
                        factory_name,
                        module.__name__,
                    )
                    return candidate

        logger.debug(
            "No ASGI application detected in module '%s'. Attributes: %s",
            module.__name__,
            sorted(attr for attr in dir(module) if not attr.startswith("_")),
        )
        return None

    async def _asgi_request(self, method: str, path: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        if self._client is None:
            raise DeepevalWrapperError("ASGI transport not initialised.")

        try:
            logger.info("ASGI request to wrapper: %s %s (payload keys: %s)",
                       method.upper(), path, list(payload.keys()) if payload else None)
            response = await self._client.request(method, path, json=payload)
            logger.info(
                "ASGI response from wrapper: status=%s, content_length=%d",
                response.status_code,
                len(response.content),
            )
        except httpx.TimeoutException as exc:
            logger.error("Wrapper ASGI request timed out (%s %s).", method.upper(), path)
            raise DeepevalWrapperError("Wrapper request timed out.") from exc
        except httpx.HTTPError as exc:
            logger.error("Wrapper ASGI request failed.", exc_info=True)
            raise DeepevalWrapperError(f"Error while calling deepeval wrapper: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text
            logger.error("Wrapper returned error %s: %s", response.status_code, detail)
            raise DeepevalWrapperError(
                f"HTTP error from deepeval wrapper ({response.status_code}): {detail}"
            )

        if not response.content:
            logger.info("Wrapper returned empty response body")
            return {}

        try:
            result = response.json()
            logger.info("Wrapper response parsed successfully, keys: %s", list(result.keys()) if isinstance(result, dict) else type(result))
            return result
        except ValueError as exc:
            logger.error("Failed to parse wrapper response as JSON: %s", response.text[:200])
            raise DeepevalWrapperError("Wrapper returned invalid JSON.") from exc
