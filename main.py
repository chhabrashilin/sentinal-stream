"""
main.py — Sentinel-Stream v2.0 — Mendota Digital Twin

Real-time environmental intelligence pipeline for Lake Mendota, Madison, WI.
Ingests 1 Hz NTL-LTER buoy telemetry from a distributed edge-node swarm,
applies physics-informed ML to maintain a continuous digital twin of the
lake's thermal state, and serves 48-hour foresight risk scores for HAB,
anoxia, and lake-turnover events.

Architecture overview
---------------------
  POST /ingest           ← 1 Hz telemetry from any registered edge node
      │
      ├─ Pydantic validation   (physical-plausibility bounds per field)
      ├─ Hard-threshold outlier (wind > 20 m/s OR chlorophyll > 100 µg/L)
      ├─ Z-score fouling detect (|z| > 3.0 on 60-reading rolling window)
      ├─ Rolling-window smooth  (10-point clean wind buffer)
      └─ SQLite persistence     (all fields + node_id + fouling flags)

  GET /digital-twin      ← physics-informed ML subsurface predictor
      │
      └─ MultiOutputRegressor (Ridge) trained on recent atmospheric+depth
         records.  Predicts full water-column profile (0m–20m) from surface
         air temp and wind alone — enabling continuous estimation in Ice-In mode.

  GET /foresight         ← 48-hour risk assessment
      │
      └─ Scoring model for HAB (algal bloom), Anoxia (oxygen depletion),
         and Turnover (lake overturn) risks based on stratification,
         chlorophyll, wind energy, and surface temperature trend.

  POST /nodes/register   ← edge node self-registration
  GET  /nodes            ← list all registered swarm nodes
  GET  /ice-mode         ← query current Ice-In estimation mode state
  POST /ice-mode         ← toggle Ice-In estimation mode
  GET  /forecast         ← 5-min surface temperature forecast (linear regression)
  GET  /stratification   ← thermocline strength and classification
  GET  /status           ← health probe (Docker healthcheck target)
  GET  /readings         ← recent record retrieval for dashboards
  GET  /buoy-status      ← live proxy to SSEC MetObs status API
"""

from __future__ import annotations

import logging
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Deque, Optional

