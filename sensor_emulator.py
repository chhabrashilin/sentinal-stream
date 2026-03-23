"""
sensor_emulator.py — Sentinel-Stream: Mendota Edition

Simulates a 1 Hz telemetry stream from a research-grade environmental buoy
anchored at Lake Mendota, 1.5 km NE of Picnic Point, Madison, WI — mirroring
the North Temperate Lakes Long-Term Ecological Research (NTL-LTER) buoy
operated jointly by the UW-Madison Space Science and Engineering Center (SSEC)
and the Center for Limnology.

Because the physical SSEC buoy is currently off-station for the season, this
emulator provides a synthetic high-frequency stream to maintain data continuity
for predictive modeling and pipeline development.

The emulator models three classes of real-world fault conditions that any
production environmental IoT pipeline must tolerate:

  1. Gaussian sensor noise    — thermistors, anemometers, and fluorometers
                                exhibit normally-distributed measurement error.
                                Ignoring this produces false spikes in harmful
                                algal bloom (HAB) alert systems.

  2. Packet drop (10 %)       — Wi-Fi and LoRaWAN links between lake buoys and
                                shore stations experience interference from
                                weather and vegetation.  Gaps in the stream must
                                not corrupt time-series smoothing state.

  3. Outlier injection (5 %)  — fluorometer optics can be fouled by biofilm or
                                debris, causing spurious chlorophyll spikes well
                                above plausible bloom concentrations.  The
                                smoothing layer must quarantine these without
                                discarding legitimate HAB-level readings.

Sensor schema mirrors the NTL-LTER buoy data product:
  https://lter.limnology.wisc.edu/dataset/north-temperate-lakes-lter-high-frequency-data-meteorological-dissolved-oxygen-chlorophyll

Usage:
    python sensor_emulator.py                    # sends to http://localhost:8000
    API_URL=http://api:8000 python sensor_emulator.py    # Docker Compose
"""

import datetime
import logging
import os
import random
import time
from typing import Optional

import numpy as np
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Read target API URL from environment so this script works both in local dev
# (default) and inside the Docker Compose network where the API service is
# named "api" rather than "localhost".
API_URL: str = os.environ.get("API_URL", "http://localhost:8000")
INGEST_ENDPOINT: str = f"{API_URL}/ingest"

# Lake Mendota NTL-LTER buoy position — 1.5 km NE of Picnic Point, Madison, WI.
# Source: UW-Madison SSEC / Center for Limnology buoy metadata.
BUOY_LAT: float = 43.0988   # degrees North
BUOY_LON: float = -89.4045  # degrees West (negative = West)
BUOY_LOCATION: str = "Lake Mendota — 1.5 km NE of Picnic Point, Madison, WI"

# ---------------------------------------------------------------------------
# Environmental baselines — mid-spring (April) for Lake Mendota
# ---------------------------------------------------------------------------

# Air temperature: Madison, WI April average ~10 °C; warm-spell baseline.
BASE_AIR_TEMP_C: float = 12.0

# Wind: Lake Mendota is exposed to prevailing SW winds; moderate spring breeze.
BASE_WIND_MS: float = 5.2

# Water temperature vertical profile — spring thermal stratification begins.
# Surface warms first; hypolimnion remains near winter values (4 °C).
BASE_WATER_TEMP: dict[str, float] = {
    "0m":  14.0,   # epilimnion — warming rapidly under spring sun
    "5m":  10.5,   # thermocline developing
    "10m":  7.2,   # metalimnion
    "20m":  5.1,   # hypolimnion — near isothermal with winter turnover temp
}

# Chlorophyll-a: early spring moderate level before summer bloom season.
# Units: µg/L (micrograms per litre).  NTL-LTER typical range: 2–80 µg/L.
BASE_CHLOROPHYLL_UGL: float = 8.5

# ---------------------------------------------------------------------------
# Sensor noise standard deviations (σ)
# Derived from typical instrument specifications for buoy-grade sensors.
# ---------------------------------------------------------------------------

