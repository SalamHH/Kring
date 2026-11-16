"""Expo Push API client (spec §8.7): send in batches of ≤ 100, read receipts.

Docs: https://docs.expo.dev/push-notifications/sending-notifications/
- POST /push/send with a JSON list of messages; the response has one ticket per message, in order:
  {"status": "ok", "id": <receipt id>} or {"status": "error", "message", "details": {"error"}}.
- POST /push/getReceipts with {"ids": [...]} (≤ 1 000); the response maps id → {"status", ...}.
  A receipt that isn't ready yet is simply missing.

429, 5xx, timeouts and connection errors are retried twice (after 1 s and 2 s), then ExpoFailed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import httpx

SEND_BATCH = 100
RECEIPT_BATCH = 1000
RETRY_DELAYS_S: tuple[float, ...] = (1.0, 2.0)


class ExpoFailed(Exception):
    pass


class ExpoClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        push_url: str,
        receipts_url: str,
        access_token: str | None = None,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        retry_delays_s: Sequence[float] = RETRY_DELAYS_S,
    ) -> None:
        self.http = http
        self.push_url = push_url
        self.receipts_url = receipts_url
        self.access_token = access_token
        self._sleep = sleep
        self._retry_delays_s = tuple(retry_delays_s)

    async def _post(self, url: str, payload: Any) -> Any:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        attempts = len(self._retry_delays_s) + 1
        reason = ""
        for attempt in range(attempts):
            try:
                resp = await self.http.post(url, json=payload, headers=headers, timeout=30.0)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                reason = f"{type(e).__name__}: {e}"
            else:
                if resp.status_code == 429 or resp.status_code >= 500:
                    reason = f"HTTP {resp.status_code}"
                elif resp.is_error:
                    raise ExpoFailed(f"HTTP {resp.status_code}: {resp.text[:300]}")
                else:
                    try:
                        return resp.json()
                    except ValueError as e:
                        raise ExpoFailed("invalid JSON from Expo") from e
            if attempt < attempts - 1:
                await self._sleep(self._retry_delays_s[attempt])
        raise ExpoFailed(f"{reason} (after {attempts} attempts)")

    async def send(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """One ticket per message, in order. Raises ExpoFailed for the whole batch."""
        tickets: list[dict[str, Any]] = []
        for i in range(0, len(messages), SEND_BATCH):
            batch = messages[i : i + SEND_BATCH]
            data = (await self._post(self.push_url, batch)).get("data")
            if not isinstance(data, list) or len(data) != len(batch):
                raise ExpoFailed(f"expected {len(batch)} tickets, got {data!r:.200}")
            tickets.extend(t if isinstance(t, dict) else {"status": "error"} for t in data)
        return tickets

    async def receipts(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for i in range(0, len(ids), RECEIPT_BATCH):
            data = (await self._post(self.receipts_url, {"ids": ids[i : i + RECEIPT_BATCH]})).get("data")
            if isinstance(data, dict):
                out.update({k: v for k, v in data.items() if isinstance(v, dict)})
        return out


def error_code(item: dict[str, Any]) -> str:
    details = item.get("details") if isinstance(item.get("details"), dict) else {}
    return str(details.get("error") or item.get("message") or "unknown")[:200]