import numpy as np
import pandas as pd
import requests as http_requests
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.metrics import r2_score
from sklearn.multioutput import MultiOutputRegressor
from sqlalchemy import (
    Boolean, Column, Float, Integer, String,
    create_engine, func, text,
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

DATABASE_URL: str = "sqlite:///./mendota_buoy.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------

class BuoyReading(Base):
    """
    Persisted buoy telemetry record — Lake Mendota NTL-LTER digital twin.

    Stores the full sensor payload plus two derived quality flags:
      is_outlier     — hard-threshold violation (wind or chlorophyll)
      zscore_fouling — statistical spike detected by rolling Z-score filter

    node_id links each record to the edge node that sourced it, enabling
    per-node quality analysis across the simulated sensor swarm.
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
    water_temp_0m: float = Column(Float, nullable=False)
    water_temp_5m: float = Column(Float, nullable=False)
    water_temp_10m: float = Column(Float, nullable=False)
    water_temp_20m: float = Column(Float, nullable=False)

    # Biological / chemical
    chlorophyll_ugl: float = Column(Float, nullable=False)

    # Quality flags
    is_outlier: bool = Column(Boolean, nullable=False, default=False)
    zscore_fouling: bool = Column(Boolean, nullable=False, default=False)

    # Edge node identifier (null for legacy records from single-node deployment)
    node_id: str = Column(String, nullable=True)


class EdgeNode(Base):
    """
    Registered edge node in the Sentinel-Stream swarm.

    Each Docker container running sensor_emulator.py self-registers here
    on startup, providing a persistent record of the swarm topology for
    dashboard display and per-node data provenance.
    """

    __tablename__ = "edge_nodes"

    id: int = Column(Integer, primary_key=True, index=True)
    node_id: str = Column(String, unique=True, nullable=False, index=True)
    lat: float = Column(Float, nullable=False)
    long: float = Column(Float, nullable=False)
    location: str = Column(String, nullable=True)
    registered_at: str = Column(String, nullable=False)
    last_seen: str = Column(String, nullable=True)
    reading_count: int = Column(Integer, default=0)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Hard-threshold outlier detection
WIND_OUTLIER_THRESHOLD_MS: float = 20.0
CHLOROPHYLL_OUTLIER_THRESHOLD_UGL: float = 100.0

# Rolling-window smoothing (wind)
WINDOW_SIZE: int = 10

# Z-score sensor fouling detection
# 60 samples at 1 Hz = 60-second adaptive baseline per sensor.
ZSCORE_WINDOW: int = 60
ZSCORE_THRESHOLD: float = 3.0
ZSCORE_MIN_SAMPLES: int = 15  # minimum samples before Z-score is meaningful

# Physics-informed digital twin model
MIN_TWIN_RECORDS: int = 30  # minimum clean records needed to train

# ---------------------------------------------------------------------------
# Process-lifetime state
# ---------------------------------------------------------------------------

# Outlier-filtered wind readings for rolling-average smoothing.
rolling_buffer: Deque[float] = deque(maxlen=WINDOW_SIZE)

# Per-sensor rolling buffers for Z-score fouling detection.
# Each sensor maintains its own adaptive baseline independent of the others.
sensor_buffers: dict[str, Deque[float]] = {
    "air_temp_c":      deque(maxlen=ZSCORE_WINDOW),
    "wind_speed_ms":   deque(maxlen=ZSCORE_WINDOW),
    "water_temp_0m":   deque(maxlen=ZSCORE_WINDOW),
    "chlorophyll_ugl": deque(maxlen=ZSCORE_WINDOW),
}

# Ice-In estimation mode — when True, the digital twin operates without
# physical sensor data (sensors are retracted for winter).
ice_mode_enabled: bool = False

# Cached physics-informed model (trained lazily from DB records).
_digital_twin_model: Optional[MultiOutputRegressor] = None
_model_records_used: int = 0
_model_r2: float = 0.0


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class WaterTempProfile(BaseModel):
    field_0m: float = Field(..., alias="0m", ge=0.0, le=35.0)
    field_5m: float = Field(..., alias="5m", ge=0.0, le=35.0)
    field_10m: float = Field(..., alias="10m", ge=0.0, le=35.0)
    field_20m: float = Field(..., alias="20m", ge=0.0, le=35.0)

    model_config = {"populate_by_name": True}


class SensorReading(BaseModel):
    """Validated inbound telemetry payload from a Lake Mendota edge node."""

    timestamp: str = Field(..., description="ISO-8601 UTC timestamp.")
    location: Optional[str] = Field(default=None)
    lat: float = Field(..., ge=42.9, le=43.2)
    long: float = Field(..., ge=-89.6, le=-89.3)
    air_temp_c: float = Field(..., ge=-40.0, le=50.0)
    wind_speed_ms: float = Field(..., ge=0.0, le=60.0)
    water_temp_profile: WaterTempProfile
    chlorophyll_ugl: float = Field(..., ge=0.0, le=1000.0)
    node_id: Optional[str] = Field(
        default=None,
        description="Edge node identifier (e.g. 'node-north'). Null for legacy single-node deployments.",
    )

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("timestamp must not be empty")
        return v


class IngestResponse(BaseModel):
    status: str
    smoothed_wind_ms: float
    is_outlier: bool
    zscore_fouling: bool = Field(
        description="True if any sensor field triggered the Z-score fouling detector (|z| > 3.0)."
    )
    surface_water_temp_c: float
    node_id: Optional[str]


class ForecastResponse(BaseModel):
    current_surface_temp_c: float
    forecast_5min_surface_temp_c: float
    trend: str
    r_squared: float
    records_used: int


class StatusResponse(BaseModel):
    status: str
    record_count: int
    latest_reading: Optional[dict[str, Any]]
    system: str


class ReadingsResponse(BaseModel):
    count: int
    readings: list[dict[str, Any]]


class StratificationResponse(BaseModel):
    surface_temp_c: float
    deep_temp_c: float
    thermocline_strength_c: float
    stratification_status: str
    timestamp: str


class BuoyStatusResponse(BaseModel):
    ssec_status_code: Optional[int]
    ssec_status_message: str
    ssec_last_updated: str
    pipeline_mode: str
    ssec_api_reachable: bool


class NodeRegistration(BaseModel):
    """Edge node self-registration payload."""
    node_id: str = Field(..., description="Unique identifier for this edge node.")
    lat: float = Field(..., ge=42.9, le=43.2)
    long: float = Field(..., ge=-89.6, le=-89.3)
    location: Optional[str] = Field(default=None)


class NodeResponse(BaseModel):
    node_id: str
    lat: float
    long: float
    location: Optional[str]
    registered_at: str
    last_seen: Optional[str]
    reading_count: int


class IceModeRequest(BaseModel):
    enabled: bool = Field(..., description="True to activate Ice-In estimation mode.")


class IceModeResponse(BaseModel):
    ice_mode_enabled: bool
    mode: str = Field(description="'estimation' when sensors retracted, 'live' otherwise.")
    message: str


class DigitalTwinResponse(BaseModel):
    """
    Physics-informed ML prediction of the full water-column temperature profile.

    In 'verification' mode (live sensors): predicted values are shown alongside
    measured values to validate the model against ground truth.
    In 'estimation' mode (Ice-In): measured values are None; the digital twin
    is the sole source of subsurface thermal state.
    """
    surface_temp_c: float
    predicted_5m_c: float
    predicted_10m_c: float
    predicted_20m_c: float
    measured_5m_c: Optional[float]
    measured_10m_c: Optional[float]
    measured_20m_c: Optional[float]
    model_r2: float = Field(description="Mean R² of the multi-output regression model.")
    model_confidence: float = Field(description="Normalised confidence [0,1] based on training records.")
    mode: str = Field(description="'estimation' (Ice-In) or 'verification' (live sensors).")
    records_used: int
    ice_mode: bool

    model_config = {"protected_namespaces": ()}


class ForesightResponse(BaseModel):
    """48-hour environmental risk assessment for Lake Mendota."""
    risk_score: float = Field(description="Aggregate risk score [0, 1].")
    risk_level: str = Field(description="One of: 'low', 'moderate', 'high', 'critical'.")
    primary_risk: str = Field(description="Dominant risk category: 'hab', 'anoxia', or 'turnover'.")
    risk_scores: dict[str, float] = Field(description="Per-category scores.")
    horizon_hours: int = Field(default=48)
    contributing_factors: list[str]
    recommendation: str
    timestamp: str


# ---------------------------------------------------------------------------
# Dependency injection
# ---------------------------------------------------------------------------

def get_db() -> Any:
    with SessionLocal() as db:
        yield db


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _zscore(value: float, buf: Deque[float]) -> Optional[float]:
    """
    Compute the absolute Z-score of *value* against the rolling buffer.

    Returns None if the buffer has fewer than ZSCORE_MIN_SAMPLES entries
    (not enough data for a meaningful baseline).  Returns 0.0 if the buffer
    has zero variance (constant signal — sensor may be stuck, but not spiking).
    """
    if len(buf) < ZSCORE_MIN_SAMPLES:
        return None
    arr = np.array(list(buf))
    std = float(np.std(arr))
    if std < 1e-6:
        return 0.0
    return abs(float((value - float(np.mean(arr))) / std))


def _build_twin_features(air_temp: float, wind: float) -> np.ndarray:
    """
    Physics-informed feature vector for the digital twin model.

    Features encode the primary atmospheric forcings of lake thermal dynamics:
      air_temp_c             — surface boundary condition (heat exchange)
      wind_speed_ms          — mixing energy (linear)
      wind_speed_ms²         — mixing energy (kinetic, ~ v²)
      air_temp × wind_speed  — coupling: cold + windy = faster conductive cooling
    """
    return np.array([[air_temp, wind, wind ** 2, air_temp * wind]])


def _train_digital_twin(db: Session) -> tuple[Optional[MultiOutputRegressor], int, float]:
    """
    Train a physics-informed multi-output regression model on recent clean records.

    The model predicts the full water-column temperature profile (0m, 5m, 10m, 20m)
    from atmospheric surface signals (air temperature + wind speed), enabling
    digital twin estimation when physical thermistor chains are retracted for winter.

    Ridge regularisation prevents overfitting on the correlated feature set and
    ensures physically stable predictions during extrapolation.
    """
    records = (
        db.query(BuoyReading)
        .filter(BuoyReading.is_outlier == False)  # noqa: E712
        .order_by(BuoyReading.id.desc())
        .limit(500)
        .all()
    )

    if len(records) < MIN_TWIN_RECORDS:
        return None, 0, 0.0

    X = np.array([
        [r.air_temp_c, r.wind_speed_ms_smoothed,
         r.wind_speed_ms_smoothed ** 2,
         r.air_temp_c * r.wind_speed_ms_smoothed]
        for r in records
    ])
    y = np.array([
        [r.water_temp_0m, r.water_temp_5m, r.water_temp_10m, r.water_temp_20m]
        for r in records
    ])

    model = MultiOutputRegressor(Ridge(alpha=1.0))
    model.fit(X, y)

    y_pred = model.predict(X)
    r2 = float(r2_score(y, y_pred, multioutput="uniform_average"))

    logger.info(
        "Digital twin model trained: %d records, mean R²=%.3f",
        len(records), r2,
    )
    return model, len(records), max(0.0, r2)


def _compute_foresight(
    recent_records: list,
    strat_status: str,
    thermo_strength: float,
) -> dict:
    """
    Compute a 48-hour multi-hazard risk score for Lake Mendota.

    Three risk categories are evaluated independently, then the dominant
    risk and its score are surfaced as the actionable intelligence output:

      HAB (Harmful Algal Bloom)
        Drivers: strong stratification + elevated chlorophyll + low wind
        Physics: calm, warm, stratified water concentrates nutrients in the
                 epilimnion, providing ideal conditions for cyanobacteria.

      Anoxia
        Drivers: prolonged stratification + warm hypolimnion + decomposition
        Physics: the deep layer is cut off from surface oxygen exchange; as
                 organic matter decomposes, dissolved O2 is consumed.

      Turnover
        Drivers: rapid surface cooling + high wind + weakly stratified column
        Physics: when surface water cools to match deep water density,
                 a mixing event overturns the column — resurfacing anoxic water.
    """
    if len(recent_records) < 5:
        return {
            "risk_score": 0.0,
            "risk_level": "unknown",
            "primary_risk": "none",
            "risk_scores": {"hab": 0.0, "anoxia": 0.0, "turnover": 0.0},
            "contributing_factors": ["Insufficient sensor data for risk assessment"],
            "recommendation": "Stream sensor data to enable 48-hour foresight.",
        }

    latest = recent_records[0]
    chl = latest.chlorophyll_ugl
    wind = latest.wind_speed_ms_smoothed

    # ── HAB risk ──────────────────────────────────────────────────────────────
    # Cyanobacterial blooms on Lake Mendota are driven by three interacting
    # conditions: (1) thermal stratification that keeps buoyant cells near the
    # light-rich surface, (2) elevated phosphorus/nitrogen tracked by chl-a as
    # a biomass proxy, and (3) calm wind — field studies on Mendota show blooms
    # collapse when sustained wind exceeds ~5–8 m/s, which erodes the
    # thermocline and mixes cells below the photic zone.  8 m/s is used as the
    # mixing saturation point (wind_calm_w → 0 at or above that speed).
    strat_w     = {"stratified": 0.8, "weakly_stratified": 0.45, "mixed": 0.1}.get(strat_status, 0.1)
    chl_w       = min(1.0, chl / 50.0)        # Wisconsin DNR concern threshold ~20 µg/L; 50 saturates
    wind_calm_w = max(0.0, 1.0 - wind / 8.0)  # full mixing disruption above 8 m/s
    hab = round(0.40 * strat_w + 0.35 * chl_w + 0.25 * wind_calm_w, 3)

    # ── Anoxia risk ───────────────────────────────────────────────────────────
    # Hypolimnetic anoxia in Lake Mendota occurs when the thermocline persists
    # long enough to cut the deep layer off from surface O₂ exchange.  Warm
    # deep-water temperatures accelerate organic decomposition (O₂ consumption
    # rate ~ doubles every 10°C — van 't Hoff rule).  The hypolimnion at 20m
    # in Mendota typically ranges 4°C (spring isothermal) to ~10°C (late summer
    # peak), so we normalise over a 6°C working range rather than an
    # unphysical 20°C range.
    thermo_w = min(1.0, thermo_strength / 15.0)
    deep_w   = min(1.0, max(0.0, (latest.water_temp_20m - 4.0) / 6.0))  # 4°C → 0, 10°C → 1
    anoxia   = round(0.60 * thermo_w + 0.25 * deep_w + 0.15 * chl_w, 3)

    # ── Turnover risk ─────────────────────────────────────────────────────────
    # Fall/spring overturn occurs when the surface cools to match hypolimnion
    # density, allowing wind to mix the full column.  The vulnerability is
    # highest for a *weakly stratified* column (on the cusp of mixing), moderate
    # for a *strongly stratified* column (thermal inertia delays onset but the
    # eventual event is more dramatic), and lowest for an already *mixed* column
    # (turnover already complete — no stratified energy available to release).
    #
    # Cooling rate is measured over the last 50 clean records (≈50 s at 1 Hz).
    # Normalisation: -0.001°C/s (= -3.6°C/hour) saturates the cooling factor at 1.0.
    # Rates below 0.001°C/s are climatologically realistic precursors; this
    # threshold avoids false positives from instrument noise (σ ≈ 0.15°C → noise
    # slope ≈ ±0.003°C/reading over 50 records, filtered by the max(0,...) guard).
    clean         = [r for r in recent_records[:50] if not r.is_outlier]
    surface_temps = [r.water_temp_0m for r in reversed(clean)]
    if len(surface_temps) >= 10:
        xs    = np.arange(len(surface_temps), dtype=float)
        slope = float(np.polyfit(xs, surface_temps, 1)[0])
        cooling_w = min(1.0, max(0.0, -slope / 0.001))
    else:
        cooling_w = 0.0

    wind_mix_w = min(1.0, wind / 15.0)
    vuln_w     = {"weakly_stratified": 0.9, "stratified": 0.4, "mixed": 0.1}.get(strat_status, 0.2)
    turnover   = round(0.35 * cooling_w + 0.35 * wind_mix_w + 0.30 * vuln_w, 3)

    # ── Aggregate ─────────────────────────────────────────────────────────────
    scores = {"hab": hab, "anoxia": anoxia, "turnover": turnover}
    primary = max(scores, key=scores.get)
    score = scores[primary]

    level = (
        "critical" if score >= 0.70 else
        "high"     if score >= 0.50 else
        "moderate" if score >= 0.30 else
        "low"
    )

    # ── Contributing factors ──────────────────────────────────────────────────
    factors: list[str] = []
    if strat_w >= 0.40:
        factors.append(f"Strong thermal stratification (Δt = {thermo_strength:.1f} °C)")
    if chl_w >= 0.30:
        factors.append(f"Elevated chlorophyll-a ({chl:.1f} µg/L)")
    if wind_calm_w >= 0.60:
        factors.append(f"Low mixing energy (wind {wind:.1f} m/s — stagnant surface)")
    if wind_mix_w >= 0.60:
        factors.append(f"High wind speed ({wind:.1f} m/s — potential mixing event)")
    if cooling_w >= 0.30:
        factors.append("Rapid surface cooling — lake turnover precursor")
    if not factors:
        factors.append("All parameters within normal seasonal range")

    # ── Recommendation ────────────────────────────────────────────────────────
    _recs: dict[tuple, str] = {
        ("hab", "critical"): (
            "Issue HAB advisory. Stratified, stagnant, nutrient-rich conditions "
            "strongly favour cyanobacterial bloom development within 48 hours."
        ),
        ("hab", "high"): (
            "Monitor algal conditions. HAB risk elevated by stratification and "
            "low mixing energy — bloom initiation possible within 48 hours."
        ),
        ("anoxia", "critical"): (
            "Hypolimnetic anoxia imminent. Prolonged stratification restricting "
            "O₂ recharge to the deep layer — benthic organisms at risk."
        ),
        ("anoxia", "high"): (
            "Anoxia risk growing. Monitor dissolved oxygen at depth. Deep O₂ "
            "depletion may stress cold-water fish species."
        ),
        ("turnover", "critical"): (
            "Lake overturn likely within 48 hours. Resurfacing of anoxic hypolimnetic "
            "water may trigger a fish kill — issue waterway advisory."
        ),
        ("turnover", "high"): (
            "Turnover conditions developing. Monitor surface temperature and wind. "
            "A significant mixing event may occur within 48 hours."
        ),
    }
    recommendation = _recs.get(
        (primary, level),
        "Conditions within acceptable range. Continue routine 1 Hz monitoring.",
    )

    return {
        "risk_score": round(score, 3),
        "risk_level": level,
        "primary_risk": primary,
        "risk_scores": scores,
        "contributing_factors": factors,
        "recommendation": recommendation,
    }


# ---------------------------------------------------------------------------
# Lifespan context manager
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Startup: create schema, migrate new columns, seed rolling buffer.
    Shutdown: log clean exit.
    """
    logger.info("Sentinel-Stream v2.0 starting — creating database schema.")
    Base.metadata.create_all(bind=engine)

    # Additive schema migration for columns added in v2.0.
    # SQLite's create_all() only creates missing *tables*, not missing columns,
    # so we ALTER TABLE explicitly.  Errors are caught and ignored when the
    # column already exists (idempotent on repeated restarts).
    _migrations = [
        "ALTER TABLE buoy_readings ADD COLUMN node_id TEXT",
        "ALTER TABLE buoy_readings ADD COLUMN zscore_fouling BOOLEAN DEFAULT FALSE",
    ]
    with engine.connect() as conn:
        for stmt in _migrations:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                pass  # column already exists

    # Seed the rolling wind buffer from the most recent clean DB records so
    # a service restart preserves smoothing context.
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

        # Seed per-sensor Z-score buffers from recent readings.
        zseed = (
            db.query(BuoyReading)
            .filter(BuoyReading.is_outlier == False)  # noqa: E712
            .order_by(BuoyReading.id.desc())
            .limit(ZSCORE_WINDOW)
            .all()
        )
        for r in reversed(zseed):
            sensor_buffers["air_temp_c"].append(r.air_temp_c)
            sensor_buffers["wind_speed_ms"].append(r.raw_wind_speed_ms)
            sensor_buffers["water_temp_0m"].append(r.water_temp_0m)
            sensor_buffers["chlorophyll_ugl"].append(r.chlorophyll_ugl)

        logger.info(
            "Rolling buffer seeded: wind=%d records, Z-score buffers=%d records.",
            len(rolling_buffer),
            len(sensor_buffers["air_temp_c"]),
        )

    logger.info(
        "Sentinel-Stream v2.0 ready — Lake Mendota NTL-LTER digital twin online. "
        "Buoy: 43.0988° N, 89.4045° W"
    )
    yield

    logger.info("Sentinel-Stream v2.0 shutting down gracefully.")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Sentinel-Stream v2.0: Mendota Edition",
    description=(
        "Real-time environmental intelligence pipeline for Lake Mendota, Madison, WI. "
        "Ingests 1 Hz NTL-LTER edge-node telemetry, applies physics-informed ML for "
        "continuous digital twin operation, and serves 48-hour foresight risk scores "
        "for harmful algal bloom, anoxia, and lake-turnover events."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
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
    Ingest a validated edge-node telemetry packet.

    Processing pipeline
    -------------------
    1. Pydantic has already validated field types and physical plausibility.
    2. Hard-threshold outlier: wind > 20 m/s OR chlorophyll > 100 µg/L.
    3. Z-score sensor fouling: |z| > 3.0 on 60-reading rolling baseline.
       This catches rapid spikes that pass the hard threshold (e.g., a water
       temperature that suddenly jumps 8 °C — physically impossible in 1 s).
    4. Rolling wind buffer updated with clean readings only.
    5. Edge node last_seen / reading_count updated if node_id provided.
    6. Full record persisted including both quality flags.
    """
    # ── Hard-threshold outlier detection ──────────────────────────────────────
    wind_outlier: bool = reading.wind_speed_ms > WIND_OUTLIER_THRESHOLD_MS
    chl_outlier: bool = reading.chlorophyll_ugl > CHLOROPHYLL_OUTLIER_THRESHOLD_UGL
    is_outlier: bool = wind_outlier or chl_outlier

    # ── Z-score sensor fouling detection ──────────────────────────────────────
    # Run Z-score check before updating the buffer so we measure against the
    # existing baseline, not a baseline already contaminated by this reading.
    z_checks = {
        "air_temp_c":      _zscore(reading.air_temp_c,      sensor_buffers["air_temp_c"]),
        "wind_speed_ms":   _zscore(reading.wind_speed_ms,    sensor_buffers["wind_speed_ms"]),
        "water_temp_0m":   _zscore(reading.water_temp_profile.field_0m, sensor_buffers["water_temp_0m"]),
        "chlorophyll_ugl": _zscore(reading.chlorophyll_ugl,  sensor_buffers["chlorophyll_ugl"]),
    }
    zscore_fouling: bool = any(
        z is not None and z > ZSCORE_THRESHOLD for z in z_checks.values()
    )

    if zscore_fouling:
        triggered = [k for k, z in z_checks.items() if z is not None and z > ZSCORE_THRESHOLD]
        logger.warning(
            "Sensor fouling detected (Z-score) — fields=%s — stored with zscore_fouling=True.",
            triggered,
        )

    if is_outlier:
        logger.warning(
            "Outlier detected (hard threshold) — wind_outlier=%s, chl_outlier=%s — "
            "wind=%.1f m/s, chl=%.1f µg/L.",
            wind_outlier, chl_outlier,
            reading.wind_speed_ms, reading.chlorophyll_ugl,
        )

    # ── Update Z-score buffers (clean readings only) ───────────────────────
    if not is_outlier and not zscore_fouling:
        sensor_buffers["air_temp_c"].append(reading.air_temp_c)
        sensor_buffers["wind_speed_ms"].append(reading.wind_speed_ms)
        sensor_buffers["water_temp_0m"].append(reading.water_temp_profile.field_0m)
        sensor_buffers["chlorophyll_ugl"].append(reading.chlorophyll_ugl)

    # ── Rolling wind smoothing ────────────────────────────────────────────────
    if not is_outlier:
        rolling_buffer.append(reading.wind_speed_ms)

    smoothed_wind: float = (
        float(np.mean(list(rolling_buffer))) if rolling_buffer else reading.wind_speed_ms
    )

    # ── Persist ───────────────────────────────────────────────────────────────
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
        zscore_fouling=zscore_fouling,
        node_id=reading.node_id,
    )
    db.add(record)

    # Update edge node activity if node_id is known
    if reading.node_id:
        node = db.query(EdgeNode).filter(EdgeNode.node_id == reading.node_id).first()
        if node:
            node.last_seen = reading.timestamp
            node.reading_count = (node.reading_count or 0) + 1

    db.commit()

    return IngestResponse(
        status="ok",
        smoothed_wind_ms=round(smoothed_wind, 4),
        is_outlier=is_outlier,
        zscore_fouling=zscore_fouling,
        surface_water_temp_c=record.water_temp_0m,
        node_id=reading.node_id,
    )


# ---------------------------------------------------------------------------
# GET /forecast
# ---------------------------------------------------------------------------

@app.get("/forecast", response_model=ForecastResponse)
def get_forecast(db: Session = Depends(get_db)) -> ForecastResponse:
    """
    Generate a 5-minute surface water temperature forecast using linear regression.
    """
    MIN_RECORDS: int = 10
    QUERY_LIMIT: int = 100
    FORECAST_HORIZON_S: float = 300.0
    STABLE_BAND_C: float = 0.1

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
                f"minimum {MIN_RECORDS} required. Continue streaming and retry."
            ),
        )

    records = list(reversed(records))

    df = pd.DataFrame(
        {
            "timestamp":    [r.timestamp for r in records],
            "water_temp_0m": [r.water_temp_0m for r in records],
        }
    )
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
    """Health probe — Docker healthcheck target."""
    record_count: int = db.query(func.count(BuoyReading.id)).scalar() or 0

    latest_record = db.query(BuoyReading).order_by(BuoyReading.id.desc()).first()

    latest: Optional[dict[str, Any]] = None
    if latest_record is not None:
        latest = {
            "id":               latest_record.id,
            "timestamp":        latest_record.timestamp,
            "air_temp_c":       latest_record.air_temp_c,
            "water_temp_0m":    latest_record.water_temp_0m,
            "smoothed_wind_ms": latest_record.wind_speed_ms_smoothed,
            "chlorophyll_ugl":  latest_record.chlorophyll_ugl,
            "is_outlier":       latest_record.is_outlier,
            "zscore_fouling":   latest_record.zscore_fouling,
            "node_id":          latest_record.node_id,
        }

    return StatusResponse(
        status="healthy",
        record_count=record_count,
        latest_reading=latest,
        system="Sentinel-Stream v2.0 | Lake Mendota NTL-LTER digital twin",
    )


# ---------------------------------------------------------------------------
# GET /readings
# ---------------------------------------------------------------------------

@app.get("/readings", response_model=ReadingsResponse)
def get_readings(
    n: int = 20,
    db: Session = Depends(get_db),
) -> ReadingsResponse:
    """Retrieve the N most recent buoy readings (default 20, max 500)."""
    n = max(1, min(n, 500))

    records = (
        db.query(BuoyReading)
        .order_by(BuoyReading.id.desc())
        .limit(n)
        .all()
    )

    readings = [
        {
            "id":               r.id,
            "timestamp":        r.timestamp,
            "location":         r.location,
            "lat":              r.lat,
            "long":             r.long,
            "air_temp_c":       r.air_temp_c,
            "raw_wind_speed_ms":        r.raw_wind_speed_ms,
            "wind_speed_ms_smoothed":   r.wind_speed_ms_smoothed,
            "water_temp_profile": {
                "0m":  r.water_temp_0m,
                "5m":  r.water_temp_5m,
                "10m": r.water_temp_10m,
                "20m": r.water_temp_20m,
            },
            "chlorophyll_ugl":  r.chlorophyll_ugl,
            "is_outlier":       r.is_outlier,
            "zscore_fouling":   r.zscore_fouling,
            "node_id":          r.node_id,
        }
        for r in records
    ]

    return ReadingsResponse(count=len(readings), readings=readings)


# ---------------------------------------------------------------------------
# GET /stratification
# ---------------------------------------------------------------------------

SSEC_STATUS_URL: str = "http://metobs.ssec.wisc.edu/api/status/mendota/buoy.json"


@app.get("/stratification", response_model=StratificationResponse)
def get_stratification(db: Session = Depends(get_db)) -> StratificationResponse:
    """
    Compute the current thermal stratification strength of Lake Mendota.

    Δt = water_temp_0m − water_temp_20m
    """
    latest = (
        db.query(BuoyReading)
        .filter(BuoyReading.is_outlier == False)  # noqa: E712
        .order_by(BuoyReading.id.desc())
        .first()
    )

    if latest is None:
        raise HTTPException(
            status_code=422,
            detail="No clean records available. Stream sensor data first.",
        )

    delta: float = latest.water_temp_0m - latest.water_temp_20m

    if delta >= 10.0:
        status = "stratified"
    elif delta >= 4.0:
        status = "weakly_stratified"
    else:
        status = "mixed"

    return StratificationResponse(
        surface_temp_c=round(latest.water_temp_0m, 3),
        deep_temp_c=round(latest.water_temp_20m, 3),
        thermocline_strength_c=round(delta, 3),
        stratification_status=status,
        timestamp=latest.timestamp,
    )


# ---------------------------------------------------------------------------
# GET /buoy-status
# ---------------------------------------------------------------------------

@app.get("/buoy-status", response_model=BuoyStatusResponse)
def get_buoy_status() -> BuoyStatusResponse:
    """Proxy the real SSEC MetObs buoy operational status."""
    try:
        resp = http_requests.get(SSEC_STATUS_URL, timeout=5)
        resp.raise_for_status()
        data = resp.json()

        is_online: bool = data.get("status_code", -1) == 0
        return BuoyStatusResponse(
            ssec_status_code=data.get("status_code"),
            ssec_status_message=data.get("status_message", "unknown"),
            ssec_last_updated=data.get("last_updated", "unknown"),
            pipeline_mode="live" if is_online else "emulator",
            ssec_api_reachable=True,
        )
    except Exception as exc:
        logger.warning("Could not reach SSEC status API: %s", exc)
        return BuoyStatusResponse(
            ssec_status_code=None,
            ssec_status_message="SSEC API unreachable",
            ssec_last_updated="unknown",
            pipeline_mode="emulator",
            ssec_api_reachable=False,
        )


# ---------------------------------------------------------------------------
# POST /nodes/register
# ---------------------------------------------------------------------------

@app.post("/nodes/register", response_model=NodeResponse, status_code=200)
def register_node(
    reg: NodeRegistration,
    db: Session = Depends(get_db),
) -> NodeResponse:
    """
    Register or update an edge node in the Sentinel-Stream swarm.

    Called automatically by sensor_emulator.py on startup. Re-registration
    of an existing node_id updates position and last_seen (nodes may be
    redeployed to different lake positions between seasons).
    """
    now = datetime.now(timezone.utc).isoformat()

    node = db.query(EdgeNode).filter(EdgeNode.node_id == reg.node_id).first()

    if node is None:
        node = EdgeNode(
            node_id=reg.node_id,
            lat=reg.lat,
            long=reg.long,
            location=reg.location,
            registered_at=now,
            last_seen=now,
            reading_count=0,
        )
        db.add(node)
        logger.info(
            "Edge node registered: %s at (%.4f, %.4f)", reg.node_id, reg.lat, reg.long
        )
    else:
        node.lat = reg.lat
        node.long = reg.long
        node.location = reg.location
        node.last_seen = now
        logger.info("Edge node re-registered: %s", reg.node_id)

    db.commit()
    db.refresh(node)

    return NodeResponse(
        node_id=node.node_id,
        lat=node.lat,
        long=node.long,
        location=node.location,
        registered_at=node.registered_at,
        last_seen=node.last_seen,
        reading_count=node.reading_count or 0,
    )


# ---------------------------------------------------------------------------
# GET /nodes
# ---------------------------------------------------------------------------

@app.get("/nodes", response_model=list[NodeResponse])
def get_nodes(db: Session = Depends(get_db)) -> list[NodeResponse]:
    """
    List all registered edge nodes in the Sentinel-Stream swarm.

    Returns nodes ordered by registration time.  The dashboard uses this
    to render the swarm map and per-node activity indicators.
    """
    nodes = db.query(EdgeNode).order_by(EdgeNode.registered_at).all()
    return [
        NodeResponse(
            node_id=n.node_id,
            lat=n.lat,
            long=n.long,
            location=n.location,
            registered_at=n.registered_at,
            last_seen=n.last_seen,
            reading_count=n.reading_count or 0,
        )
        for n in nodes
    ]


# ---------------------------------------------------------------------------
# GET /ice-mode
# ---------------------------------------------------------------------------

@app.get("/ice-mode", response_model=IceModeResponse)
def get_ice_mode() -> IceModeResponse:
    """
    Query the current Ice-In estimation mode state.

    When ice_mode_enabled is True, the Digital Twin operates in 'estimation'
    mode — the physics-informed ML model is the sole source of subsurface
    thermal state.  When False, the twin is in 'verification' mode, comparing
    ML predictions to live sensor measurements.
    """
    return IceModeResponse(
        ice_mode_enabled=ice_mode_enabled,
        mode="estimation" if ice_mode_enabled else "live",
        message=(
            "Physical sensors retracted. Digital twin operating in ML estimation mode."
            if ice_mode_enabled else
            "Physical sensors online. Digital twin in live verification mode."
        ),
    )


# ---------------------------------------------------------------------------
# POST /ice-mode
# ---------------------------------------------------------------------------

@app.post("/ice-mode", response_model=IceModeResponse)
def set_ice_mode(req: IceModeRequest) -> IceModeResponse:
    """
    Toggle Ice-In estimation mode.

    Activate (enabled=true) when the physical buoy thermistor chains are
    retracted for winter — typically late November through mid-March on
    Lake Mendota.  The digital twin will switch to ML-only subsurface
    temperature estimation, maintaining data continuity year-round.
    """
    global ice_mode_enabled
    ice_mode_enabled = req.enabled
    action = "activated" if req.enabled else "deactivated"
    logger.info("Ice-In estimation mode %s.", action)

    return IceModeResponse(
        ice_mode_enabled=ice_mode_enabled,
        mode="estimation" if ice_mode_enabled else "live",
        message=(
            "Ice-In mode activated. Digital twin switching to ML estimation."
            if ice_mode_enabled else
            "Ice-In mode deactivated. Digital twin returning to live sensor fusion."
        ),
    )


# ---------------------------------------------------------------------------
# GET /digital-twin
# ---------------------------------------------------------------------------

@app.get("/digital-twin", response_model=DigitalTwinResponse)
def get_digital_twin(db: Session = Depends(get_db)) -> DigitalTwinResponse:
    """
    Retrieve the current physics-informed ML digital twin state.

    The model (MultiOutputRegressor with Ridge regression) predicts the full
    water-column temperature profile (0m, 5m, 10m, 20m) from atmospheric
    surface signals (air temperature + wind speed).  It is trained lazily
    from recent clean DB records and retrained automatically every 100 new
    records.

    Modes
    -----
    verification: live sensors active — ML predictions compared to measured values.
    estimation:   Ice-In mode — ML predictions are the authoritative state.
    """
    global _digital_twin_model, _model_records_used, _model_r2

    # Get latest atmospheric reading
    latest = (
        db.query(BuoyReading)
        .filter(BuoyReading.is_outlier == False)  # noqa: E712
        .order_by(BuoyReading.id.desc())
        .first()
    )

    if latest is None:
        raise HTTPException(
            status_code=422,
            detail="No clean records available. Stream sensor data to initialise the digital twin.",
        )

    # Retrain if model is absent or stale (100+ new records since last train)
    current_count: int = db.query(func.count(BuoyReading.id)).scalar() or 0
    if _digital_twin_model is None or (current_count - _model_records_used) >= 100:
        _digital_twin_model, _model_records_used, _model_r2 = _train_digital_twin(db)

    if _digital_twin_model is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Insufficient data to train digital twin model "
                f"(need {MIN_TWIN_RECORDS} clean records, have {current_count})."
            ),
        )

    # Predict from atmospheric signals only
    features = _build_twin_features(latest.air_temp_c, latest.wind_speed_ms_smoothed)
    predictions = _digital_twin_model.predict(features)[0]

    # Model confidence normalised to training data size
    confidence = min(1.0, _model_records_used / 200.0)

    mode = "estimation" if ice_mode_enabled else "verification"

    logger.info(
        "Digital twin: mode=%s  air=%.2f°C  wind=%.2f m/s  "
        "pred=[0m=%.2f, 5m=%.2f, 10m=%.2f, 20m=%.2f]°C  R²=%.3f",
        mode,
        latest.air_temp_c, latest.wind_speed_ms_smoothed,
        predictions[0], predictions[1], predictions[2], predictions[3],
        _model_r2,
    )

    return DigitalTwinResponse(
        surface_temp_c=round(float(predictions[0]), 3),
        predicted_5m_c=round(float(predictions[1]), 3),
        predicted_10m_c=round(float(predictions[2]), 3),
        predicted_20m_c=round(float(predictions[3]), 3),
        measured_5m_c=None if ice_mode_enabled else round(latest.water_temp_5m, 3),
        measured_10m_c=None if ice_mode_enabled else round(latest.water_temp_10m, 3),
        measured_20m_c=None if ice_mode_enabled else round(latest.water_temp_20m, 3),
        model_r2=round(_model_r2, 4),
        model_confidence=round(confidence, 3),
        mode=mode,
        records_used=_model_records_used,
        ice_mode=ice_mode_enabled,
    )


# ---------------------------------------------------------------------------
# GET /foresight
# ---------------------------------------------------------------------------

@app.get("/foresight", response_model=ForesightResponse)
def get_foresight(db: Session = Depends(get_db)) -> ForesightResponse:
    """
    Generate a 48-hour environmental risk assessment for Lake Mendota.

    Evaluates three hazard categories driven by the current lake state:

      HAB      — harmful algal bloom risk from stratification + chl + calm wind
      Anoxia   — deep oxygen depletion risk from prolonged stratification
      Turnover — lake overturn risk from rapid cooling + high wind

    The dominant risk category, its score, and a human-readable recommendation
    are returned for display on the operator dashboard and autonomous alert systems.
    """
    MIN_RECORDS: int = 5

    recent = (
        db.query(BuoyReading)
        .filter(BuoyReading.is_outlier == False)  # noqa: E712
        .order_by(BuoyReading.id.desc())
        .limit(50)
        .all()
    )

    if len(recent) < MIN_RECORDS:
        raise HTTPException(
            status_code=422,
            detail=f"Insufficient data: {len(recent)} records, need {MIN_RECORDS}.",
        )

    latest = recent[0]
    delta: float = latest.water_temp_0m - latest.water_temp_20m
    strat_status = (
        "stratified"        if delta >= 10.0 else
        "weakly_stratified" if delta >= 4.0  else
        "mixed"
    )

    result = _compute_foresight(recent, strat_status, delta)

    logger.info(
        "Foresight: risk_score=%.3f  level=%s  primary=%s  strat=%s  thermo=%.2f°C",
        result["risk_score"], result["risk_level"], result["primary_risk"],
        strat_status, delta,
    )

    return ForesightResponse(
        risk_score=result["risk_score"],
        risk_level=result["risk_level"],
        primary_risk=result["primary_risk"],
        risk_scores=result["risk_scores"],
        horizon_hours=48,
        contributing_factors=result["contributing_factors"],
        recommendation=result["recommendation"],
        timestamp=latest.timestamp,
    )
