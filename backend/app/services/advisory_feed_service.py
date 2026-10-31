"""Reads the OSV advisory feed (docs/LIVE_DEPENDENCY_ALERTS.md section 5). The only module that does I/O
against OSV on behalf of live alerts.

Two hosts, both fixed: the GCS bucket (`<ECO>/modified_id.csv`, newest first, HTTP Range supported, and
`<ECO>/<ID>.json` records) and the OSV API (`v1/querybatch`, the same call the scanner makes, sending only
(ecosystem, package, version) triples). The base URLs come from settings, and the production validator
refuses anything but the defaults, so this module never reads from a host an attacker could name.

`_get` / `_post` are the only functions that touch the network; tests replace them.
"""

import json
import re
from datetime import datetime
from urllib.parse import quote

import httpx

from app.core.advisory import parse_modified_csv
from app.core.config import settings

_CHUNK = 256 * 1024
_MAX_CHUNKS = 8
_QUERY_CHUNK = 500
_MAX_PAGES = 3
_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")


class FeedError(Exception):
    """The feed answered with something unusable. The message never contains a URL."""


async def _get(url: str, headers: dict | None = None) -> tuple[int, bytes]:
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        resp = await client.get(url, headers=headers)
    return resp.status_code, resp.content


async def _post(url: str, payload: dict) -> tuple[int, dict]:
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        resp = await client.post(url, json=payload)
    try:
        body = resp.json()
    except ValueError:
        body = {}
    return resp.status_code, body if isinstance(body, dict) else {}


def _feed_url(ecosystem: str, name: str) -> str:
    return f"{settings.advisory_feed_base_url.rstrip('/')}/{quote(ecosystem, safe='')}/{name}"


async def _chunk(ecosystem: str, offset: int) -> tuple[int, bytes]:
    return await _get(
        _feed_url(ecosystem, "modified_id.csv"), {"Range": f"bytes={offset}-{offset + _CHUNK - 1}"}
    )


async def head_modified(ecosystem: str) -> datetime | None:
    """The newest `modified` in the ecosystem's index (None for an empty one). The first run's cursor."""
    status, body = await _get(_feed_url(ecosystem, "modified_id.csv"), {"Range": "bytes=0-4095"})
    if status not in (200, 206):
        raise FeedError(f"index returned HTTP {status}")
    rows = parse_modified_csv(body.decode("utf-8", "replace"), drop_partial_tail=status == 206 and len(body) >= 4096)
    return rows[0][0] if rows else None


async def fetch_rows_since(
    ecosystem: str, cursor: datetime, horizon: datetime
) -> tuple[list[tuple[datetime, str]], bool]:
    """Index rows with cursor < modified <= horizon, newest first, and whether the walk reached the cursor
    (or the start of history). At most 8 chunks of 256 KB are read, which covers well over a day per
    ecosystem; if the cursor is further back than that, `reached` is False and the caller records a gap.
    A line cut by a chunk boundary is carried into the next chunk rather than parsed half-way."""
    rows: list[tuple[datetime, str]] = []
    carry = b""
    offset = 0
    for _ in range(_MAX_CHUNKS):
        status, body = await _chunk(ecosystem, offset)
        if status == 416:  # past the end of the file
            return rows, True
        if status not in (200, 206):
            raise FeedError(f"index returned HTTP {status}")
        last = status == 200 or len(body) < _CHUNK  # a 200 ignored our Range: that is the whole file
        data = carry + body
        carry = b""
        if not last:
            cut = data.rfind(b"\n") + 1
            data, carry = data[:cut], data[cut:]
        reached = last
        for modified, advisory_id in parse_modified_csv(data.decode("utf-8", "replace"), drop_partial_tail=False):
            if modified <= cursor:
                reached = True
                break
            if modified <= horizon:
                rows.append((modified, advisory_id))
        if reached:
            return rows, True
        offset += _CHUNK
    return rows, False


async def fetch_record(ecosystem: str, advisory_id: str) -> dict | None:
    """One OSV record, or None if the feed has no such file (404). Anything else raises."""
    if not _ID_RE.match(advisory_id):
        raise FeedError("advisory id has an unexpected shape")
    status, body = await _get(_feed_url(ecosystem, f"{quote(advisory_id, safe='')}.json"))
    if status == 404:
        return None
    if status != 200:
        raise FeedError(f"record returned HTTP {status}")
    try:
        record = json.loads(body)
    except ValueError as exc:
        raise FeedError("record is not JSON") from exc
    if not isinstance(record, dict):
        raise FeedError("record is not an object")
    return record


async def confirm(pairs: list[tuple[str, str, str]]) -> dict[tuple[str, str, str], set[str]]:
    """Ask OSV's own matcher which advisories affect each (ecosystem, package, version). Chunks of 500
    queries, following `next_page_token` at most 3 times. Raises on any failure: a half-answered
    confirmation must never be read as "not affected"."""
    out: dict[tuple[str, str, str], set[str]] = {p: set() for p in pairs}
    url = f"{settings.osv_api_base_url.rstrip('/')}/v1/querybatch"
    for start in range(0, len(pairs), _QUERY_CHUNK):
        pending = [(p, None) for p in pairs[start : start + _QUERY_CHUNK]]
        for _ in range(_MAX_PAGES + 1):
            if not pending:
                break
            queries = []
            for (ecosystem, package, version), token in pending:
                query: dict = {"package": {"name": package, "ecosystem": ecosystem}, "version": version}
                if token:
                    query["page_token"] = token
                queries.append(query)
            status, body = await _post(url, {"queries": queries})
            results = body.get("results")
            if status != 200 or not isinstance(results, list) or len(results) != len(queries):
                raise FeedError(f"querybatch returned HTTP {status}")
            nxt = []
            for (pair, _), result in zip(pending, results):
                result = result or {}
                out[pair].update(v["id"] for v in result.get("vulns") or [] if isinstance(v, dict) and v.get("id"))
                if result.get("next_page_token"):
                    nxt.append((pair, result["next_page_token"]))
            pending = nxt
    return out
