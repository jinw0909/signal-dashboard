#!/usr/bin/env python3
"""
Fetch weekly win-rate signal snapshots and store them as static JSON files.

Expected layout:
    project-root/
    ├── data/
    │   ├── manifest.json
    │   └── snapshots/
    └── scripts/
        └── update_snapshot.py

Run manually:
    python3 scripts/update_snapshot.py

Example cron (every Sunday at 03:00):
    0 3 * * 0 /usr/bin/python3 /var/www/signal-dashboard/scripts/update_snapshot.py >> /var/log/signal-dashboard-snapshot.log 2>&1
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_API_URL = "http://3.36.217.232/winrate/symbol-list"
DEFAULT_RATES = (100, 90)
DEFAULT_PAGE_SIZE = 100
DEFAULT_TIMEOUT_SECONDS = 20

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"

LOGGER = logging.getLogger("update_snapshot")


class SnapshotUpdateError(RuntimeError):
    """Raised when the snapshot update cannot complete safely."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch weekly signal data and save static JSON snapshots."
    )
    parser.add_argument(
        "--api-url",
        default=os.getenv("SIGNAL_API_URL", DEFAULT_API_URL),
        help=f"Signal API endpoint. Default: {DEFAULT_API_URL}",
    )
    parser.add_argument(
        "--rates",
        nargs="+",
        type=int,
        default=list(DEFAULT_RATES),
        help="Rate values to fetch. Default: 100 90",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help=f"API page size. Default: {DEFAULT_PAGE_SIZE}",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"HTTP timeout in seconds. Default: {DEFAULT_TIMEOUT_SECONDS}",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"Directory containing manifest.json and snapshots/. Default: {DEFAULT_DATA_DIR}",
    )
    return parser.parse_args()


def fetch_json(url: str, *, timeout: int) -> dict[str, Any]:
    request = Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": "signal-dashboard-snapshot-updater/1.0",
        },
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read().decode(charset)
    except HTTPError as exc:
        raise SnapshotUpdateError(
            f"HTTP error while requesting {url}: {exc.code} {exc.reason}"
        ) from exc
    except URLError as exc:
        raise SnapshotUpdateError(
            f"Network error while requesting {url}: {exc.reason}"
        ) from exc
    except TimeoutError as exc:
        raise SnapshotUpdateError(f"Request timed out: {url}") from exc

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SnapshotUpdateError(f"Response is not valid JSON: {url}") from exc

    if not isinstance(payload, dict):
        raise SnapshotUpdateError(f"Expected JSON object but received another type: {url}")

    return payload