NOISE_AIR_TEMP_STD: float = 0.25   # °C  — thermistor accuracy ±0.2 °C
NOISE_WIND_STD: float = 0.4        # m/s — cup anemometer accuracy ±0.3 m/s
NOISE_WATER_TEMP_STD: float = 0.15 # °C  — underwater thermistor chain
NOISE_CHLOROPHYLL_STD: float = 0.8 # µg/L — fluorometer noise floor

# Outlier threshold for wind: 20 m/s on an inland lake is a violent storm.
OUTLIER_WIND_MS: float = 20.0

# Outlier threshold for chlorophyll: fluorometer saturation / lens fouling.
OUTLIER_CHLOROPHYLL_UGL: float = 100.0

# ---------------------------------------------------------------------------
# Chaos-engineering knobs — overridable via environment variables
# ---------------------------------------------------------------------------

PACKET_DROP_RATE: float = float(os.environ.get("PACKET_DROP_RATE", "0.10"))
OUTLIER_RATE: float = float(os.environ.get("OUTLIER_RATE", "0.05"))
EMIT_INTERVAL_S: float = float(os.environ.get("EMIT_INTERVAL_S", "1.0"))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [BUOY @ Lake Mendota] %(levelname)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data generation
# ---------------------------------------------------------------------------

def _water_temp_profile(sequence: int) -> dict[str, float]:
    """
    Generate a synthetic vertical water temperature profile.

    A diurnal heating cycle is applied to the surface (0m) layer only —
    the epilimnion responds to solar radiation on a daily timescale, while
    the hypolimnion (20m) is thermally isolated by the developing pycnocline.
    This models the thermal stratification dynamic that is the primary focus
    of the NTL-LTER Mendota buoy's sub-surface temperature chain.

    Parameters
    ----------
    sequence:
        Monotonically increasing packet counter used as a time proxy (1 Hz).

    Returns
    -------
    dict[str, float]
        Water temperature (°C) keyed by depth string: "0m", "5m", "10m", "20m".
    """
    # Diurnal surface warming: ±1.5 °C amplitude over 86 400 s (24 hours).
    surface_diurnal: float = 1.5 * np.sin(2 * np.pi * sequence / 86_400)

    profile: dict[str, float] = {}
    for depth, base in BASE_WATER_TEMP.items():
        # Diurnal signal attenuates with depth — surface feels full amplitude,
        # hypolimnion (20m) is essentially decoupled from daily solar forcing.
        attenuation: float = {"0m": 1.0, "5m": 0.6, "10m": 0.2, "20m": 0.0}[depth]
        temp = (
            base
            + surface_diurnal * attenuation
            + np.random.normal(0.0, NOISE_WATER_TEMP_STD)
        )
        profile[depth] = round(max(0.0, temp), 3)

    return profile


