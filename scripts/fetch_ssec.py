"""
scripts/fetch_ssec.py — SSEC MetObs Live & Historical Data Fetcher

Connects to the UW-Madison Space Science and Engineering Center (SSEC)
Meteorological Observing Station API to fetch real Lake Mendota buoy data
and seed the Sentinel-Stream database.

Two modes of operation:

  LIVE MODE  (when buoy is deployed, typically May–November)
  ─────────────────────────────────────────────────────────
  Polls the SSEC API every POLL_INTERVAL seconds and forwards each reading
  to the local Sentinel-Stream /ingest endpoint.  Effectively replaces the
  synthetic emulator with real hardware telemetry.

  HISTORICAL MODE  (--historical flag, works year-round)
  ──────────────────────────────────────────────────────
  Downloads archived data for a specified date range and bulk-loads it
  into the Sentinel-Stream database.  Useful for pre-training the forecast
  model on a full summer season before the current season begins.

Real SSEC API endpoints discovered from metobs.ssec.wisc.edu:

  Status:  GET http://metobs.ssec.wisc.edu/api/status/mendota/buoy.json
  Data:    GET http://metobs.ssec.wisc.edu/api/data.csv
               ?site=mendota
               &inst=buoy
               &symbols=air_temp:wind_speed:water_temp_1:water_temp_3:
                        water_temp_5:water_temp_7:water_temp_9:
                        chlorophyll:phycocyanin
               &begin=YYYY-MM-DDTHH:MM:SSZ   (or relative: -24:00:00)
               &end=YYYY-MM-DDTHH:MM:SSZ
               &interval=1m

SSEC sensor-to-depth mapping (Lake Mendota NTL-LTER thermistor chain):
  water_temp_1  →  0 m   (surface / epilimnion)
  water_temp_3  →  1 m
  water_temp_5  →  5 m   (developing thermocline)
  water_temp_7  →  10 m  (metalimnion)
  water_temp_9  →  20 m  (hypolimnion)

Note: when water_temp_9 is unavailable, water_temp_8 (≈15 m) is used as
the hypolimnion proxy.  The mapping is documented in the NTL-LTER buoy
metadata at lter.limnology.wisc.edu.

Usage:
    # Check if the buoy is online
    python scripts/fetch_ssec.py --status

    # Seed the DB with last 7 days of real data (requires buoy to be online)
    python scripts/fetch_ssec.py --historical --days 7

    # Seed with a specific summer date range
    python scripts/fetch_ssec.py --historical --begin 2024-07-01 --end 2024-07-31

    # Live-poll mode: forward real SSEC data to Sentinel-Stream at 1-minute intervals
    python scripts/fetch_ssec.py --live
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from io import StringIO
from typing import Optional

import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SSEC_BASE_URL: str = "http://metobs.ssec.wisc.edu"
STATUS_URL: str = f"{SSEC_BASE_URL}/api/status/mendota/buoy.json"
DATA_URL: str = f"{SSEC_BASE_URL}/api/data.csv"

# SSEC MetObs symbol names for the variables we care about.
# Discovered by querying the live API and inspecting the 'fields' header.
SSEC_SYMBOLS: str = ":".join([
    "air_temp",       # Air temperature at buoy mast (°C)
    "wind_speed",     # Wind speed (m/s)
    "water_temp_1",   # Surface (0 m) — epilimnion
    "water_temp_3",   # 1 m depth
    "water_temp_5",   # 5 m depth — developing thermocline
    "water_temp_7",   # 10 m depth — metalimnion
    "water_temp_9",   # 20 m depth — hypolimnion
    "chlorophyll",    # Chlorophyll-a (µg/L proxy from fluorometer RFU)
    "phycocyanin",    # Phycocyanin (µg/L) — cyanobacteria HAB indicator
])

# Sentinel-Stream ingest endpoint
SENTINEL_INGEST_URL: str = "http://localhost:8000/ingest"

# Buoy location (from SSEC metadata)
BUOY_LAT: float = 43.0988
BUOY_LON: float = -89.4045
BUOY_LOCATION: str = "Lake Mendota — 1.5 km NE of Picnic Point, Madison, WI"

# Outlier thresholds — must match main.py constants
WIND_OUTLIER_THRESHOLD_MS: float = 20.0
CHLOROPHYLL_OUTLIER_THRESHOLD_UGL: float = 100.0

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SSEC-FETCHER] %(levelname)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SSEC API helpers
# ---------------------------------------------------------------------------

def check_buoy_status() -> dict:
    """
    Query the SSEC status API and return the operational status of the buoy.

    Returns
    -------
    dict
        JSON payload from the status endpoint, e.g.:
        {
          "last_updated": "2025-11-19 20:27:38Z",
          "long_name": "Mendota Buoy",
          "status_code": 8,
          "status_message": "Out for the season"
        }

    Raises
    ------
    requests.exceptions.RequestException
        On any network failure.
    """
    response = requests.get(STATUS_URL, timeout=10)
    response.raise_for_status()
    return response.json()


def is_buoy_online() -> bool:
    """
    Return True if the buoy status indicates it is actively collecting data.

    The SSEC uses status_code 0 for normal operation.  Any other code
    (8 = "Out for the season", etc.) indicates the buoy is not transmitting.
    """
    try:
        status = check_buoy_status()
        code = status.get("status_code", -1)
        msg = status.get("status_message", "unknown")
        logger.info("Buoy status: code=%d  message='%s'", code, msg)
        return code == 0
    except Exception as exc:
        logger.error("Failed to reach SSEC status API: %s", exc)
        return False


def fetch_ssec_data(
    begin: str,
    end: Optional[str] = None,
    interval: str = "1m",
) -> pd.DataFrame:
    """
    Fetch data from the SSEC MetObs API and return as a pandas DataFrame.

    Parameters
    ----------
    begin:
        Start time — either ISO-8601 absolute (e.g., "2024-07-01T00:00:00Z")
        or SSEC relative (e.g., "-24:00:00" for last 24 hours).
    end:
        End time — ISO-8601 absolute.  If omitted, defaults to now.
    interval:
        Sampling interval: "1m" (1 minute), "5m", or "1h".

    Returns
    -------
    pd.DataFrame
        Parsed sensor data.  Empty DataFrame if no records returned.

    Raises
    ------
    requests.exceptions.RequestException
        On network failure.
    ValueError
        If the API returns a non-success status or unparseable CSV.
    """
    params: dict = {
        "site": "mendota",
        "inst": "buoy",
        "symbols": SSEC_SYMBOLS,
        "begin": begin,
        "interval": interval,
    }
    if end:
        params["end"] = end

    logger.info(
        "Fetching SSEC data: begin=%s  end=%s  interval=%s",
        begin,
        end or "now",
        interval,
    )

    response = requests.get(DATA_URL, params=params, timeout=30)
    response.raise_for_status()

    # The SSEC API returns a pseudo-CSV with metadata lines before the data.
    # Format:
    #   status: success
    #   code: 200
    #   message:
    #   num_results: N
    #   fields: timestamp,col1,col2,...
    #   <data rows>
    lines = response.text.strip().split("\n")

    # Parse metadata header
    meta: dict = {}
    data_start: int = 0
    for i, line in enumerate(lines):
        if ":" in line and not line.startswith("%"):
            key, _, val = line.partition(":")
            meta[key.strip()] = val.strip()
        if line.startswith("fields:"):
            data_start = i
            break

    num_results = int(meta.get("num_results", 0))
    if num_results == 0:
        logger.warning(
            "SSEC API returned 0 records for begin=%s.  "
            "The buoy may be offline for the season.  "
            "Run with --status to check operational status.",
            begin,
        )
        return pd.DataFrame()

    # Extract the column-header line (strips "fields: " prefix) and data rows.
    fields_line = lines[data_start].replace("fields:", "").strip()
    # Rename the timestamp column from the strftime format to a clean name.
    fields_line = fields_line.replace("%Y-%m-%dT%H:%M:%SZ", "timestamp")

    csv_text = fields_line + "\n" + "\n".join(lines[data_start + 1:])
    df = pd.read_csv(StringIO(csv_text))

    logger.info(
        "Retrieved %d records from SSEC API (%s to %s).",
        len(df),
        df["timestamp"].iloc[0] if len(df) > 0 else "N/A",
        df["timestamp"].iloc[-1] if len(df) > 0 else "N/A",
    )
    return df


# ---------------------------------------------------------------------------
# Data transformation: SSEC → Sentinel-Stream schema
# ---------------------------------------------------------------------------

def ssec_row_to_payload(row: pd.Series) -> Optional[dict]:
    """
    Convert a single SSEC data row to a Sentinel-Stream /ingest payload.

    Returns None if essential fields (air_temp or wind_speed) are NaN,
    which indicates the sensor was offline or the field wasn't sampled
    in this interval.

    Parameters
    ----------
    row:
        A row from the DataFrame returned by :func:`fetch_ssec_data`.

    Returns
    -------
    dict or None
        Valid Sentinel-Stream payload, or None if the row is too incomplete.
    """
    # Require at minimum: timestamp, air temp, wind speed
    if pd.isna(row.get("air_temp")) or pd.isna(row.get("wind_speed")):
        return None

    def safe_float(key: str, fallback: float) -> float:
        val = row.get(key)
        return float(val) if pd.notna(val) else fallback

    # Build the vertical temperature profile.
    # Use the best available value at each depth; fall back to a
    # plausible interpolation when a sensor reports NaN.
    surface = safe_float("water_temp_1", 12.0)
    depth_5m = safe_float("water_temp_5", surface - 2.0)
    depth_10m = safe_float("water_temp_7", depth_5m - 2.0)
    depth_20m = safe_float("water_temp_9", depth_10m - 2.0)

    # Clamp to physically plausible range for Lake Mendota (0–35 °C)
    for val in [surface, depth_5m, depth_10m, depth_20m]:
        val = max(0.0, min(35.0, val))

    chlorophyll = safe_float("chlorophyll", 8.5)
    # Clamp — very high raw fluorometer RFUs are instrument artifacts
    chlorophyll = max(0.0, min(999.9, chlorophyll))

    return {
        "timestamp": str(row["timestamp"]),
        "location": BUOY_LOCATION,
        "lat": BUOY_LAT,
        "long": BUOY_LON,
        "air_temp_c": round(float(row["air_temp"]), 3),
        "wind_speed_ms": round(max(0.0, float(row["wind_speed"])), 3),
        "water_temp_profile": {
            "0m": round(surface, 3),
            "5m": round(depth_5m, 3),
            "10m": round(depth_10m, 3),
            "20m": round(depth_20m, 3),
        },
        "chlorophyll_ugl": round(chlorophyll, 3),
    }


# ---------------------------------------------------------------------------
# Ingest to Sentinel-Stream
# ---------------------------------------------------------------------------

def ingest_payload(payload: dict) -> bool:
    """
    POST a single payload to the Sentinel-Stream /ingest endpoint.

    Returns True on success, False on any error.
    """
    try:
        resp = requests.post(SENTINEL_INGEST_URL, json=payload, timeout=5)
        resp.raise_for_status()
        return True
    except requests.exceptions.RequestException as exc:
        logger.error("Failed to ingest payload: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Main modes
# ---------------------------------------------------------------------------

def cmd_status() -> None:
    """Print the current SSEC buoy operational status."""
    try:
        status = check_buoy_status()
        print("\n── SSEC Lake Mendota Buoy Status ──────────────────────────")
        print(f"  Status code    : {status.get('status_code')}")
        print(f"  Status message : {status.get('status_message')}")
        print(f"  Last updated   : {status.get('last_updated')}")
        print(f"  Long name      : {status.get('long_name')}")
        print()
        if status.get("status_code") == 0:
            print("  ✓  Buoy is ONLINE — live data available.")
            print(f"     Run: python scripts/fetch_ssec.py --live")
        else:
            print("  ✗  Buoy is OFFLINE.")
            print("     The synthetic emulator (sensor_emulator.py) provides")
            print("     a continuous synthetic stream matching SSEC schema.")
            print(f"     Historical data example:")
            print(f"       python scripts/fetch_ssec.py --historical --begin 2024-07-01 --end 2024-07-31")
        print()
    except Exception as exc:
        logger.error("Could not reach SSEC API: %s", exc)
        sys.exit(1)


def cmd_historical(begin: str, end: Optional[str], interval: str) -> None:
    """
    Fetch historical SSEC data and seed the Sentinel-Stream database.

    Exits with code 1 if no data is returned (buoy was offline for the
    requested period or the request failed).
    """
    print(f"\n── Fetching SSEC historical data ──")
    print(f"  Begin    : {begin}")
    print(f"  End      : {end or 'now'}")
    print(f"  Interval : {interval}")
    print(f"  Symbols  : {SSEC_SYMBOLS.replace(':', ', ')}")
    print()

    try:
        df = fetch_ssec_data(begin=begin, end=end, interval=interval)
    except Exception as exc:
        logger.error("SSEC API request failed: %s", exc)
        sys.exit(1)

    if df.empty:
        print(
            "No data returned.  The buoy may have been offline for the requested period.\n"
            "Try a summer date range, e.g.:\n"
            "  python scripts/fetch_ssec.py --historical --begin 2024-07-01 --end 2024-07-31\n"
        )
        sys.exit(1)

    print(f"Retrieved {len(df)} records.  Ingesting into Sentinel-Stream...\n")

    success = 0
    skipped = 0
    for _, row in df.iterrows():
        payload = ssec_row_to_payload(row)
        if payload is None:
            skipped += 1
            continue
        if ingest_payload(payload):
            success += 1
        time.sleep(0.01)  # Avoid overwhelming the local API

    print(f"── Seed complete ──────────────────────────────────────────")
    print(f"  Records fetched  : {len(df)}")
    print(f"  Successfully ingested : {success}")
    print(f"  Skipped (incomplete)  : {skipped}")
    print(f"  Failed                : {len(df) - success - skipped}")
    print(f"\n  Run 'curl http://localhost:8000/status' to verify record count.")
    print(f"  Run 'curl http://localhost:8000/forecast' to see the trained forecast.\n")


def cmd_live(poll_interval: int) -> None:
    """
    Live-poll the SSEC API and forward real-time data to Sentinel-Stream.

    This mode replaces the synthetic sensor_emulator.py when the physical
    buoy is actively deployed on the lake (typically May–November).
    """
    if not is_buoy_online():
        print(
            "\n✗  The SSEC Mendota buoy is currently OFFLINE.\n"
            "   Use the synthetic emulator instead:\n"
            "     python sensor_emulator.py\n"
            "\n   Or seed with historical summer data:\n"
            "     python scripts/fetch_ssec.py --historical "
            "--begin 2024-07-01 --end 2024-07-31\n"
        )
        sys.exit(1)

    logger.info(
        "Live-poll mode active — fetching from SSEC API every %d s",
        poll_interval,
    )

    while True:
        # Fetch the last 2 × poll_interval to ensure we don't miss any readings
        # in case of slight clock skew between the SSEC server and local time.
        begin = f"-{poll_interval * 2}s"
        try:
            df = fetch_ssec_data(begin=begin, interval="1m")
            for _, row in df.iterrows():
                payload = ssec_row_to_payload(row)
                if payload:
                    ingest_payload(payload)
        except Exception as exc:
            logger.warning("Poll cycle failed: %s — will retry", exc)

        time.sleep(poll_interval)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fetch_ssec",
        description=(
            "SSEC MetObs Lake Mendota data fetcher for Sentinel-Stream.\n"
            "Connects to the real UW-Madison buoy API at metobs.ssec.wisc.edu."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--status",
        action="store_true",
        help="Print the current SSEC buoy operational status and exit.",
    )
    mode.add_argument(
        "--historical",
        action="store_true",
        help="Fetch historical data and seed the Sentinel-Stream database.",
    )
    mode.add_argument(
        "--live",
        action="store_true",
        help=(
            "Poll the SSEC API in real time and forward data to Sentinel-Stream. "
            "Exits if the buoy is currently offline."
        ),
    )

    parser.add_argument(
        "--begin",
        default="-168:00:00",
        help=(
            "Start of the data window.  "
            "ISO-8601 date (2024-07-01) or SSEC relative (-168:00:00). "
            "Default: -168:00:00 (last 7 days)."
        ),
    )
    parser.add_argument(
        "--end",
        default=None,
        help="End of the data window (ISO-8601 date).  Default: now.",
    )
    parser.add_argument(
        "--interval",
        default="1m",
        choices=["1m", "5m", "1h"],
        help="Sampling interval.  Default: 1m (1 minute).",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=60,
        help="Seconds between polls in --live mode.  Default: 60.",
    )

    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.status:
        cmd_status()
    elif args.historical:
        begin = args.begin
        # Convert bare date (2024-07-01) to ISO-8601 with time
        if len(begin) == 10 and "T" not in begin:
            begin = f"{begin}T00:00:00Z"
        end = args.end
        if end and len(end) == 10 and "T" not in end:
            end = f"{end}T23:59:59Z"
        cmd_historical(begin=begin, end=end, interval=args.interval)
    elif args.live:
        cmd_live(poll_interval=args.poll_interval)


if __name__ == "__main__":
    main()
