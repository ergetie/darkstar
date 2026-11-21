import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any, cast

import pytz
import yaml
from nordpool.elspot import Prices

from backend.core.atomic_json import write_json_atomic
from backend.core.cache import cache_sync
from backend.core.time_windows import matches, parse_window

logger = logging.getLogger("darkstar.core.prices")

# Processed Nordpool slots (import prices include fees); invalidated on pricing change.
NORDPOOL_CACHE_KEY = "nordpool_data"

# Seconds to serve an incomplete or failed fetch result before fetching again. Equals the
# planner's backoff cap so retries stay aligned, and bounds fetch timeouts to one per window.
FETCH_RETRY_SECONDS = 300.0
FETCH_TIMEOUT_SECONDS = 10.0
# Hour (local time) from which tomorrow's prices are expected to be published.
TOMORROW_PUBLISH_HOUR = 13

_LAST_GOOD_PATH = Path("data/nordpool_last_good.json")
# Stored entries that ended longer ago than this are dropped when the store is rewritten.
_LAST_GOOD_RETAIN = timedelta(days=1)

# Last complete set of published prices, mirrored from disk (loaded lazily on first use).
_last_good: dict[str, Any] | None = None
_last_good_loaded = False
# time.monotonic() before which a negative-cached result is served without refetching.
_retry_after = 0.0
# Whether the stored-price fallback was already announced at warning level.
_fallback_logged = False
# Whether the cached result came from a total fetch failure (stored future slots or empty).
_cached_total_failure = False


def reset_price_fetch_state() -> None:
    """Forget the in-memory last-good prices, the retry window and the fallback log state."""
    global _last_good, _last_good_loaded, _retry_after, _fallback_logged, _cached_total_failure
    _last_good = None
    _last_good_loaded = False
    _retry_after = 0.0
    _fallback_logged = False
    _cached_total_failure = False


def _log_fetch_failure(day: str, exc: BaseException) -> None:
    if isinstance(exc, TimeoutError):
        logger.warning(
            "Nordpool %s price fetch timed out after %.0f seconds", day, FETCH_TIMEOUT_SECONDS
        )
    else:
        logger.warning("Failed to fetch Nordpool %s prices: %s", day, exc, exc_info=True)


def _parse_last_good(payload: Any) -> dict[str, Any]:
    """Validate a stored payload and return it with datetimes parsed. Raises on bad format."""
    if not isinstance(payload, dict):
        raise ValueError("payload is not an object")
    payload = cast("dict[str, Any]", payload)
    entries: list[dict[str, Any]] = [
        {
            "start": datetime.fromisoformat(e["start"]),
            "end": datetime.fromisoformat(e["end"]),
            "value": float(e["value"]),
        }
        for e in payload["entries"]
    ]
    if any(e["start"].tzinfo is None or e["end"].tzinfo is None for e in entries):
        raise ValueError("entry timestamps must be timezone-aware")
    return {
        "price_area": str(payload["price_area"]),
        "currency": str(payload["currency"]),
        "resolution_minutes": int(payload["resolution_minutes"]),
        "saved_at": str(payload["saved_at"]),
        "entries": entries,
    }


def _load_last_good(
    price_area: str, currency: str, resolution_minutes: int
) -> dict[str, Any] | None:
    """
    Return the stored published prices if they match the configured area, currency and
    resolution, else ``None``. Reads the file once (lazily); a missing, unparsable or
    mismatched store is ignored, and corruption is logged once at warning.
    """
    global _last_good, _last_good_loaded
    if not _last_good_loaded:
        _last_good_loaded = True
        try:
            _last_good = _parse_last_good(json.loads(_LAST_GOOD_PATH.read_text(encoding="utf-8")))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("Ignoring stored Nordpool prices %s: %r", _LAST_GOOD_PATH, exc)
    stored = _last_good
    if stored is None:
        return None
    if (
        stored["price_area"] != price_area
        or stored["currency"] != currency
        or stored["resolution_minutes"] != resolution_minutes
    ):
        return None
    return stored


