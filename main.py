"""
main.py — Sentinel-Stream FastAPI Microservice

Real-time environmental data ingest, noise filtering, and ML-powered
5-minute weather forecasting for maritime operations at the
Port of Long Beach.

Architecture overview
---------------------
  POST /ingest    ← sensor packets arrive at 1 Hz
      │
      ├─ Pydantic validation (reject malformed packets early)
      ├─ Outlier detection   (wind_ms > 30 m/s flagged but still stored)
      ├─ Rolling-window smoothing (last 10 *non-outlier* readings)
      └─ SQLite persistence  (raw + smoothed values + outlier flag)

  GET /forecast   ← queried by operators / dashboards
      │
      └─ Linear regression on last 100 non-outlier records
         predicts temperature 5 minutes ahead

  GET /status     ← health probe (used by Docker healthcheck)
  GET /readings   ← recent record retrieval for UI / dashboards

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
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, create_engine, func, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [sentinel-stream] %(levelname)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database setup — SQLAlchemy 2.0 style
# ---------------------------------------------------------------------------

# SQLite is deliberately chosen for this edge-compute context: zero
# configuration, no separate daemon, single-file backup, and sufficient
# throughput for 1 Hz sensor data.  A production fleet would use
# TimescaleDB or InfluxDB behind the same API contract.
DATABASE_URL: str = "sqlite:///./weather_data.db"

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

class WeatherReading(Base):
    """
    Persisted sensor record.

    Stores both the raw sensor value and the post-smoothing value so that
    analysts can always reconstruct the original signal or audit the
    smoothing behaviour.  The ``is_outlier`` flag allows queries to easily
    partition clean data from anomalous events.
    """

    __tablename__ = "weather_readings"

    id: int = Column(Integer, primary_key=True, index=True)
    timestamp: str = Column(String, nullable=False, index=True)
    lat: float = Column(Float, nullable=False)
    long: float = Column(Float, nullable=False)
    temp_c: float = Column(Float, nullable=False)
    pressure_hpa: float = Column(Float, nullable=False)

    # Raw anemometer value — preserved even for outliers for audit purposes.
    raw_wind_ms: float = Column(Float, nullable=False)

    # Smoothed value: 10-point rolling mean computed over *non-outlier*
    # readings only.  Outlier packets do not update the rolling buffer,
    # preventing a single saturated reading from skewing 10 subsequent values.
    wind_ms_smoothed: float = Column(Float, nullable=False)

    # True when raw_wind_ms > OUTLIER_THRESHOLD.  Outlier records are stored
    # (not discarded) to enable post-incident forensic analysis.
    is_outlier: bool = Column(Boolean, nullable=False, default=False)


# ---------------------------------------------------------------------------
# Smoothing buffer — process-lifetime rolling window
# ---------------------------------------------------------------------------

# Threshold above which a wind reading is considered physically implausible
# for typical coastal/harbour conditions.  30 m/s ≈ Beaufort force 11
# (violent storm).  Readings above this are stored with is_outlier=True but
# are excluded from the rolling average so they don't corrupt downstream
# analytics.
OUTLIER_THRESHOLD_MS: float = 30.0

# Window length for the rolling average.  10 samples at 1 Hz = 10-second
# smoothing window — short enough to track real wind shifts, long enough to
# suppress sensor noise spikes.
WINDOW_SIZE: int = 10

# In-memory deque that holds the last WINDOW_SIZE *clean* (non-outlier)
# wind readings.  Lives in process memory rather than the database to avoid
# a round-trip SQL query on every ingest — critical for maintaining low
# latency at high throughput.
rolling_buffer: Deque[float] = deque(maxlen=WINDOW_SIZE)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class SensorReading(BaseModel):
    """
    Validated inbound sensor payload from the buoy.

    Field ranges encode physical plausibility constraints — values outside
    these bounds indicate a sensor fault or malformed packet and are rejected
    before touching the database.
    """

    timestamp: str = Field(
        ...,
        description="ISO-8601 UTC timestamp of the sensor reading.",
        examples=["2024-06-01T12:00:00Z"],
    )
    lat: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
        description="Buoy latitude in decimal degrees.",
    )
    long: float = Field(
        ...,
        ge=-180.0,
        le=180.0,
        description="Buoy longitude in decimal degrees.",
    )
    temp_c: float = Field(
        ...,
        ge=-40.0,
        le=60.0,
        description="Sea-surface temperature in degrees Celsius.",
    )
    pressure_hpa: float = Field(
        ...,
        ge=870.0,
        le=1084.0,
        description="Atmospheric pressure in hectopascals.",
    )
    wind_ms: float = Field(
        ...,
        ge=0.0,
        le=120.0,
        description=(
            "Wind speed in metres per second.  Values > 30 m/s are flagged "
            "as outliers but still accepted for storage."
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
    smoothed_wind: float = Field(description="10-point rolling-average wind speed (m/s).")
    is_outlier: bool = Field(description="True if raw wind_ms exceeded the outlier threshold.")


class ForecastResponse(BaseModel):
    """Response body returned by GET /forecast."""

    current_temp: float
    forecast_5min_temp: float
    trend: str = Field(description="One of 'rising', 'falling', or 'stable'.")
    r_squared: float = Field(description="Linear regression R² — model confidence [0, 1].")
    records_used: int = Field(description="Number of non-outlier records used to fit the model.")


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
    FastAPI dependency that provides a SQLAlchemy session.

    Uses the context-manager pattern introduced in SQLAlchemy 2.0 to
    guarantee the session is closed (and any transaction rolled back on
    error) even if an exception propagates through the endpoint handler.

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
    Application lifespan handler (replaces deprecated on_event decorators).

    Startup: creates database tables if they don't exist and seeds the
    rolling buffer from the most recent records so that a process restart
    doesn't reset the smoothing state to zero.

    Shutdown: logs a clean shutdown message.
    """
    # --- startup ---
    logger.info("Sentinel-Stream API starting up — creating database schema.")
    Base.metadata.create_all(bind=engine)

    # Seed the rolling buffer from the last WINDOW_SIZE non-outlier records
    # so that a service restart preserves recent smoothing context.
    with SessionLocal() as db:
        recent = (
            db.query(WeatherReading)
            .filter(WeatherReading.is_outlier == False)  # noqa: E712
            .order_by(WeatherReading.id.desc())
            .limit(WINDOW_SIZE)
            .all()
        )
        for record in reversed(recent):
            rolling_buffer.append(record.raw_wind_ms)
        logger.info(
            "Rolling buffer seeded with %d records from previous session.",
            len(rolling_buffer),
        )

    logger.info("API ready — Port of Long Beach buoy pipeline online.")
    yield

    # --- shutdown ---
    logger.info("Sentinel-Stream API shutting down gracefully.")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Sentinel-Stream",
    description=(
        "Real-time maritime environmental intelligence pipeline. "
        "Ingests 1 Hz buoy telemetry from the Port of Long Beach, "
        "applies rolling-average noise filtering, and serves ML-powered "
        "5-minute temperature forecasts."
    ),
    version="1.0.0",
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
    Ingest a validated sensor reading from the maritime buoy.

    Processing pipeline
    -------------------
    1. Pydantic has already validated field types and physical ranges.
    2. Detect outliers: wind_ms > OUTLIER_THRESHOLD_MS.
    3. Update the rolling buffer **only** with non-outlier readings.
       This prevents a single saturated anemometer reading from corrupting
       10 subsequent smoothed values — a real concern during squall events.
    4. Compute the rolling average from the buffer (or fall back to the raw
       value when the buffer has fewer than WINDOW_SIZE entries, i.e. on
       cold start).
    5. Persist the full record including both raw and smoothed wind values.

    Parameters
    ----------
    reading:
        Validated sensor payload.
    db:
        Injected SQLAlchemy session.

    Returns
    -------
    IngestResponse
        Confirmation with the current smoothed wind speed and outlier flag.
    """
    is_outlier: bool = reading.wind_ms > OUTLIER_THRESHOLD_MS

    if is_outlier:
        logger.warning(
            "Outlier detected: wind_ms=%.1f m/s (threshold %.1f m/s) — "
            "record stored with is_outlier=True, excluded from smoothing buffer.",
            reading.wind_ms,
            OUTLIER_THRESHOLD_MS,
        )
    else:
        # Only clean readings enter the rolling buffer.
        rolling_buffer.append(reading.wind_ms)

    # Compute smoothed value.  If the buffer is empty (first packet ever),
    # fall back to the raw reading so the API always returns a numeric value.
    smoothed_wind: float = (
        float(np.mean(list(rolling_buffer))) if rolling_buffer else reading.wind_ms
    )

    record = WeatherReading(
        timestamp=reading.timestamp,
        lat=reading.lat,
        long=reading.long,
        temp_c=reading.temp_c,
        pressure_hpa=reading.pressure_hpa,
        raw_wind_ms=reading.wind_ms,
        wind_ms_smoothed=round(smoothed_wind, 4),
        is_outlier=is_outlier,
    )

    db.add(record)
    db.commit()

    logger.debug(
        "Ingested id=%d  temp=%.2f°C  raw_wind=%.2f  smooth=%.2f  outlier=%s",
        record.id,
        record.temp_c,
        record.raw_wind_ms,
        record.wind_ms_smoothed,
        record.is_outlier,
    )

    return IngestResponse(
        status="ok",
        smoothed_wind=round(smoothed_wind, 4),
        is_outlier=is_outlier,
    )


# ---------------------------------------------------------------------------
# GET /forecast
# ---------------------------------------------------------------------------

@app.get("/forecast", response_model=ForecastResponse)
def get_forecast(db: Session = Depends(get_db)) -> ForecastResponse:
    """
    Generate a 5-minute temperature forecast using linear regression.

    Methodology
    -----------
    Linear regression is chosen deliberately for two reasons relevant to
    maritime edge-compute deployments:

      1. **Interpretability** — operators can inspect the slope coefficient
         to understand the rate of temperature change; no black-box opacity.
      2. **Compute budget** — a buoy processor or shore-side Raspberry Pi
         can fit this model in milliseconds, leaving headroom for other tasks.

    The model is fitted on the last 100 *non-outlier* records.  Outliers
    are excluded because corrupted readings would bias the regression line,
    potentially inverting the predicted trend direction — a safety-critical
    error in weather-routing decisions.

    Parameters
    ----------
    db:
        Injected SQLAlchemy session.

    Returns
    -------
    ForecastResponse
        Current temp, 5-min forecast, trend direction, and R² score.

    Raises
    ------
    HTTPException(422)
        When fewer than 10 clean records exist — not enough signal to fit
        a meaningful model.
    """
    MIN_RECORDS: int = 10
    QUERY_LIMIT: int = 100
    FORECAST_HORIZON_S: float = 300.0  # 5 minutes

    records = (
        db.query(WeatherReading)
        .filter(WeatherReading.is_outlier == False)  # noqa: E712
        .order_by(WeatherReading.id.desc())
        .limit(QUERY_LIMIT)
        .all()
    )

    if len(records) < MIN_RECORDS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Insufficient data: {len(records)} clean records found, "
                f"minimum {MIN_RECORDS} required to produce a reliable forecast. "
                "Continue streaming sensor data and retry."
            ),
        )

    # Reverse to chronological order for time-series processing.
    records = list(reversed(records))

    df = pd.DataFrame(
        {
            "timestamp": [r.timestamp for r in records],
            "temp_c": [r.temp_c for r in records],
        }
    )

    # Represent time as seconds relative to the first record in the window.
    # Using relative time (rather than Unix epoch) keeps the X values small
    # and avoids numerical precision issues in the regression coefficients.
    df["time_s"] = pd.to_datetime(df["timestamp"], utc=True).astype("int64") // 10**9
    t0: int = int(df["time_s"].iloc[0])
    df["relative_s"] = df["time_s"] - t0

    X = df[["relative_s"]].values
    y = df["temp_c"].values

    model = LinearRegression()
    model.fit(X, y)

    r_squared: float = float(model.score(X, y))

    # Current temperature: most recent reading in the window.
    current_temp: float = float(df["temp_c"].iloc[-1])

    # Forecast horizon: last relative timestamp + 300 s.
    last_relative_s: float = float(df["relative_s"].iloc[-1])
    forecast_relative_s: float = last_relative_s + FORECAST_HORIZON_S
    forecast_temp: float = float(
        model.predict(np.array([[forecast_relative_s]]))[0]
    )

    # Classify trend from the regression slope.
    # 0.1 °C dead-band prevents "rising" / "falling" noise on a flat signal.
    STABLE_BAND: float = 0.1
    temp_delta: float = forecast_temp - current_temp

    if temp_delta > STABLE_BAND:
        trend = "rising"
    elif temp_delta < -STABLE_BAND:
        trend = "falling"
    else:
        trend = "stable"

    logger.info(
        "Forecast: current=%.2f°C  5-min=%.2f°C  trend=%s  R²=%.3f  n=%d",
        current_temp,
        forecast_temp,
        trend,
        r_squared,
        len(records),
    )

    return ForecastResponse(
        current_temp=round(current_temp, 3),
        forecast_5min_temp=round(forecast_temp, 3),
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
    System health probe.

    Used by the Docker Compose healthcheck and monitoring dashboards to
    verify the API is alive and the database is reachable.  Returns the
    total record count and the most recent reading for quick sanity checks.

    Parameters
    ----------
    db:
        Injected SQLAlchemy session.

    Returns
    -------
    StatusResponse
        Health status, record count, latest reading snapshot, and system tag.
    """
    total_records: int = db.query(func.count(WeatherReading.id)).scalar() or 0

    latest_record: Optional[WeatherReading] = (
        db.query(WeatherReading)
        .order_by(WeatherReading.id.desc())
        .first()
    )

    latest_snapshot: Optional[dict[str, Any]] = None
    if latest_record is not None:
        latest_snapshot = {
            "id": latest_record.id,
            "timestamp": latest_record.timestamp,
            "temp_c": latest_record.temp_c,
            "raw_wind_ms": latest_record.raw_wind_ms,
            "wind_ms_smoothed": latest_record.wind_ms_smoothed,
            "is_outlier": latest_record.is_outlier,
        }

    return StatusResponse(
        status="healthy",
        record_count=total_records,
        latest_reading=latest_snapshot,
        system="Sentinel-Stream v1.0 — Port of Long Beach buoy pipeline",
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
    Retrieve the most recent N sensor readings.

    Intended for dashboard consumption, debugging, and integration testing.
    Results are returned in reverse-chronological order (newest first).

    Parameters
    ----------
    n:
        Number of records to return.  Defaults to 20; capped at 1000 to
        prevent runaway queries on large databases.
    db:
        Injected SQLAlchemy session.

    Returns
    -------
    ReadingsResponse
        Record count and list of reading dicts.
    """
    n = min(max(1, n), 1000)  # clamp to [1, 1000]

    records = (
        db.query(WeatherReading)
        .order_by(WeatherReading.id.desc())
        .limit(n)
        .all()
    )

    readings = [
        {
            "id": r.id,
            "timestamp": r.timestamp,
            "lat": r.lat,
            "long": r.long,
            "temp_c": r.temp_c,
            "pressure_hpa": r.pressure_hpa,
            "raw_wind_ms": r.raw_wind_ms,
            "wind_ms_smoothed": r.wind_ms_smoothed,
            "is_outlier": r.is_outlier,
        }
        for r in records
    ]

    return ReadingsResponse(count=len(readings), readings=readings)
