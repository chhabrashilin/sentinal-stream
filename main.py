"""
main.py — Sentinel-Stream: Mendota Edition — FastAPI Microservice

Real-time environmental intelligence pipeline for Lake Mendota, Madison, WI.
Ingests multivariate telemetry from the NTL-LTER buoy (mirrored by the
emulator while the physical buoy is off-station for the season), applies
outlier-aware noise filtering, and serves ML-powered 5-minute surface water
temperature forecasts.

Architecture overview
---------------------
  POST /ingest    ← buoy packets arrive at 1 Hz
      │
      ├─ Pydantic validation   (physical-plausibility constraints per field)
      ├─ Outlier detection     (wind > 20 m/s OR chlorophyll > 100 µg/L)
      ├─ Rolling-window smooth (last 10 *clean* wind_speed_ms readings)
      └─ SQLite persistence    (raw + smoothed wind, water temp profile,
                                chlorophyll, outlier flag)

  GET /forecast   ← queried by operators and autonomous decision systems
      │
      └─ Linear regression on last 100 clean records
         predicts surface water temperature (0m) 5 minutes ahead.
         Returns trend direction and R² confidence score.

  GET /status     ← health probe (Docker healthcheck target)
  GET /readings   ← recent record retrieval for dashboards / debugging

Design decisions are documented inline and in README.md.
"""

from __future__ import annotations