async def _save_last_good(
    entries: list[dict[str, Any]],
    price_area: str,
    currency: str,
    resolution_minutes: int,
    now: datetime,
) -> None:
    """
    Remember a complete set of raw published entries, in memory and on disk.

    Entries that ended more than a day ago are dropped. A disk failure is logged and
    never raised; the in-memory copy is still updated.
    """
    global _last_good, _last_good_loaded
    cutoff = now - _LAST_GOOD_RETAIN
    kept: list[dict[str, Any]] = [
        {"start": e["start"], "end": e["end"], "value": float(e["value"])}
        for e in entries
        if e["end"] > cutoff
    ]
    saved_at = now.isoformat()
    _last_good = {
        "price_area": price_area,
        "currency": currency,
        "resolution_minutes": resolution_minutes,
        "saved_at": saved_at,
        "entries": kept,
    }
    _last_good_loaded = True
    payload: dict[str, Any] = {
        "price_area": price_area,
        "currency": currency,
        "resolution_minutes": resolution_minutes,
        "saved_at": saved_at,
        "entries": [
            {"start": e["start"].isoformat(), "end": e["end"].isoformat(), "value": e["value"]}
            for e in kept
        ],
    }
    try:
        await asyncio.to_thread(write_json_atomic, _LAST_GOOD_PATH, payload)
    except Exception as exc:
        logger.warning("Could not store Nordpool prices %s: %r", _LAST_GOOD_PATH, exc)


async def _fetch_day(
    client: Any,
    day: Any,
    price_area: str,
    resolution_minutes: int,
    local_tz: tzinfo,
) -> list[dict[str, Any]]:
    """Fetch the raw price entries starting on ``day`` (local date). Raises on failure."""
    raw = await asyncio.wait_for(
        asyncio.to_thread(
            client.fetch,
            end_date=day,
            areas=[price_area],
            resolution=resolution_minutes,
        ),
        timeout=FETCH_TIMEOUT_SECONDS,
    )
    if not raw or "areas" not in raw or price_area not in raw["areas"]:
        return []
    values = raw["areas"][price_area].get("values", [])
    return [v for v in values if v["start"].astimezone(local_tz).date() == day]


def _stored_gap_entries(
    price_area: str,
    currency: str,
    resolution_minutes: int,
    now: datetime,
    fresh_starts: set[datetime],
) -> tuple[list[dict[str, Any]], str]:
    """
    Stored entries that have not ended and are not already fetched, plus the store's saved_at.

    The running slot is included; ended slots are never returned.
    """
    stored = _load_last_good(price_area, currency, resolution_minutes)
    if stored is None:
        return [], ""
    entries = [e for e in stored["entries"] if e["end"] > now and e["start"] not in fresh_starts]
    return entries, stored["saved_at"]


def _announce_fallback(count: int, saved_at: str) -> None:
    """Log that stored prices are in use: warning on first use, info on repeats."""
    global _fallback_logged
    log = logger.info if _fallback_logged else logger.warning
    log("Nordpool fetch incomplete, using stored prices (%d slots, saved %s)", count, saved_at)
    _fallback_logged = True


def _reset_fallback_log() -> None:
    global _fallback_logged
    _fallback_logged = False


def _cache_prices(processed: list[dict[str, Any]], *, complete: bool, total_failure: bool) -> None:
    """Cache a result: normally for an hour, briefly (and without refetching) if incomplete."""
    global _retry_after, _cached_total_failure
    if complete:
        _retry_after = 0.0
        ttl = 3600.0
    else:
        _retry_after = time.monotonic() + FETCH_RETRY_SECONDS
        ttl = FETCH_RETRY_SECONDS
    _cached_total_failure = total_failure
    cache_sync.set(NORDPOOL_CACHE_KEY, processed, ttl_seconds=ttl)


def _serve_stored_after_error(
    config: dict[str, Any],
    price_area: str,
    currency: str,
    resolution_minutes: int,
    now: datetime,
) -> list[dict[str, Any]]:
    """Total failure outside the fetch itself: serve stored future slots (or []) and back off."""
    try:
        entries, saved_at = _stored_gap_entries(
            price_area, currency, resolution_minutes, now, set()
        )
        if entries:
            _announce_fallback(len(entries), saved_at)
        processed = _process_nordpool_data(entries, config) if entries else []
    except Exception as exc:
        logger.warning("Could not use stored Nordpool prices: %s", exc, exc_info=True)
        processed = []
    _cache_prices(processed, complete=False, total_failure=True)
    return processed


