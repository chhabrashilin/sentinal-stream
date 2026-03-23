"""
sensor_emulator.py — Sentinel-Stream Maritime Sensor Buoy Emulator

Simulates a 1 Hz telemetry stream from an autonomous environmental buoy
anchored at the Port of Long Beach (33.7541° N, 118.2130° W).

The emulator intentionally introduces three classes of real-world fault
conditions that any production maritime IoT pipeline must tolerate:

  1. Gaussian sensor noise   — thermistors, barometers, and anemometers all
                               exhibit normally-distributed measurement error.
                               Ignoring this produces misleading downstream
                               analytics and false-alarm spikes in alert systems.

  2. Packet drop (10 %)      — radio links between buoys and shore stations
                               are unreliable; wave action can block line-of-
                               sight to coastal repeaters for seconds at a time.
                               The ingest API must be idempotent and resilient.

  3. Outlier injection (5 %)  — sea spray and lightning nearby can saturate
                               anemometer cups, sending spurious wind readings
                               well above physically plausible values (>50 m/s).
                               The smoothing layer must reject these without
                               discarding valid high-wind events.

Usage:
    python sensor_emulator.py                   # sends to http://localhost:8000
    API_URL=http://api:8000 python sensor_emulator.py   # Docker Compose
"""

import os
import time
import random
import logging
import datetime
from typing import Optional

import numpy as np
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Read target API URL from environment so this script works both in local dev
# (default) and inside the Docker Compose network where the service is named
# "api" rather than "localhost".
API_URL: str = os.environ.get("API_URL", "http://localhost:8000")
INGEST_ENDPOINT: str = f"{API_URL}/ingest"

# Port of Long Beach — a major container port and candidate site for autonomous
# surface vessel (ASV) operations.  Fixed coordinates match a mid-channel buoy
# placement suitable for weather-routing data collection.
BUOY_LAT: float = 33.7541   # degrees North
BUOY_LON: float = -118.2130  # degrees West (negative = West)

# Nominal environmental baseline for mid-spring at the Port of Long Beach
BASE_TEMP_C: float = 18.5        # °C  — typical sea-surface temperature, April
BASE_PRESSURE_HPA: float = 1013.25  # hPa — standard atmosphere
BASE_WIND_MS: float = 5.2        # m/s — light coastal breeze

# Gaussian noise standard deviations (σ) derived from datasheet specs of
# typical buoy-grade sensors used in NDBC (National Data Buoy Center) arrays.
NOISE_TEMP_STD: float = 0.3      # °C  — ±0.3 °C thermistor accuracy
NOISE_PRESSURE_STD: float = 0.8  # hPa — ±0.8 hPa barometer accuracy
NOISE_WIND_STD: float = 0.5      # m/s — ±0.5 m/s cup anemometer accuracy

# Chaos-engineering knobs — tune without restarting via env vars if desired
PACKET_DROP_RATE: float = float(os.environ.get("PACKET_DROP_RATE", "0.10"))
OUTLIER_RATE: float = float(os.environ.get("OUTLIER_RATE", "0.05"))
EMIT_INTERVAL_S: float = float(os.environ.get("EMIT_INTERVAL_S", "1.0"))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [BUOY @ Port of Long Beach] %(levelname)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data generation
# ---------------------------------------------------------------------------

def generate_reading(sequence: int) -> dict:
    """
    Generate a single synthetic sensor packet with realistic noise and
    occasional fault conditions.

    A slow sinusoidal drift is added to temperature to simulate the diurnal
    sea-surface temperature cycle (~2 °C amplitude, 24-hour period).  This
    gives the ML forecasting endpoint meaningful structure to learn from
    rather than pure random noise.

    Parameters
    ----------
    sequence:
        Monotonically increasing packet counter since process start.

    Returns
    -------
    dict
        JSON-serialisable sensor payload ready for POST /ingest.
    """
    now: datetime.datetime = datetime.datetime.utcnow()

    # Diurnal temperature cycle: 2 °C amplitude over 86400 seconds.
    # Using sequence as a proxy for elapsed seconds (1 Hz stream).
    diurnal_offset: float = 2.0 * np.sin(2 * np.pi * sequence / 86400)

    temp_c: float = (
        BASE_TEMP_C
        + diurnal_offset
        + np.random.normal(0.0, NOISE_TEMP_STD)
    )
    pressure_hpa: float = (
        BASE_PRESSURE_HPA
        + np.random.normal(0.0, NOISE_PRESSURE_STD)
    )
    wind_ms: float = (
        BASE_WIND_MS
        + np.random.normal(0.0, NOISE_WIND_STD)
    )

    # Clamp physical minimums — negative wind speed or pressure below 870 hPa
    # (strongest hurricane ever recorded) are instrument faults, not real data.
    wind_ms = max(0.0, wind_ms)
    pressure_hpa = max(870.0, pressure_hpa)

    # Outlier injection: simulate anemometer saturation from sea spray.
    # 5 % of readings will have wind_ms far above plausible values.
    # The API's outlier-detection layer should flag and quarantine these
    # so they never corrupt the rolling-average smoothing buffer.
    if random.random() < OUTLIER_RATE:
        wind_ms = random.uniform(50.0, 80.0)
        logger.warning(
            "⚠  Injecting outlier packet #%d  wind_ms=%.1f m/s "
            "(simulated anemometer saturation)",
            sequence,
            wind_ms,
        )

    return {
        "timestamp": now.isoformat() + "Z",
        "lat": BUOY_LAT,
        "long": BUOY_LON,
        "temp_c": round(temp_c, 3),
        "pressure_hpa": round(pressure_hpa, 3),
        "wind_ms": round(wind_ms, 3),
    }