import logging
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Deque, Optional

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator
from sklearn.linear_model import LinearRegression
from sqlalchemy import (
    Boolean, Column, Float, Integer, String,
    create_engine, func,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [sentinel-stream-mendota] %(levelname)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database setup — SQLAlchemy 2.0 style
# ---------------------------------------------------------------------------

# SQLite is deliberately chosen for this edge-compute context: zero
# configuration, no separate daemon, single-file portability, and sufficient
# throughput for 1 Hz sensor data.  A production deployment (e.g., a shore
# station collecting from multiple lake buoys) would swap this URL for
# TimescaleDB or InfluxDB behind the same API contract.
DATABASE_URL: str = "sqlite:///./mendota_buoy.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # required for SQLite + FastAPI
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 declarative base."""
    pass


# ---------------------------------------------------------------------------
# ORM model
# ---------------------------------------------------------------------------

class BuoyReading(Base):
    """
    Persisted buoy telemetry record — Lake Mendota NTL-LTER digital twin.

    Water temperature is stored as four separate columns (one per depth)
    rather than a JSON blob so that SQL queries can filter and aggregate
    on individual depths without full-row deserialization — important when
    analysing thermal stratification across thousands of records.

    Both raw and smoothed wind values are stored so analysts can always
    reconstruct the original signal and audit the smoothing behaviour.
    The is_outlier flag partitions clean data from anomalous events for
    post-incident forensic analysis (e.g., tracing a false HAB alert).
    """

    __tablename__ = "buoy_readings"

    id: int = Column(Integer, primary_key=True, index=True)
    timestamp: str = Column(String, nullable=False, index=True)
    location: str = Column(String, nullable=True)
    lat: float = Column(Float, nullable=False)
    long: float = Column(Float, nullable=False)

    # Atmospheric measurements
    air_temp_c: float = Column(Float, nullable=False)
    raw_wind_speed_ms: float = Column(Float, nullable=False)
    wind_speed_ms_smoothed: float = Column(Float, nullable=False)

    # Sub-surface temperature profile — NTL-LTER sensor chain depths
    water_temp_0m: float = Column(Float, nullable=False)   # epilimnion
    water_temp_5m: float = Column(Float, nullable=False)   # developing thermocline
    water_temp_10m: float = Column(Float, nullable=False)  # metalimnion
    water_temp_20m: float = Column(Float, nullable=False)  # hypolimnion

    # Biological / chemical
    # Chlorophyll-a is the primary proxy for algal biomass and HAB risk.
    chlorophyll_ugl: float = Column(Float, nullable=False)

    # Outlier flag: True when any field exceeds physical plausibility bounds.
    # Records are stored (not discarded) to preserve the full audit trail.
    is_outlier: bool = Column(Boolean, nullable=False, default=False)


# ---------------------------------------------------------------------------
# Smoothing buffer — process-lifetime rolling window for wind
# ---------------------------------------------------------------------------

# Wind outlier threshold for Lake Mendota.  20 m/s is a violent storm on an
# inland lake (Beaufort force 9) — implausible under normal conditions and
# likely indicates anemometer saturation or mechanical fault.
WIND_OUTLIER_THRESHOLD_MS: float = 20.0

# Chlorophyll outlier threshold.  Values above 100 µg/L are outside the
# plausible range for Lake Mendota and likely indicate fluorometer lens
# fouling rather than a genuine harmful algal bloom.
CHLOROPHYLL_OUTLIER_THRESHOLD_UGL: float = 100.0

# Rolling window length: 10 samples at 1 Hz = 10-second smoothing window.
# Short enough to track real wind shifts on the lake; long enough to suppress
# instrument noise from the cup anemometer on the buoy mast.
WINDOW_SIZE: int = 10

# In-memory deque for outlier-filtered wind readings.  Process-memory rather
# than per-request DB query keeps ingest latency constant at high throughput.
rolling_buffer: Deque[float] = deque(maxlen=WINDOW_SIZE)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class WaterTempProfile(BaseModel):
    """
    Vertical water temperature profile from the NTL-LTER thermistor chain.

    Depth keys match the NTL-LTER buoy sensor chain deployment depths for
    Lake Mendota.  Each value is the temperature in degrees Celsius at that
    depth below the surface.
    """

    field_0m: float = Field(..., alias="0m", ge=0.0, le=35.0,
                            description="Surface (epilimnion) temperature °C.")
    field_5m: float = Field(..., alias="5m", ge=0.0, le=35.0,
                            description="5 m depth temperature °C.")
    field_10m: float = Field(..., alias="10m", ge=0.0, le=35.0,
                             description="10 m depth temperature °C.")
    field_20m: float = Field(..., alias="20m", ge=0.0, le=35.0,
                             description="20 m depth (hypolimnion) temperature °C.")

    model_config = {"populate_by_name": True}


class SensorReading(BaseModel):
    """
    Validated inbound telemetry payload from the Lake Mendota buoy.

    Field ranges encode physical plausibility constraints for the Lake Mendota
    site.  Values outside these bounds indicate a sensor fault or malformed
    packet and are rejected before touching the database.
    """

    timestamp: str = Field(
        ...,
        description="ISO-8601 UTC timestamp of the reading.",
        examples=["2026-03-22T20:27:00Z"],
    )
    location: Optional[str] = Field(
        default=None,
        description="Human-readable buoy location label.",
    )
    lat: float = Field(
        ..., ge=42.9, le=43.2,
        description="Buoy latitude in decimal degrees (Lake Mendota range).",
    )
    long: float = Field(
        ..., ge=-89.6, le=-89.3,
        description="Buoy longitude in decimal degrees (Lake Mendota range).",
    )
    air_temp_c: float = Field(
        ..., ge=-40.0, le=50.0,
        description="Air temperature at buoy mast height, degrees Celsius.",
    )
    wind_speed_ms: float = Field(
        ..., ge=0.0, le=60.0,
        description=(
            "Wind speed in metres per second.  Values > 20 m/s are flagged "
            "as outliers but stored for audit."
        ),
    )
    water_temp_profile: WaterTempProfile = Field(
        ...,
        description="Vertical water temperature profile from the thermistor chain.",
    )
    chlorophyll_ugl: float = Field(
        ..., ge=0.0, le=1000.0,
        description=(
            "Chlorophyll-a concentration in µg/L.  Values > 100 µg/L are "
            "flagged as outliers (probable fluorometer fouling)."
        ),
    )

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_nonempty(cls, v: str) -> str:
        """Reject blank timestamp strings before they reach the database."""
        if not v.strip():
            raise ValueError("timestamp must not be empty")
        return v


class IngestResponse(BaseModel):
    """Response body returned by POST /ingest."""

    status: str
    smoothed_wind_ms: float = Field(
        description="10-point rolling-average wind speed (m/s), outliers excluded."
    )
    is_outlier: bool = Field(
        description="True if wind or chlorophyll exceeded the outlier threshold."
    )
    surface_water_temp_c: float = Field(
        description="Ingested surface (0m) water temperature (°C)."
    )


class ForecastResponse(BaseModel):
    """Response body returned by GET /forecast."""

    current_surface_temp_c: float = Field(
        description="Most recent surface (0m) water temperature (°C)."
    )
    forecast_5min_surface_temp_c: float = Field(
        description="Predicted surface water temperature 5 minutes from now (°C)."
    )
    trend: str = Field(
        description="One of 'rising', 'falling', or 'stable' (±0.1 °C dead-band)."
    )
    r_squared: float = Field(
        description="Linear regression R² score — model confidence [0, 1]."
    )
    records_used: int = Field(
        description="Number of clean (non-outlier) records used to fit the model."
    )


class StatusResponse(BaseModel):
    """Response body returned by GET /status."""

    status: str
    record_count: int
    latest_reading: Optional[dict[str, Any]]
    system: str


class ReadingsResponse(BaseModel):
    """Response body returned by GET /readings."""

    count: int
    readings: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Dependency injection — database session
# ---------------------------------------------------------------------------

def get_db() -> Any:
    """
    FastAPI dependency that provides a SQLAlchemy 2.0 session.

    The context-manager pattern guarantees the session is closed (and any
    open transaction rolled back on error) even when an exception propagates
    through the endpoint handler.

    Yields
    ------
    Session
        An active database session bound to the request lifecycle.
    """
    with SessionLocal() as db:
        yield db


# ---------------------------------------------------------------------------
# Lifespan context manager
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan handler (replaces deprecated @app.on_event decorators).

    Startup: creates DB tables if absent, then seeds the rolling wind buffer
    from the most recent records so that a process restart doesn't reset
    smoothing state — important for maintaining data continuity during
    routine service restarts on the shore-side server.

    Shutdown: logs a clean shutdown message.
    """
    logger.info("Sentinel-Stream Mendota API starting up — creating database schema.")
    Base.metadata.create_all(bind=engine)

    # Seed the rolling buffer from the last WINDOW_SIZE clean records so that
    # a service restart preserves recent smoothing context rather than starting
    # cold and producing artificially low averages on the first few packets.
    with SessionLocal() as db:
        recent = (
            db.query(BuoyReading)
            .filter(BuoyReading.is_outlier == False)  # noqa: E712
            .order_by(BuoyReading.id.desc())
            .limit(WINDOW_SIZE)
            .all()
        )
        for record in reversed(recent):
            rolling_buffer.append(record.raw_wind_speed_ms)
        logger.info(
            "Rolling buffer seeded with %d records from previous session.",
            len(rolling_buffer),
        )

    logger.info(
        "API ready — Lake Mendota NTL-LTER digital twin pipeline online. "
        "Buoy: 43.0988° N, 89.4045° W"
    )
    yield

    logger.info("Sentinel-Stream Mendota API shutting down gracefully.")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Sentinel-Stream: Mendota Edition",
    description=(
        "Real-time environmental intelligence pipeline for Lake Mendota, Madison, WI. "
        "Ingests 1 Hz NTL-LTER buoy telemetry (atmospheric + sub-surface temperature "
        "profile + chlorophyll-a), applies outlier-aware rolling-average filtering, "
        "and serves ML-powered 5-minute surface water temperature forecasts. "
        "Built as a digital twin of the UW-Madison SSEC / Center for Limnology buoy."
    ),
    version="2.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# POST /ingest
# ---------------------------------------------------------------------------

@app.post("/ingest", response_model=IngestResponse, status_code=200)
def ingest_reading(
    reading: SensorReading,
    db: Session = Depends(get_db),
) -> IngestResponse:
    """
    Ingest a validated buoy telemetry packet.

    Processing pipeline
    -------------------
    1. Pydantic has already validated field types and physical plausibility.
    2. Detect outliers: wind > 20 m/s OR chlorophyll > 100 µg/L.
       Both are flagged with the same is_outlier sentinel so downstream
       consumers apply a single filter regardless of which variable caused it.
    3. Update the rolling wind buffer **only** with non-outlier readings.
       This prevents a fouled fluorometer or anemometer fault from corrupting
       10 subsequent smoothed wind values — a real concern on Lake Mendota
       where biofilm accumulation on sensor optics is seasonally common.
    4. Persist the full record including raw wind, smoothed wind, all four
       water depth temperatures, chlorophyll, and the outlier flag.

    Parameters
    ----------
    reading:
        Validated buoy payload from the NTL-LTER emulator.
    db:
        Injected SQLAlchemy session.

    Returns
    -------
    IngestResponse
        Confirmation with smoothed wind speed, outlier flag, and surface temp.
    """
    # An outlier is any reading where either the anemometer or the fluorometer
    # is reporting a physically implausible value.
    wind_outlier: bool = reading.wind_speed_ms > WIND_OUTLIER_THRESHOLD_MS
    chl_outlier: bool = reading.chlorophyll_ugl > CHLOROPHYLL_OUTLIER_THRESHOLD_UGL
    is_outlier: bool = wind_outlier or chl_outlier

    if is_outlier:
        logger.warning(
            "Outlier detected (wind_outlier=%s, chl_outlier=%s) — "
            "wind=%.1f m/s, chl=%.1f µg/L — stored with is_outlier=True, "
            "excluded from smoothing buffer.",
            wind_outlier,
            chl_outlier,
            reading.wind_speed_ms,
            reading.chlorophyll_ugl,
        )
    else:
        # Only clean wind readings enter the rolling buffer.
        rolling_buffer.append(reading.wind_speed_ms)

    # Compute smoothed wind.  Fall back to raw value on cold start (empty buffer)
    # so the API always returns a numeric result from the first packet onward.
    smoothed_wind: float = (
        float(np.mean(list(rolling_buffer))) if rolling_buffer else reading.wind_speed_ms
    )

    record = BuoyReading(
        timestamp=reading.timestamp,
        location=reading.location,
        lat=reading.lat,
        long=reading.long,
        air_temp_c=reading.air_temp_c,
        raw_wind_speed_ms=reading.wind_speed_ms,
        wind_speed_ms_smoothed=round(smoothed_wind, 4),
        water_temp_0m=reading.water_temp_profile.field_0m,
        water_temp_5m=reading.water_temp_profile.field_5m,
        water_temp_10m=reading.water_temp_profile.field_10m,
        water_temp_20m=reading.water_temp_profile.field_20m,
        chlorophyll_ugl=reading.chlorophyll_ugl,
        is_outlier=is_outlier,
    )

    db.add(record)
    db.commit()

    logger.debug(
        "Ingested id=%d  air=%.2f°C  water_0m=%.2f°C  wind_raw=%.2f→smooth=%.2f  "
        "chl=%.1f µg/L  outlier=%s",
        record.id,
        record.air_temp_c,
        record.water_temp_0m,
        record.raw_wind_speed_ms,
        record.wind_speed_ms_smoothed,
        record.chlorophyll_ugl,
        record.is_outlier,
    )

    return IngestResponse(
        status="ok",
        smoothed_wind_ms=round(smoothed_wind, 4),
        is_outlier=is_outlier,
        surface_water_temp_c=record.water_temp_0m,
    )


# ---------------------------------------------------------------------------
# GET /forecast
# ---------------------------------------------------------------------------

@app.get("/forecast", response_model=ForecastResponse)
def get_forecast(db: Session = Depends(get_db)) -> ForecastResponse:
    """
    Generate a 5-minute surface water temperature forecast using linear regression.

    The model predicts surface (0m) water temperature because thermal
    stratification dynamics — the development and deepening of the thermocline
    over spring and summer — are the primary scientific focus of the NTL-LTER
    buoy deployment.  Surface temperature drives mixing energy, dissolved oxygen
    distribution, and harmful algal bloom risk, making it the highest-value
    forecast target for both scientific and operational users.

    Methodology
    -----------
    Linear regression is chosen for two reasons relevant to edge deployments:

      1. **Interpretability** — the slope coefficient directly represents the
         rate of surface warming (°C/s), which scientists and operators can
         sanity-check against known seasonal dynamics.

      2. **Compute budget** — a shore-station Raspberry Pi or equivalent SBC
         fits this model in <1 ms, leaving headroom for concurrent data logging
         and alert evaluation.

    Outlier records are excluded from the regression.  A fouled-fluorometer
    record carrying a spurious temperature reading could invert the predicted
    trend direction — a safety-critical error in HAB early-warning systems.

    Parameters
    ----------
    db:
        Injected SQLAlchemy session.

    Returns
    -------
    ForecastResponse
        Current surface temp, 5-min forecast, trend direction, and R² score.

    Raises
    ------
    HTTPException(422)
        When fewer than 10 clean records are available — the minimum for a
        statistically meaningful linear regression.
    """
    MIN_RECORDS: int = 10
    QUERY_LIMIT: int = 100
    FORECAST_HORIZON_S: float = 300.0  # 5 minutes
    STABLE_BAND_C: float = 0.1         # °C dead-band for "stable" classification

    records = (
        db.query(BuoyReading)
        .filter(BuoyReading.is_outlier == False)  # noqa: E712
        .order_by(BuoyReading.id.desc())
        .limit(QUERY_LIMIT)
        .all()
    )

    if len(records) < MIN_RECORDS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Insufficient data: {len(records)} clean records found, "
                f"minimum {MIN_RECORDS} required for a reliable surface temperature "
                "forecast.  Continue streaming sensor data and retry."
            ),
        )

    # Reverse to chronological order for time-series feature engineering.
    records = list(reversed(records))

    df = pd.DataFrame(
        {
            "timestamp": [r.timestamp for r in records],
            "water_temp_0m": [r.water_temp_0m for r in records],
        }
    )

    # Represent time as seconds relative to the first record in the window.
    # Relative time keeps X values small and avoids precision loss in regression
    # coefficients when using Unix epoch integers directly.
    df["time_s"] = pd.to_datetime(df["timestamp"], utc=True).astype("int64") // 10**9
    t0: int = int(df["time_s"].iloc[0])
    df["relative_s"] = df["time_s"] - t0

    X = df[["relative_s"]].values
    y = df["water_temp_0m"].values

    model = LinearRegression()
    model.fit(X, y)
    r_squared: float = float(model.score(X, y))

    current_temp: float = float(df["water_temp_0m"].iloc[-1])
    last_relative_s: float = float(df["relative_s"].iloc[-1])
    forecast_temp: float = float(
        model.predict(np.array([[last_relative_s + FORECAST_HORIZON_S]]))[0]
    )

    temp_delta: float = forecast_temp - current_temp
    if abs(temp_delta) <= STABLE_BAND_C:
        trend = "stable"
    elif temp_delta > 0:
        trend = "rising"
    else:
        trend = "falling"

    logger.info(
        "Forecast: current_0m=%.2f°C  forecast_0m=%.2f°C  trend=%s  "
        "R²=%.3f  records=%d",
        current_temp,
        forecast_temp,
        trend,
        r_squared,
        len(records),
    )

    return ForecastResponse(
        current_surface_temp_c=round(current_temp, 3),
        forecast_5min_surface_temp_c=round(forecast_temp, 3),
        trend=trend,
        r_squared=round(r_squared, 4),
        records_used=len(records),
    )


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------