async def get_nordpool_data(config_path: str = "config.yaml") -> list[dict[str, Any]]:
    # --- Smart Cache Check ---
    cache_key = NORDPOOL_CACHE_KEY
    cached = cache_sync.get(cache_key)

    with Path(config_path).open() as f:
        config = yaml.safe_load(f)
    local_tz = pytz.timezone(config.get("timezone", "Europe/Stockholm"))
    now = datetime.now(local_tz)
    today = now.date()

    if cached is not None and _cached_total_failure:
        # A cached [] is a hit too; slots that ended since caching must not be served.
        return [s for s in cached if s["end_time"] > now]

    if cached:
        retry_pending = time.monotonic() < _retry_after
        first_slot = cached[0]["start_time"]
        first_slot_date = first_slot.date() if hasattr(first_slot, "date") else today
        has_tomorrow = any(
            s["start_time"].date() > today for s in cached if hasattr(s["start_time"], "date")
        )

        if first_slot_date < today:
            cached = None
        elif first_slot > now and now.hour < 23:
            current_slot_start = now.replace(
                minute=(now.minute // 15) * 15, second=0, microsecond=0
            )
            if first_slot > current_slot_start:
                cached = None

        # Missing tomorrow is refetched, but not before the retry window has elapsed.
        if cached and now.hour >= 13 and not has_tomorrow and not retry_pending:
            cached = None

        if cached:
            return cached

    nordpool_config = config.get("nordpool", {})
    price_area = nordpool_config.get("price_area", "SE4")
    currency = nordpool_config.get("currency", "SEK")
    resolution_minutes = nordpool_config.get("resolution_minutes", 60)

    prices_client = Prices(currency=currency)

    try:
        # Today and tomorrow are fetched separately so a failed tomorrow keeps today's prices.
        today_values: list[dict[str, Any]] = []
        today_failed = False
        try:
            today_values = await _fetch_day(
                prices_client, today, price_area, resolution_minutes, local_tz
            )
        except Exception as exc:
            # Nordpool is unreachable; a second attempt for tomorrow would only add a timeout.
            today_failed = True
            _log_fetch_failure("today", exc)

        tomorrow_values: list[dict[str, Any]] = []
        if now.hour >= TOMORROW_PUBLISH_HOUR and not today_failed:
            try:
                tomorrow_values = await _fetch_day(
                    prices_client,
                    today + timedelta(days=1),
                    price_area,
                    resolution_minutes,
                    local_tz,
                )
            except Exception as exc:
                _log_fetch_failure("tomorrow", exc)

        all_entries = today_values + tomorrow_values
        total_failure = not today_values
        complete = not total_failure and (now.hour < TOMORROW_PUBLISH_HOUR or bool(tomorrow_values))

        # Only a complete fetch replaces the stored prices: today, and tomorrow once published.
        if complete:
            await _save_last_good(all_entries, price_area, currency, resolution_minutes, now)
            _reset_fallback_log()
        else:
            # Fill the gap with stored prices that have not ended; fresh entries win.
            gap_entries, saved_at = _stored_gap_entries(
                price_area,
                currency,
                resolution_minutes,
                now,
                {e["start"] for e in all_entries},
            )
            if gap_entries:
                _announce_fallback(len(gap_entries), saved_at)
                all_entries = all_entries + gap_entries

        # If no tomorrow data yet (before ~13:00 CET auction), try forecast fallback
        has_tomorrow_slots = any(
            e["start"].astimezone(local_tz).date() > today for e in all_entries
        )
        if not has_tomorrow_slots and now.hour < TOMORROW_PUBLISH_HOUR:
            try:
                from ml.price_forecast import get_d1_price_forecast_fallback

                forecast_fallback = await get_d1_price_forecast_fallback(config)
                if forecast_fallback:
                    # Convert forecast format to match Nordpool format
                    for fc in forecast_fallback:
                        slot_start = fc["slot_start"]
                        if isinstance(slot_start, str):
                            slot_start = datetime.fromisoformat(slot_start)
                        slot_start = (
                            slot_start.replace(tzinfo=local_tz)
                            if slot_start.tzinfo is None
                            else slot_start.astimezone(local_tz)
                        )
                        end_time = slot_start + timedelta(minutes=resolution_minutes)
                        all_entries.append(
                            {
                                "start": slot_start,
                                "end": end_time,
                                "value": fc.get("spot_p50", 0) * 1000,  # Convert SEK/kWh to SEK/MWh
                                "price_source": "forecast",
                                "forecast_days_ahead": fc.get("forecast_days_ahead"),
                            }
                        )
                    logger.info(
                        "[get_nordpool_data] Using D+1 price forecast fallback (%d slots)",
                        len(forecast_fallback),
                    )
            except Exception as exc:
                logger.warning("Failed to get D+1 price forecast fallback: %s", exc)

        processed = _process_nordpool_data(all_entries, config) if all_entries else []
        _cache_prices(processed, complete=complete, total_failure=total_failure)
        return processed
    except TimeoutError:
        logger.warning("Nordpool price fetch timed out after 10 seconds")
        return _serve_stored_after_error(config, price_area, currency, resolution_minutes, now)
    except Exception as exc:
        logger.warning("Failed to fetch Nordpool prices: %s", exc, exc_info=True)
        return _serve_stored_after_error(config, price_area, currency, resolution_minutes, now)


DEFAULT_GRID_TRANSFER_FEE_SEK = 0.2456
DEFAULT_ENERGY_TAX_SEK = 0.36
TRANSFER_FEE_MODE_FLAT = "flat"
TRANSFER_FEE_MODE_TOU = "time_of_use"

# Invalid-rule warnings already logged, so per-slot resolution doesn't flood the log.
_reported_invalid_rules: set[str] = set()


def _warn_invalid_rule_once(index: int, rule: Any, error: Exception) -> None:
    key = f"{index}:{rule!r}:{error}"
    if key in _reported_invalid_rules:
        return
    _reported_invalid_rules.add(key)
    logger.warning("Skipping invalid pricing.transfer_fee_rules[%d] (%s): %r", index, error, rule)


def resolve_transfer_fee(
    slot_start: datetime | None,
    pricing_cfg: dict[str, Any],
    tz: str | tzinfo = "Europe/Stockholm",
) -> float:
    """
    Resolve the grid transfer fee (SEK/kWh, excl. VAT) for a slot.

    In ``flat`` mode (default) or without ``slot_start`` the flat
    ``grid_transfer_fee_sek`` is returned. In ``time_of_use`` mode the ordered
    ``transfer_fee_rules`` are matched against the slot start in local time;
    the first match wins and the flat fee is the catch-all. Invalid rules are
    skipped with a (deduplicated) warning and never abort price calculation.

    Naive ``slot_start`` values are interpreted as already local.
    """
    flat_fee = float(pricing_cfg.get("grid_transfer_fee_sek", DEFAULT_GRID_TRANSFER_FEE_SEK))
    if slot_start is None:
        return flat_fee
    if pricing_cfg.get("transfer_fee_mode", TRANSFER_FEE_MODE_FLAT) != TRANSFER_FEE_MODE_TOU:
        return flat_fee

    rules: Any = pricing_cfg.get("transfer_fee_rules") or []
    if not isinstance(rules, list):
        _warn_invalid_rule_once(-1, rules, ValueError("transfer_fee_rules must be a list"))
        return flat_fee

    if slot_start.tzinfo is not None:
        local_tz = pytz.timezone(tz) if isinstance(tz, str) else tz
        local_dt = slot_start.astimezone(local_tz)
    else:
        local_dt = slot_start
    holidays_as_weekend = bool(pricing_cfg.get("holidays_as_weekend", False))

    for index, rule in enumerate(cast("list[Any]", rules)):
        try:
            window = parse_window(rule)
            fee = parse_rule_fee(rule)
        except ValueError as exc:
            _warn_invalid_rule_once(index, rule, exc)
            continue
        if matches(window, local_dt, holidays_as_weekend):
            return fee
    return flat_fee


def parse_rule_fee(rule: dict[str, Any]) -> float:
    """Return a rule's ``fee_sek``. Raises ``ValueError`` if missing/negative/non-numeric."""
    fee = rule.get("fee_sek")
    if isinstance(fee, bool) or not isinstance(fee, int | float):
        raise ValueError("fee_sek must be a number")
    if fee < 0:
        raise ValueError("fee_sek must not be negative")
    return float(fee)


def calculate_import_export_prices(
    spot_price_mwh: float,
    config: dict[str, Any],
    slot_start: datetime | None = None,
) -> tuple[float, float]:
    """
    Calculate import and export prices from spot price.

    Args:
        spot_price_mwh: Spot price in SEK/MWh
        config: Configuration dictionary
        slot_start: Slot start time. Used to resolve a time-of-use transfer fee;
            ``None`` uses the flat ``grid_transfer_fee_sek``.

    Returns:
        tuple: (import_price_sek_kwh, export_price_sek_kwh)
    """
    pricing_config = config.get("pricing", {})
    vat_percent = pricing_config.get("vat_percent", 25.0)
    grid_transfer_fee_sek = resolve_transfer_fee(
        slot_start, pricing_config, config.get("timezone", "Europe/Stockholm")
    )
    energy_tax_sek = pricing_config.get("energy_tax_sek", DEFAULT_ENERGY_TAX_SEK)
    supplier_markup_sek = float(pricing_config.get("supplier_markup_sek_kwh", 0.0) or 0.0)

    spot_price_sek_kwh = spot_price_mwh / 1000.0
    export_price_sek_kwh = spot_price_sek_kwh

    import_price_sek_kwh = (
        spot_price_sek_kwh + grid_transfer_fee_sek + energy_tax_sek + supplier_markup_sek
    ) * (1 + vat_percent / 100.0)

    return import_price_sek_kwh, export_price_sek_kwh


def _process_nordpool_data(
    all_entries: list[dict[str, Any]],
    config: dict[str, Any],
    today_values: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Process raw Nordpool API data into the required format.

    Args:
        all_entries: Combined list of raw price entries from today and tomorrow
        config: The full configuration dictionary, typed as dict[str, Any]

    Returns:
        list: Processed list of dictionaries with standardized format
    """
    result: list[dict[str, Any]] = []

    # Get local timezone
    local_tz = pytz.timezone(config.get("timezone", "Europe/Stockholm"))

    # Process the hourly data
    for i, entry in enumerate(all_entries):
        # Manual timezone conversion
        if today_values is not None and i < len(today_values):
            # Original entries - use their actual timestamps
            start_time = entry["start"].astimezone(local_tz)
            end_time = entry["end"].astimezone(local_tz)
        else:
            # Extended entries - calculate timestamps based on position
            if today_values is not None and len(today_values) > 0:
                base_start = today_values[0]["start"].astimezone(local_tz)
                slot_duration = today_values[0]["end"] - today_values[0]["start"]
                start_time = base_start + (slot_duration * i)
                end_time = start_time + slot_duration
            else:
                # Fallback if no today_values available
                start_time = entry["start"].astimezone(local_tz)
                end_time = entry["end"].astimezone(local_tz)

        import_price, export_price = calculate_import_export_prices(
            entry["value"], config, slot_start=start_time
        )

        processed_entry: dict[str, Any] = {
            "start_time": start_time,
            "end_time": end_time,
            "import_price_sek_kwh": import_price,
            "export_price_sek_kwh": export_price,
            "price_source": entry.get("price_source", "nordpool"),
        }
        # Forecast fallback slots carry the horizon of the issue they came from.
        if entry.get("forecast_days_ahead") is not None:
            processed_entry["forecast_days_ahead"] = entry["forecast_days_ahead"]
        result.append(processed_entry)

    # Sort by start time to ensure chronological order
    result.sort(key=lambda x: x["start_time"])

    # Deduplicate by start_time, keeping first occurrence (Nordpool wins over fallback)
    seen: set[Any] = set()
    deduped: list[dict[str, Any]] = []
    for entry in result:
        key = entry["start_time"]
        if key not in seen:
            seen.add(key)
            deduped.append(entry)
    dup_count = len(result) - len(deduped)
    if dup_count > 0:
        logger.info(
            "_process_nordpool_data dropped %d duplicate start_time entries (kept first occurrence)",
            dup_count,
        )

    return deduped


async def get_known_spot_by_slot(config_path: str = "config.yaml") -> dict[datetime, float]:
    """
    Return published Nordpool spot prices keyed by tz-aware local slot start.

    Values are raw spot in SEK/kWh (no fees/VAT). Entries synthesized from the
    D+1 forecast fallback (``price_source == "forecast"``) are excluded, so the
    map only contains genuinely known prices. On fetch failure an empty map is
    returned and a warning is logged; callers then fall back to forecasts.
    """
    try:
        price_data = await get_nordpool_data(config_path)
    except Exception as exc:
        logger.warning("Known spot prices unavailable, using forecasts only: %s", exc)
        return {}

    # Keys are 15-minute slot starts (the price-forecast grid), so coarser
    # Nordpool resolutions are expanded to one key per covered quarter-hour.
    quarter = timedelta(minutes=15)
    known: dict[datetime, float] = {}
    for slot in price_data:
        if slot.get("price_source") != "nordpool":
            continue
        spot = float(slot["export_price_sek_kwh"])
        slot_start = slot["start_time"]
        while slot_start < slot["end_time"]:
            known[slot_start] = spot
            slot_start += quarter
    if not known:
        logger.warning("Known spot prices unavailable, using forecasts only: no Nordpool data")
    return known


async def get_current_slot_prices(config: dict[str, Any]) -> dict[str, float] | None:
    """
    Fetch prices for the current 15-minute slot.
    """
    try:
        price_data = await get_nordpool_data()
        if not price_data:
            return None

        local_tz = pytz.timezone(config.get("timezone", "Europe/Stockholm"))
        now = datetime.now(local_tz)

        # Find the slot containing 'now'
        for slot in price_data:
            if slot["start_time"] <= now < slot["end_time"]:
                return {
                    "import_price_sek_kwh": slot["import_price_sek_kwh"],
                    "export_price_sek_kwh": slot["export_price_sek_kwh"],
                }
        return None
    except Exception as exc:
        logger.warning("Failed to get current slot prices: %s", exc)
        return None
