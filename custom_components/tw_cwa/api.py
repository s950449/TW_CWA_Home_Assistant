"""Async client for the CWA open data REST API."""
from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from .const import API_BASE


class CwaError(Exception):
    """Generic API error."""


class CwaAuthError(CwaError):
    """Invalid or unauthorized API key."""


class CwaClient:
    """Thin wrapper around /api/v1/rest/datastore/{dataset}."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str) -> None:
        self._session = session
        self._api_key = api_key

    async def get(self, dataset: str, **params: Any) -> dict[str, Any]:
        """Fetch a dataset and return its `records` object."""
        query = {"Authorization": self._api_key, "format": "JSON", **params}
        try:
            async with asyncio.timeout(30):
                resp = await self._session.get(f"{API_BASE}/{dataset}", params=query)
                if resp.status in (401, 403):
                    raise CwaAuthError("Invalid API key")
                resp.raise_for_status()
                body = await resp.json(content_type=None)
        except CwaError:
            raise
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise CwaError(f"Request to {dataset} failed: {err}") from err

        if str(body.get("success")).lower() != "true":
            raise CwaError(f"API reported failure for {dataset}: {body}")
        return body.get("records") or {}
