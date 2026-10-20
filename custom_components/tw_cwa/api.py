"""Async client for the CWA open data REST API."""
from __future__ import annotations

import asyncio
import logging
import ssl
from typing import Any

import aiohttp
import certifi
from homeassistant.core import HomeAssistant

from .const import API_BASE, DOMAIN

_LOGGER = logging.getLogger(__name__)


class CwaError(Exception):
    """Generic API error."""


class CwaAuthError(CwaError):
    """Invalid or unauthorized API key."""


def _build_ssl_context() -> ssl.SSLContext:
    # The CWA certificate chain (TWCA) lacks a Subject Key Identifier, which
    # Python >= 3.13 rejects under VERIFY_X509_STRICT. Everything else
    # (chain, signature, hostname) is still verified.
    ctx = ssl.create_default_context(cafile=certifi.where())
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


async def async_get_ssl_context(hass: HomeAssistant) -> ssl.SSLContext:
    """Build (once) the SSL context in the executor; loading CAs blocks."""
    key = f"{DOMAIN}_ssl"
    if key not in hass.data:
        hass.data[key] = await hass.async_add_executor_job(_build_ssl_context)
    return hass.data[key]


class CwaClient:
    """Thin wrapper around /api/v1/rest/datastore/{dataset}."""

    def __init__(
        self, session: aiohttp.ClientSession, api_key: str, ssl_context: ssl.SSLContext
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._ssl = ssl_context

    async def get(self, dataset: str, **params: Any) -> dict[str, Any]:
        """Fetch a dataset and return its `records` object."""
        query = {"Authorization": self._api_key, "format": "JSON", **params}
        try:
            async with asyncio.timeout(30):
                resp = await self._session.get(f"{API_BASE}/{dataset}", params=query, ssl=self._ssl)
                if resp.status in (401, 403):
                    raise CwaAuthError("Invalid API key")
                resp.raise_for_status()
                body = await resp.json(content_type=None)
        except CwaError:
            raise
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.warning("Request to %s failed: %r", dataset, err)
            raise CwaError(f"Request to {dataset} failed: {err}") from err

        if str(body.get("success")).lower() != "true":
            raise CwaError(f"API reported failure for {dataset}: {body}")
        return body.get("records") or {}