@app.get("/status", response_model=StatusResponse)
def get_status(db: Session = Depends(get_db)) -> StatusResponse:
    """
    Health probe endpoint — the Docker healthcheck target.

    Returns HTTP 200 even on an empty database so the health check passes
    immediately after startup before the sensor emulator begins transmitting.

    Parameters
    ----------
    db:
        Injected SQLAlchemy session.

    Returns
    -------
    StatusResponse
        System health, total record count, and the most recent reading.
    """
    record_count: int = db.query(func.count(BuoyReading.id)).scalar() or 0

    latest_record = (
        db.query(BuoyReading).order_by(BuoyReading.id.desc()).first()
    )

    latest: Optional[dict[str, Any]] = None
    if latest_record is not None:
        latest = {
            "id": latest_record.id,
            "timestamp": latest_record.timestamp,
            "air_temp_c": latest_record.air_temp_c,
            "water_temp_0m": latest_record.water_temp_0m,
            "smoothed_wind_ms": latest_record.wind_speed_ms_smoothed,
            "chlorophyll_ugl": latest_record.chlorophyll_ugl,
            "is_outlier": latest_record.is_outlier,
        }

    return StatusResponse(
        status="healthy",
        record_count=record_count,
        latest_reading=latest,
        system="Sentinel-Stream Mendota v2.0.0 — Lake Mendota NTL-LTER digital twin",
    )


