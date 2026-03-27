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
REGISTER_ENDPOINT: str = f"{API_URL}/nodes/register"

# Node identity — overridden per-container in Docker Compose for the sensor swarm.
# Each node can be placed at a distinct lake position to simulate 3D spatial coverage.
NODE_ID: str = os.environ.get("NODE_ID", "node-center")

# Lake Mendota NTL-LTER buoy position — 1.5 km NE of Picnic Point, Madison, WI.
# Individual node positions are offset from center to simulate spatial distribution.
BUOY_LAT: float = float(os.environ.get("NODE_LAT", "43.0988"))
BUOY_LON: float = float(os.environ.get("NODE_LON", "-89.4045"))
BUOY_LOCATION: str = os.environ.get(
    "NODE_LOCATION",
    "Lake Mendota, 1.5 km NE of Picnic Point, Madison, WI",
)

# ---------------------------------------------------------------------------
# Environmental baselines — late March (post ice-out) for Lake Mendota
#
# Calibrated to match observed SSEC buoy data for this time of year.
# Lake Mendota typically loses ice cover in mid-to-late March (ice-off date
# varies: 1855–present record kept by UW-Madison Limnology).  Immediately
# after ice-out the water column is nearly isothermal at ~4 °C — the
# temperature of maximum density — because winter mixing has erased all
# stratification.  Surface warming and stratification onset begins in April.
#
# Key distinction from summer values:
#   Summer (Jul):  surface ~24 °C, 20m ~7 °C, Δt ≈ 17 °C (strongly stratified)
#   Now (Mar):     surface ~4 °C,  20m ~3.5 °C, Δt ≈ 0.5 °C (fully mixed)
# ---------------------------------------------------------------------------

# Air temperature: Madison, WI late March average 5–8 °C; cool post-ice baseline.
BASE_AIR_TEMP_C: float = 6.0

# Wind: Lake Mendota is exposed to prevailing SW winds; moderate spring gusts.
BASE_WIND_MS: float = 6.0

# Water temperature vertical profile — post ice-out, nearly isothermal.
# The full water column sits near 4 °C (temperature of maximum density).
# /stratification endpoint will correctly classify this as "mixed".
BASE_WATER_TEMP: dict[str, float] = {
    "0m":  4.0,   # surface — just above freezing, ice-out conditions
    "5m":  3.8,   # slight cooling with depth (inverse stratification resolving)
    "10m": 3.6,   # nearly isothermal through metalimnion
    "20m": 3.4,   # hypolimnion — coldest layer during spring turnover
}

# Chlorophyll-a: late-winter/early-spring low.  Post ice-out phytoplankton
# bloom has not yet started; diatom communities are beginning to establish.
# Units: µg/L (micrograms per litre).  NTL-LTER observed range Mar: 2–12 µg/L.
#
# NOTE: The SSEC fluorometer reports raw Relative Fluorescence Units (RFU)
# which can read 5000–15000 RFU — these are NOT µg/L.  The conversion factor
# is instrument-specific (typically ~1 RFU ≈ 0.001–0.003 µg/L for the
# Turner Cyclops sensor used on the Mendota buoy).  This pipeline stores
# the calibrated µg/L value.
BASE_CHLOROPHYLL_UGL: float = 6.5

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

    A diurnal heating cycle is applied to the surface (0m) layer only.
    In late March (post ice-out), the water column is nearly isothermal and
    the thermocline has not yet formed, so diurnal solar heating amplitude is
    small (~0.3 °C) compared to summer (~1.5 °C).  As the season progresses
    into April–May the surface will warm faster than depth, establishing the
    pycnocline and increasing the diurnal amplitude.  The /stratification
    endpoint will reflect this: currently returning "mixed", transitioning to
    "weakly_stratified" as spring progresses.

    Parameters
    ----------
    sequence:
        Monotonically increasing packet counter used as a time proxy (1 Hz).

    Returns
    -------
    dict[str, float]
        Water temperature (°C) keyed by depth string: "0m", "5m", "10m", "20m".
    """
    # Post ice-out surface diurnal amplitude: ±0.3 °C over 86 400 s (24 h).
    # In late March the water column is nearly isothermal — the full thermal
    # mass distributes solar heating rapidly, so the epilimnion barely warms
    # above the rest of the column.  Summer amplitude (~1.5 °C) is much larger
    # because the established thermocline traps shortwave energy in the
    # epilimnion, preventing it from mixing downward.
    surface_diurnal: float = 0.3 * np.sin(2 * np.pi * sequence / 86_400)

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

    # Diurnal air temperature cycle: ±4 °C over 24 hours.
    # Late March in Madison: cold nights (~2 °C) warming to ~10 °C midday.
    diurnal_air: float = 4.0 * np.sin(2 * np.pi * sequence / 86_400)
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
        "node_id": NODE_ID,
    }


# ---------------------------------------------------------------------------
# Node registration
# ---------------------------------------------------------------------------

def register_node() -> bool:
    """
    Self-register this edge node with the Sentinel-Stream API on startup.

    Registers node_id, position, and location label so the swarm dashboard
    can display the full topology.  Returns True on success, False on failure
    (non-fatal — the node continues streaming regardless).
    """
    try:
        resp = requests.post(
            REGISTER_ENDPOINT,
            json={
                "node_id":  NODE_ID,
                "lat":      BUOY_LAT,
                "long":     BUOY_LON,
                "location": BUOY_LOCATION,
            },
            timeout=5.0,
        )
        resp.raise_for_status()
        logger.info("Node '%s' registered with API at (%.4f, %.4f).", NODE_ID, BUOY_LAT, BUOY_LON)
        return True
    except Exception as exc:
        logger.warning("Could not register node '%s': %s — continuing without registration.", NODE_ID, exc)
        return False


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
        "node=%s  position: %.4f° N, %.4f° W",
        NODE_ID,
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

    register_node()

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