def fetch_rate_rows(
        api_url: str,
        *,
        rate: int,
        page_size: int,
        timeout: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page = 1

    while True:
        query = urlencode({"rate": rate, "page": page, "page_size": page_size})
        url = f"{api_url}?{query}"
        LOGGER.info("Fetching rate=%s page=%s", rate, page)

        payload = fetch_json(url, timeout=timeout)

        if payload.get("reCode") not in (None, 0):
            raise SnapshotUpdateError(
                f"API returned an error for rate={rate}, page={page}: "
                f"reCode={payload.get('reCode')}, message={payload.get('message')!r}"
            )

        results = payload.get("results")
        if not isinstance(results, list):
            raise SnapshotUpdateError(
                f"API results must be a list for rate={rate}, page={page}"
            )

        for item in results:
            if not isinstance(item, dict):
                raise SnapshotUpdateError(
                    f"Each result item must be an object for rate={rate}, page={page}"
                )
            rows.append(item)

        try:
            total_pages = int(payload.get("totalPages", 1))
        except (TypeError, ValueError) as exc:
            raise SnapshotUpdateError(
                f"Invalid totalPages for rate={rate}, page={page}: {payload.get('totalPages')!r}"
            ) from exc

        if page >= max(total_pages, 1):
            break
        page += 1

    return rows


def parse_snapshot_date(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SnapshotUpdateError("Every API row must contain a non-empty datetime string")

    raw = value.strip()

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass

    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except ValueError as exc:
        raise SnapshotUpdateError(f"Unsupported datetime format: {raw!r}") from exc


def normalize_rows(
        rows_by_rate: dict[int, list[dict[str, Any]]]
) -> tuple[str, list[dict[str, Any]]]:
    """Merge duplicate rows by (date, rate, signal), and deduplicate symbols."""
    grouped_symbols: dict[tuple[str, int, str], set[str]] = defaultdict(set)
    datetime_by_key: dict[tuple[str, int, str], str] = {}
    snapshot_dates: set[str] = set()

    for rate, rows in rows_by_rate.items():
        for item in rows:
            signal = item.get("signal")
            raw_datetime = item.get("datetime")
            symbols = item.get("list", [])

            if not isinstance(signal, str) or not signal.strip():
                raise SnapshotUpdateError(f"Invalid signal value in rate={rate}: {signal!r}")

            if not isinstance(symbols, list):
                raise SnapshotUpdateError(
                    f"Expected list field to be an array for rate={rate}, signal={signal!r}"
                )

            snapshot_date = parse_snapshot_date(raw_datetime)
            snapshot_dates.add(snapshot_date)

            key = (snapshot_date, rate, signal.strip())
            datetime_by_key.setdefault(key, str(raw_datetime))

            for symbol in symbols:
                if symbol is None:
                    continue
                normalized_symbol = str(symbol).strip()
                if normalized_symbol:
                    grouped_symbols[key].add(normalized_symbol)

    if not grouped_symbols:
        raise SnapshotUpdateError("No result rows were returned by the API")

    # if len(snapshot_dates) != 1:
    #     raise SnapshotUpdateError(
    #         "API returned multiple snapshot dates in a single run: "
    #         + ", ".join(sorted(snapshot_dates))
    #     )
    #
    # snapshot_date = next(iter(snapshot_dates))

    if not snapshot_dates:
        raise SnapshotUpdateError("No snapshot dates were found")

    if len(snapshot_dates) > 1:
        LOGGER.warning(
            "API returned multiple snapshot dates in a single run: %s. Using latest only.",
            ", ".join(sorted(snapshot_dates)),
        )

    snapshot_date = max(snapshot_dates)

    # normalized_rows = [
    #     {
    #         "signal": signal,
    #         "datetime": datetime_by_key[(date, rate, signal)],
    #         "rate": rate,
    #         "symbols": sorted(grouped_symbols[(date, rate, signal)]),
    #     }
    #     for date, rate, signal in sorted(
    #         grouped_symbols,
    #         key=lambda key: (-key[1], key[2]),
    #     )
    # ]


    normalized_rows = [
        {
            "signal": signal,
            "datetime": datetime_by_key[(date, rate, signal)],
            "rate": rate,
            "symbols": sorted(grouped_symbols[(date, rate, signal)]),
        }
        for date, rate, signal in sorted(
            grouped_symbols,
            key=lambda key: (-key[1], key[2]),
        )
        if date == snapshot_date
    ]

    return snapshot_date, normalized_rows


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    path.parent.chmod(0o755)

    fd, temp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temp_path = Path(temp_name)

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())

        temp_path.chmod(0o644)
        os.replace(temp_path, path)

    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"dates": [], "latest": None}

    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotUpdateError(f"Cannot read existing manifest: {path}") from exc

    if not isinstance(payload, dict):
        raise SnapshotUpdateError(f"Existing manifest must be a JSON object: {path}")

    return payload


def update_manifest(manifest_path: Path, snapshot_date: str) -> dict[str, Any]:
    existing = load_manifest(manifest_path)
    raw_dates = existing.get("dates", [])

    if not isinstance(raw_dates, list):
        raise SnapshotUpdateError("manifest.json field 'dates' must be an array")

    dates = {str(date).strip() for date in raw_dates if str(date).strip()}
    dates.add(snapshot_date)
    sorted_dates = sorted(dates, reverse=True)

    manifest = {"dates": sorted_dates, "latest": sorted_dates[0]}
    atomic_write_json(manifest_path, manifest)
    return manifest


def main() -> int:
    args = parse_args()

    if not args.rates:
        raise SnapshotUpdateError("At least one rate must be provided")
    if args.page_size <= 0:
        raise SnapshotUpdateError("--page-size must be greater than zero")
    if args.timeout <= 0:
        raise SnapshotUpdateError("--timeout must be greater than zero")

    data_dir = args.data_dir.expanduser().resolve()
    snapshots_dir = data_dir / "snapshots"
    manifest_path = data_dir / "manifest.json"

    rows_by_rate: dict[int, list[dict[str, Any]]] = {}
    for rate in args.rates:
        rows_by_rate[rate] = fetch_rate_rows(
            args.api_url,
            rate=rate,
            page_size=args.page_size,
            timeout=args.timeout,
        )

    snapshot_date, rows = normalize_rows(rows_by_rate)
    snapshot_payload = {
        "date": snapshot_date,
        "fetchedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rows": rows,
    }

    snapshot_path = snapshots_dir / f"{snapshot_date}.json"
    atomic_write_json(snapshot_path, snapshot_payload)
    manifest = update_manifest(manifest_path, snapshot_date)

    LOGGER.info("Saved snapshot: %s", snapshot_path)
    LOGGER.info("Updated manifest: %s", manifest_path)

    print(
        json.dumps(
            {
                "snapshot": str(snapshot_path),
                "manifest": str(manifest_path),
                "date": snapshot_date,
                "rows": len(rows),
                "availableDates": len(manifest["dates"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        raise SystemExit(main())
    except SnapshotUpdateError as exc:
        LOGGER.error("%s", exc)
        raise SystemExit(1)