# ---------------------------------------------------------------------------
# GET /readings
# ---------------------------------------------------------------------------

@app.get("/readings", response_model=ReadingsResponse)
def get_readings(
    n: int = 20,
    db: Session = Depends(get_db),
) -> ReadingsResponse:
    """
    Retrieve the N most recent buoy readings (default 20).

    Useful for populating a live dashboard or debugging the sensor stream.
    Records are returned in reverse-chronological order (newest first).

    Parameters
    ----------
    n:
        Number of records to return (clamped to [1, 500]).
    db:
        Injected SQLAlchemy session.

    Returns
    -------
    ReadingsResponse
        List of recent records with all sensor fields.
    """
    n = max(1, min(n, 500))

    records = (
        db.query(BuoyReading)
        .order_by(BuoyReading.id.desc())
        .limit(n)
        .all()
    )

    readings = [
        {
            "id": r.id,
            "timestamp": r.timestamp,
            "location": r.location,
            "lat": r.lat,
            "long": r.long,
            "air_temp_c": r.air_temp_c,
            "raw_wind_speed_ms": r.raw_wind_speed_ms,
            "wind_speed_ms_smoothed": r.wind_speed_ms_smoothed,
            "water_temp_profile": {
                "0m": r.water_temp_0m,
                "5m": r.water_temp_5m,
                "10m": r.water_temp_10m,
                "20m": r.water_temp_20m,
            },
            "chlorophyll_ugl": r.chlorophyll_ugl,
            "is_outlier": r.is_outlier,
        }
        for r in records
    ]

    return ReadingsResponse(count=len(readings), readings=readings)
