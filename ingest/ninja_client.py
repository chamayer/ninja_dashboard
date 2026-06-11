"""NinjaRMM v2 API client.

OAuth2 client-credentials auth (token cached in memory, refreshed on
401). Two pagination styles match Ninja's surface:
  - `after` — last-id, used by /organizations, /locations,
    /devices-detailed.
  - `cursor` — opaque cursor object on /queries/* endpoints.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Any

import httpx

from ingest.url_utils import redact_url

log = logging.getLogger(__name__)

_DEFAULT_PAGE_SIZE = 500
_MAX_RETRIES = 5
_RETRY_STATUSES = {429, 500, 502, 503, 504}
# Sanity cap — real datasets are orders of magnitude smaller. Guards
# against runaway loops if an endpoint's pagination model changes.
_MAX_PAGES = 1000


class NinjaClient:
    def __init__(
        self,
        base_url: str,
        token_url: str,
        client_id: str,
        client_secret: str,
        scope: str = "monitoring",
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope
        self._token: str | None = None
        self._http = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> NinjaClient:
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    # ── Auth ──────────────────────────────────────────────────────────

    def _fetch_token(self) -> str:
        log.debug("Fetching new OAuth token from %s", redact_url(self.token_url))
        resp = self._http.post(
            self.token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": self.scope,
            },
        )
        resp.raise_for_status()
        self._token = resp.json()["access_token"]
        return self._token

    def _ensure_token(self) -> str:
        if self._token is None:
            return self._fetch_token()
        return self._token

    # ── Request ───────────────────────────────────────────────────────

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        refreshed = False
        for attempt in range(_MAX_RETRIES):
            token = self._ensure_token()
            resp = self._http.get(
                url,
                params=params or {},
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code == 401 and not refreshed:
                log.info("401 from %s — refreshing token", path)
                self._token = None
                refreshed = True
                continue
            if resp.status_code in _RETRY_STATUSES:
                wait = self._retry_wait(resp, attempt)
                log.warning(
                    "%d from %s — retry %d/%d in %.1fs",
                    resp.status_code, path, attempt + 1, _MAX_RETRIES, wait,
                )
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError(f"Exhausted {_MAX_RETRIES} retries for GET {path}")

    @staticmethod
    def _retry_wait(resp: httpx.Response, attempt: int) -> float:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
        return min(2 ** attempt, 30)

    # ── Pagination ────────────────────────────────────────────────────

    def paginate_after(
        self,
        path: str,
        page_size: int = _DEFAULT_PAGE_SIZE,
        params: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield items from endpoints that use `after=<last_id>` paging
        (e.g. /organizations, /locations, /devices-detailed)."""
        cursor: int | None = None
        for _ in range(_MAX_PAGES):
            q = dict(params or {})
            q["pageSize"] = page_size
            if cursor is not None:
                q["after"] = cursor
            items = self.get(path, q)
            if not items:
                return
            for item in items:
                yield item
            cursor = items[-1]["id"]
        log.warning("paginate_after hit page cap (%d) on %s", _MAX_PAGES, path)

    def paginate_cursor(
        self,
        path: str,
        page_size: int = _DEFAULT_PAGE_SIZE,
        params: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield items from /queries/* endpoints using cursor paging.

        Ninja's cursor model on /queries/* endpoints returns the SAME
        cursor name across pages — the actual progress lives in
        cursor.offset / cursor.count. We stop on any of:
          - empty results
          - missing cursor in response
          - cursor.offset + len(results) >= cursor.count (primary)
          - cursor.offset didn't advance vs. last page (server-bug guard)
        """
        cursor_name: str | None = None
        last_offset = -1
        seen_records = 0
        pages_done = 0
        for _ in range(_MAX_PAGES):
            q = dict(params or {})
            q["pageSize"] = page_size
            if cursor_name is not None:
                q["cursor"] = cursor_name
            resp = self.get(path, q)
            results = resp.get("results") or []
            for item in results:
                yield item
            seen_records += len(results)
            pages_done += 1

            if not results:
                return

            cursor_obj = resp.get("cursor") or {}
            new_cursor_name = cursor_obj.get("name")
            offset = cursor_obj.get("offset")
            count = cursor_obj.get("count")

            # Heartbeat every 10 pages so big paginations don't look like
            # infinite loops to anyone tailing logs.
            if pages_done % 10 == 0:
                log.info(
                    "paginate_cursor %s: page %d, %d records, offset=%s count=%s",
                    path, pages_done, seen_records, offset, count,
                )

            if not new_cursor_name:
                return
            if (
                offset is not None
                and count is not None
                and offset + len(results) >= count
            ):
                return
            if offset is not None and offset <= last_offset:
                log.warning(
                    "Cursor offset stalled (%d → %d) on %s — stopping",
                    last_offset, offset, path,
                )
                return
            if offset is not None:
                last_offset = offset

            cursor_name = new_cursor_name
        log.warning(
            "paginate_cursor hit page cap (%d) on %s after %d records",
            _MAX_PAGES, path, seen_records,
        )