def generate_reading(sequence: int) -> dict:
    """
    Generate a single synthetic buoy telemetry packet with realistic noise
    and occasional fault conditions.

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

    # Diurnal air temperature cycle: ±3 °C over 24 hours.
    diurnal_air: float = 3.0 * np.sin(2 * np.pi * sequence / 86_400)
    air_temp_c: float = BASE_AIR_TEMP_C + diurnal_air + np.random.normal(0.0, NOISE_AIR_TEMP_STD)

    wind_speed_ms: float = max(0.0, BASE_WIND_MS + np.random.normal(0.0, NOISE_WIND_STD))

    chlorophyll_ugl: float = max(0.0, BASE_CHLOROPHYLL_UGL + np.random.normal(0.0, NOISE_CHLOROPHYLL_STD))

    # Outlier injection: simulate fluorometer lens fouling or wind sensor fault.
    # 5 % of readings carry an implausible value to exercise the API's outlier
    # detection and quarantine logic.
    if random.random() < OUTLIER_RATE:
        # Alternate between wind outlier and chlorophyll outlier to test both paths.
        if random.random() < 0.5:
            wind_speed_ms = random.uniform(25.0, 40.0)
            logger.warning(
                "⚠  Injecting wind outlier — packet #%d  wind=%.1f m/s "
                "(simulated anemometer fault on Lake Mendota)",
                sequence,
                wind_speed_ms,
            )
        else:
            chlorophyll_ugl = random.uniform(110.0, 200.0)
            logger.warning(
                "⚠  Injecting chlorophyll outlier — packet #%d  chl=%.1f µg/L "
                "(simulated fluorometer lens fouling)",
                sequence,
                chlorophyll_ugl,
            )

    return {
        "timestamp": now.isoformat() + "Z",
        "location": BUOY_LOCATION,
        "lat": BUOY_LAT,
        "long": BUOY_LON,
        "air_temp_c": round(air_temp_c, 3),
        "wind_speed_ms": round(wind_speed_ms, 3),
        "water_temp_profile": _water_temp_profile(sequence),
        "chlorophyll_ugl": round(chlorophyll_ugl, 3),
    }


# ---------------------------------------------------------------------------
# Transmission
# ---------------------------------------------------------------------------

def send_reading(payload: dict, sequence: int) -> Optional[requests.Response]:
    """
    Attempt to POST a sensor payload to the Sentinel-Stream ingest API.

    Implements a single-attempt with graceful error logging — matching the
    behaviour of real buoy firmware that logs failed transmissions to an
    on-board ring buffer for shore-side retrieval during routine servicing.

    Parameters
    ----------
    payload:
        Sensor reading dict produced by :func:`generate_reading`.
    sequence:
        Packet counter used for log correlation.

    Returns
    -------
    requests.Response or None
        The HTTP response if the request succeeded, otherwise ``None``.
    """
    try:
        response = requests.post(INGEST_ENDPOINT, json=payload, timeout=5.0)
        response.raise_for_status()
        data = response.json()
        logger.info(
            "✓  #%d ingested │ air=%.2f°C  water_0m=%.2f°C  "
            "wind_raw=%.2f→smooth=%.2f m/s  chl=%.1f µg/L  outlier=%s",
            sequence,
            payload["air_temp_c"],
            payload["water_temp_profile"]["0m"],
            payload["wind_speed_ms"],
            data.get("smoothed_wind_ms", float("nan")),
            payload["chlorophyll_ugl"],
            data.get("is_outlier", "?"),
        )
        return response
    except requests.exceptions.ConnectionError:
        logger.error(
            "✗  #%d — connection refused to %s  (API not ready; retrying next cycle)",
            sequence,
            INGEST_ENDPOINT,
        )
    except requests.exceptions.Timeout:
        logger.error("✗  #%d — request timed out after 5 s", sequence)
    except requests.exceptions.HTTPError as exc:
        logger.error(
            "✗  #%d — HTTP %s: %s",
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
    Entry point for the buoy emulation loop.

    Runs indefinitely at ~1 Hz, generating and transmitting telemetry packets
    to the Sentinel-Stream ingest API.  Packet drops are implemented here
    (not inside the API) to accurately model link-layer losses that the
    server never sees — matching LoRaWAN / Wi-Fi packet loss behaviour in
    real lake-buoy deployments.
    """
    logger.info(
        "Sentinel-Stream Mendota Emulator starting — "
        "buoy position: %.4f° N, %.4f° W",
        BUOY_LAT,
        abs(BUOY_LON),
    )
    logger.info("Location: %s", BUOY_LOCATION)
    logger.info(
        "Config: drop_rate=%.0f%%  outlier_rate=%.0f%%  interval=%.1fs  target=%s",
        PACKET_DROP_RATE * 100,
        OUTLIER_RATE * 100,
        EMIT_INTERVAL_S,
        INGEST_ENDPOINT,
    )

    sequence: int = 0

    while True:
        loop_start: float = time.monotonic()
        sequence += 1

        reading = generate_reading(sequence)

        if random.random() < PACKET_DROP_RATE:
            # Chaos engineering: intentional packet loss.
            # LoRaWAN links used by lake buoys typically achieve 90–95 % delivery
            # in clear conditions; vegetation and terrain reduce this further.
            logger.debug(
                "⚡ #%d dropped (chaos engineering — simulated RF packet loss)",
                sequence,
            )
        else:
            send_reading(reading, sequence)

        # Maintain precise 1 Hz cadence by accounting for HTTP round-trip time.
        elapsed: float = time.monotonic() - loop_start
        sleep_time: float = max(0.0, EMIT_INTERVAL_S - elapsed)
        time.sleep(sleep_time)


if __name__ == "__main__":
    run_emulator()
