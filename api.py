from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import SW_API_URL, SW_API_KEY, logger

_session = requests.Session()
_retry = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
)
_session.mount("https://", HTTPAdapter(max_retries=_retry))
_session.mount("http://", HTTPAdapter(max_retries=_retry))


def fetch_certs(
    status: str | None = None,
    limit: int = 200,
    since: str | None = None,
    since_reviewed: str | None = None,
    sort: str | None = None,
    cert_type: str | None = None,
) -> list[dict]:
    """
    This fetches the certs from the sw api :)
    """
    params: dict[str, str] = {"limit": str(limit)}
    if status:
        params["status"] = status
    if since:
        params["since"] = since
    if since_reviewed:
        params["since_reviewed"] = since_reviewed
    if sort:
        params["sort"] = sort
    if cert_type:
        params["type"] = cert_type
    try:
        resp = _session.get(
            SW_API_URL,
            headers={"Authorization": f"Bearer {SW_API_KEY}"},
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("Failed to fetch certs from API (params=%s)", params)
        return []