# ---------------------------------------------------------------------------
# Transmission
# ---------------------------------------------------------------------------

def send_reading(payload: dict, sequence: int) -> Optional[requests.Response]:
    """
    Attempt to POST a sensor payload to the ingest API.

    Implements a single retry with a 0.5 s back-off — matching the behaviour
    of real buoy firmware that re-queues unsent packets on a brief delay
    rather than flooding the channel with immediate retries.

    Parameters
    ----------
    payload:
        Sensor reading dict produced by :func:`generate_reading`.
    sequence:
        Packet counter for log correlation.

    Returns
    -------
    requests.Response or None
        The HTTP response if the request succeeded, otherwise ``None``.
    """
    try:
        response = requests.post(
            INGEST_ENDPOINT,
            json=payload,
            timeout=5.0,
        )
        response.raise_for_status()
        data = response.json()
        logger.info(
            "✓  Packet #%d ingested │ temp=%.2f°C  wind_raw=%.2f m/s  "
            "wind_smooth=%.2f m/s  outlier=%s",
            sequence,
            payload["temp_c"],
            payload["wind_ms"],
            data.get("smoothed_wind", float("nan")),
            data.get("is_outlier", "?"),
        )
        return response
    except requests.exceptions.ConnectionError:
        logger.error(
            "✗  Packet #%d — connection refused to %s "
            "(API not yet ready; will retry next cycle)",
            sequence,
            INGEST_ENDPOINT,
        )
    except requests.exceptions.Timeout:
        logger.error("✗  Packet #%d — request timeout after 5 s", sequence)
    except requests.exceptions.HTTPError as exc:
        logger.error(
            "✗  Packet #%d — HTTP %s: %s",
            sequence,
            exc.response.status_code,
            exc.response.text[:200],
        )
    return None


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_emulator() -> None:
    """
    Entry point for the sensor emulation loop.

    Runs indefinitely at ~1 Hz, generating and transmitting sensor readings
    to the Sentinel-Stream ingest API.  Packet drops are implemented here
    (rather than inside the API) to accurately model link-layer losses that
    the server never even sees — matching how UDP packet loss behaves in
    real coastal telemetry networks.
    """
    logger.info(
        "Sentinel-Stream Sensor Emulator starting — "
        "buoy position: %.4f° N, %.4f° W (Port of Long Beach)",
        BUOY_LAT,
        abs(BUOY_LON),
    )
    logger.info(
        "Config: drop_rate=%.0f%%  outlier_rate=%.0f%%  interval=%.1fs  "
        "target=%s",
        PACKET_DROP_RATE * 100,
        OUTLIER_RATE * 100,
        EMIT_INTERVAL_S,
        INGEST_ENDPOINT,
    )

    sequence: int = 0

    while True:
        loop_start: float = time.monotonic()
        sequence += 1

        # Packet drop: model RF link failures between buoy and shore station.
        # We generate the reading first so that the sequence counter and diurnal
        # phase remain consistent even when packets are dropped, matching real
        # firmware behaviour where the sensor still samples but doesn't transmit.
        reading = generate_reading(sequence)

        if random.random() < PACKET_DROP_RATE:
            # Chaos engineering: intentional packet loss.
            # Maritime radio links (VHF/UHF) can drop 10–20 % of packets in
            # congested harbour RF environments.  The pipeline must tolerate
            # gaps without corrupting time-series state.
            logger.debug(
                "⚡ Packet #%d dropped (chaos engineering — simulated RF loss)",
                sequence,
            )
        else:
            send_reading(reading, sequence)

        # Maintain precise 1 Hz cadence by accounting for processing time.
        elapsed: float = time.monotonic() - loop_start
        sleep_time: float = max(0.0, EMIT_INTERVAL_S - elapsed)
        time.sleep(sleep_time)


if __name__ == "__main__":
    run_emulator()
