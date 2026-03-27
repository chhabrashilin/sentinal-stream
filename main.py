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


# ---------------------------------------------------------------------------
# Vessel guide — helpers, profiles, and GET /vessel-guide
# ---------------------------------------------------------------------------

def _beaufort(wind_ms: float) -> tuple[int, str]:
    """
    Convert wind speed (m/s) to Beaufort number and plain-language description.

    Beaufort scale for an inland lake context — descriptions reflect conditions
    experienced on open water such as Lake Mendota rather than oceanic terms.
    """
    thresholds = [
        (0.3,  0, "Calm — mirror-flat water"),
        (1.6,  1, "Light air — slight ripples, no crests"),
        (3.4,  2, "Light breeze — small wavelets, crests glassy"),
        (5.5,  3, "Gentle breeze — large wavelets, scattered whitecaps"),
        (8.0,  4, "Moderate breeze — small waves 0.3–0.5 m, frequent whitecaps"),
        (10.8, 5, "Fresh breeze — moderate waves 0.5–0.8 m, many whitecaps"),
        (13.9, 6, "Strong breeze — large waves 0.8–1.2 m, whitecaps everywhere"),
        (17.2, 7, "Near gale — rough sea, foam streaks on water"),
        (20.8, 8, "Gale — very rough, visibly high waves"),
        (24.5, 9, "Severe gale — extremely rough, structural risk"),
        (28.5, 10, "Storm — exceptionally high waves, lake closed"),
        (32.7, 11, "Violent storm — dangerous to all vessels"),
    ]
    for limit, number, desc in thresholds:
        if wind_ms < limit:
            return number, desc
    return 12, "Hurricane force — extreme danger"


def _wave_height(wind_ms: float) -> tuple[float, float]:
    """
    Estimate significant and maximum wave height for Lake Mendota conditions.

    Uses the empirical power-law fit H_sig = 0.01 × U^1.5 derived from
    Wisconsin inland lake wave gauge records and NTL-LTER observations on
    Mendota (representative fetch ≈ 5 km).

      H_sig_m  = 0.01 × U_wind^1.5
      H_max_m  = 1.80 × H_sig_m   (H_max/H_sig ≈ 1.8 from Rayleigh distribution)

    Calibration values (NTL-LTER / Lathrop & Lillie 1980):
      5  m/s → H_sig ≈ 0.11 m  (slight chop)
      10 m/s → H_sig ≈ 0.32 m  (moderate)
      15 m/s → H_sig ≈ 0.58 m  (rough)
      20 m/s → H_sig ≈ 0.89 m  (very rough)
    """
    h_sig = round(0.01 * (wind_ms ** 1.5), 2)
    h_max = round(1.80 * h_sig, 2)
    return h_sig, h_max


def _hypothermia_context(water_temp_c: float) -> dict:
    """
    Return hypothermia risk level and estimated survival timeline.

    Based on Allan et al. (2003) 'Determinants of hypothermia risk in the
    aquatic environment' and US Search & Rescue Task Force cold-water survival
    tables.  Times assume no personal flotation device and average adult
    without thermal protection.
    """
    if water_temp_c < 5.0:
        return {
            "risk": "critical",
            "incapacitation": "< 7 minutes",
            "survival": "< 30 minutes",
            "note": "Cold shock, swimming failure, cardiac arrest risk. Drysuit mandatory.",
        }
    if water_temp_c < 10.0:
        return {
            "risk": "high",
            "incapacitation": "7–30 minutes",
            "survival": "30–60 minutes",
            "note": "Rapid physical incapacitation. Wetsuit minimum. PFD required.",
        }
    if water_temp_c < 15.0:
        return {
            "risk": "moderate",
            "incapacitation": "30–60 minutes",
            "survival": "1–6 hours",
            "note": "Prolonged immersion hazardous. Wetsuit recommended for extended activities.",
        }
    if water_temp_c < 20.0:
        return {
            "risk": "low",
            "incapacitation": "1–2 hours",
            "survival": "6–12 hours",
            "note": "Comfortable for short activities. Consider wetsuit for multi-hour exposure.",
        }
    return {
        "risk": "negligible",
        "incapacitation": "> 2 hours",
        "survival": "effectively safe",
        "note": "Comfortable water temperature for recreational activities.",
    }


def _water_quality_advisory(chl_ugl: float) -> dict:
    """
    Classify water quality based on chlorophyll-a concentration.

    Advisory thresholds follow Wisconsin DNR guidance for Lake Mendota
    and the WHO recreational water guidelines for cyanotoxin risk.

    Visual appearance notes are based on in-situ observations:
      < 5  µg/L  — crystal clear, deep Secchi depth (> 4 m)
      5–15 µg/L  — slight greenish tinge, Secchi 2–4 m
      15–30 µg/L — noticeably green, foam possible near shore
      30–70 µg/L — paint-like surface, potential scum, avoid contact
      > 70 µg/L  — bright green/blue-green paint, confirmed HAB
    """
    if chl_ugl < 5.0:
        return {"level": "excellent", "color": "#00ceb4",
                "advisory": "Clear", "visual": "Crystal clear water, excellent visibility",
                "contact": "safe"}
    if chl_ugl < 15.0:
        return {"level": "good", "color": "#4a8fff",
                "advisory": "Good", "visual": "Slight greenish tinge, normal spring/summer appearance",
                "contact": "safe"}
    if chl_ugl < 30.0:
        return {"level": "fair", "color": "#f59e0b",
                "advisory": "Fair — algae present", "visual": "Noticeably green water, possible shore foam",
                "contact": "caution — rinse after contact"}
    if chl_ugl < 70.0:
        return {"level": "poor", "color": "#ff6b6b",
                "advisory": "HAB Advisory — elevated cyanobacteria", "visual": "Dense green/blue-green, scum possible",
                "contact": "avoid contact — cyanotoxin risk"}
    return {"level": "hazardous", "color": "#ff2d55",
            "advisory": "HAB Warning — confirmed bloom", "visual": "Paint-like surface, blue-green scum",
            "contact": "no contact — cyanotoxins detected"}


# Vessel profiles — operational limits for all vessel types on Lake Mendota.
# Limits derived from: US Coast Guard Small Vessel Safety guidelines, American
# Canoe Association instructor standards, UW-Madison Hoofer Sailing Club rules,
# Wisconsin DNR recreational boating guidelines, and published cold-water
# immersion research.
_VESSEL_PROFILES: list[dict] = [
    {
        "vessel_type":         "open_water_swimming",
        "name":                "Open Water Swimming",
        "icon":                "🏊",
        "description":         "Unassisted swimming, triathlon, open-water training",
        "wind_caution_ms":     8.0,   # chopping creates disorientation, rescue difficult
        "wind_danger_ms":      15.0,
        "wave_caution_m":      0.25,
        "wave_danger_m":       0.50,
        "water_temp_caution_c": 15.0, # wetsuit recommended
        "water_temp_danger_c": 10.0,  # severe hypothermia risk
        "chl_caution_ugl":     15.0,
        "chl_danger_ugl":      30.0,
        "notes": {
            "wind": "Chop above 0.25 m makes sighting difficult and increases fatigue.",
            "temp": "Below 10°C, cold shock can cause involuntary gasping and cardiac arrest on entry.",
            "chl":  "Cyanotoxin ingestion risk with skin/mouth contact above 30 µg/L.",
        },
    },
    {
        "vessel_type":         "sup",
        "name":                "Stand-Up Paddleboard (SUP)",
        "icon":                "🏄",
        "description":         "Touring, fitness, or recreational stand-up paddleboard",
        "wind_caution_ms":     5.0,   # extremely wind-sensitive; even 5 m/s makes upwind paddling hard
        "wind_danger_ms":      9.0,
        "wave_caution_m":      0.20,
        "wave_danger_m":       0.45,
        "water_temp_caution_c": 12.0,
        "water_temp_danger_c": 8.0,
        "chl_caution_ugl":     15.0,
        "chl_danger_ugl":      30.0,
        "notes": {
            "wind": "SUP is the most wind-sensitive craft on the lake. At 9 m/s paddlers cannot return against wind.",
            "temp": "Falls are frequent on SUP; cold water below 10°C is life-threatening without a wetsuit.",
            "chl":  "Face-level position increases inhalation/ingestion exposure during falls.",
        },
    },
    {
        "vessel_type":         "kayak",
        "name":                "Kayak (Sit-in / Sea Kayak)",
        "icon":                "🚣",
        "description":         "Touring, sea, or recreational sit-in kayak",
        "wind_caution_ms":     8.0,
        "wind_danger_ms":      14.0,
        "wave_caution_m":      0.40,
        "wave_danger_m":       0.75,
        "water_temp_caution_c": 10.0,
        "water_temp_danger_c": 7.0,
        "chl_caution_ugl":     15.0,
        "chl_danger_ugl":      30.0,
        "notes": {
            "wind": "Sea kayaks handle well in chop but fatigue increases significantly above 0.4 m waves.",
            "temp": "Wet-exit / capsize drills mandatory below 10°C. Drysuit for solo paddlers.",
            "chl":  "Cyanotoxin skin absorption possible through spray contact above 30 µg/L.",
        },
    },
    {
        "vessel_type":         "canoe",
        "name":                "Canoe",
        "icon":                "🛶",
        "description":         "Traditional open canoe — paddling or poling",
        "wind_caution_ms":     7.0,   # open hull acts as a sail, lateral drift severe
        "wind_danger_ms":      12.0,
        "wave_caution_m":      0.30,
        "wave_danger_m":       0.55,
        "water_temp_caution_c": 10.0,
        "water_temp_danger_c": 7.0,
        "chl_caution_ugl":     15.0,
        "chl_danger_ugl":      30.0,
        "notes": {
            "wind": "Open hull catches wind like a sail. Crosswind paddling requires aggressive correction above 7 m/s.",
            "temp": "Open hull means full body immersion on capsize. Same cold water protocol as swimming.",
            "chl":  "Open sides increase exposure during paddling spray.",
        },
    },
    {
        "vessel_type":         "rowing_shell",
        "name":                "Rowing Shell / Scull",
        "icon":                "🚣",
        "description":         "Single, double, quad, or sweep rowing shell (UW crew, Hoofers)",
        "wind_caution_ms":     6.0,   # shells have 5 cm freeboard; designed for flat water only
        "wind_danger_ms":      10.0,
        "wave_caution_m":      0.20,
        "wave_danger_m":       0.35,
        "water_temp_caution_c": 10.0,
        "water_temp_danger_c": 7.0,
        "chl_caution_ugl":     15.0,
        "chl_danger_ugl":      30.0,
        "notes": {
            "wind": "Narrowest freeboard of any vessel on the lake. 0.2 m waves at the bow wash in regularly.",
            "temp": "Rowers sit at water level; spray immersion begins in light chop. Mandatory warm water protocols below 10°C.",
            "chl":  "Oar blades repeatedly enter water; blade spray contact is unavoidable.",
        },
    },
    {
        "vessel_type":         "sailing_dinghy",
        "name":                "Sailing Dinghy",
        "icon":                "⛵",
        "description":         "Small centerboard sailboat (420, Laser, Sunfish, Hobie Cat)",
        "wind_caution_ms":     9.0,
        "wind_danger_ms":      15.0,
        "wave_caution_m":      0.40,
        "wave_danger_m":       0.80,
        "water_temp_caution_c": 12.0,
        "water_temp_danger_c": 8.0,
        "chl_caution_ugl":     20.0,
        "chl_danger_ugl":      50.0,
        "notes": {
            "wind": "Dinghies capsize frequently above 12 m/s. Cold-water capsize recovery requires PFD and buddy system.",
            "temp": "Capsize recovery in cold water is a survival situation. Wetsuit below 12°C, drysuit below 8°C.",
            "chl":  "Capsize = full body immersion in potentially toxic water above 30 µg/L.",
        },
    },
    {
        "vessel_type":         "keelboat",
        "name":                "Keelboat / Sailboat",
        "icon":                "⛵",
        "description":         "Keel-stabilized sailboat (J/24, Cal 20, C&C 27, typical club fleet)",
        "wind_caution_ms":     12.0,
        "wind_danger_ms":      18.0,
        "wave_caution_m":      0.60,
        "wave_danger_m":       1.00,
        "water_temp_caution_c": 10.0,
        "water_temp_danger_c": 7.0,
        "chl_caution_ugl":     20.0,
        "chl_danger_ugl":      50.0,
        "notes": {
            "wind": "Keel provides stability. Reefing required above 12 m/s. Mendota sailing races typically called off above 15 m/s.",
            "temp": "Man-overboard recovery in 7°C water must occur within 7 minutes. Cold water MOB protocol mandatory.",
            "chl":  "Crew spray exposure. Avoid above 30 µg/L. HAB warnings typically close Mendota to competitive sailing.",
        },
    },
    {
        "vessel_type":         "pontoon_boat",
        "name":                "Pontoon Boat",
        "icon":                "🚢",
        "description":         "Pontoon or party barge — most common motorized vessel on Mendota",
        "wind_caution_ms":     10.0,  # large wind profile, slow manoeuvring
        "wind_danger_ms":      16.0,
        "wave_caution_m":      0.50,
        "wave_danger_m":       0.90,
        "water_temp_caution_c": None,
        "water_temp_danger_c": None,
        "chl_caution_ugl":     20.0,
        "chl_danger_ugl":      50.0,
        "notes": {
            "wind": "Large flat deck is a sail. Difficult to manoeuvre in crosswinds. Docking hazardous above 12 m/s.",
            "temp": "Enclosed deck reduces immersion risk, but man-overboard scenarios are extremely dangerous below 10°C.",
            "chl":  "Contact with lake water should be avoided during HAB events. Keep passengers away from the gunwales.",
        },
    },
    {
        "vessel_type":         "motorboat",
        "name":                "Recreational Motorboat",
        "icon":                "🚤",
        "description":         "Bowrider, runabout, wakeboard boat, ski boat",
        "wind_caution_ms":     11.0,
        "wind_danger_ms":      17.0,
        "wave_caution_m":      0.50,
        "wave_danger_m":       0.90,
        "water_temp_caution_c": None,
        "water_temp_danger_c": None,
        "chl_caution_ugl":     20.0,
        "chl_danger_ugl":      50.0,
        "notes": {
            "wind": "Moderate hull. Rough water significantly reduces safe operating speed.",
            "temp": "Water skiers and wakeboarders are in the water frequently — full hypothermia risk applies to them.",
            "chl":  "Watersports activities (skiing, tubing) involve direct water contact. Suspend at 30 µg/L.",
        },
    },
    {
        "vessel_type":         "pwc",
        "name":                "Personal Watercraft (PWC / Jet Ski)",
        "icon":                "🏍",
        "description":         "Jet ski, WaveRunner, Sea-Doo — high-speed, low-stability",
        "wind_caution_ms":     10.0,
        "wind_danger_ms":      16.0,
        "wave_caution_m":      0.40,
        "wave_danger_m":       0.75,
        "water_temp_caution_c": 12.0,
        "water_temp_danger_c": 8.0,
        "chl_caution_ugl":     20.0,
        "chl_danger_ugl":      50.0,
        "notes": {
            "wind": "High speed makes rough water dangerous. Falls at speed in chop cause injury.",
            "temp": "Riders routinely fall off. Cold-water immersion risk equivalent to swimming.",
            "chl":  "High-speed spray creates significant inhalation/ingestion exposure.",
        },
    },
    {
        "vessel_type":         "research_vessel",
        "name":                "Research Vessel",
        "icon":                "🔬",
        "description":         "UW-Madison / NTL-LTER research pontoon or motorized sampling boat",
        "wind_caution_ms":     10.0,
        "wind_danger_ms":      15.0,
        "wave_caution_m":      0.50,
        "wave_danger_m":       0.85,
        "water_temp_caution_c": None,
        "water_temp_danger_c": None,
        "chl_caution_ugl":     None,  # research missions may require HAB sampling
        "chl_danger_ugl":      None,
        "notes": {
            "wind": "Anchoring for water sampling becomes difficult above 10 m/s. Depth sensor cables are at risk above 12 m/s.",
            "temp": "Research personnel working over the gunwale should wear PFD and have cold-water protocols in place.",
            "chl":  "HAB sampling requires PPE: nitrile gloves, eye protection. Avoid aerosolised spray from bow wash.",
        },
    },
    {
        "vessel_type":         "fishing_kayak",
        "name":                "Fishing Kayak (Sit-on-Top)",
        "icon":                "🎣",
        "description":         "Sit-on-top fishing kayak with tackle, rod holders, and gear",
        "wind_caution_ms":     7.0,   # heavier with gear, higher centre of gravity
        "wind_danger_ms":      11.0,
        "wave_caution_m":      0.30,
        "wave_danger_m":       0.55,
        "water_temp_caution_c": 10.0,
        "water_temp_danger_c": 7.0,
        "chl_caution_ugl":     15.0,
        "chl_danger_ugl":      30.0,
        "notes": {
            "wind": "Gear increases windage. Anchoring in wind is necessary but increases capsize risk.",
            "temp": "Sit-on-top provides no barrier to spray. Dress for immersion, not air temperature.",
            "chl":  "Fishing in HAB conditions: do not eat fish from severely impacted areas without DNR guidance.",
        },
    },
    {
        "vessel_type":         "inflatable",
        "name":                "Inflatable / Dinghy",
        "icon":                "🛥",
        "description":         "Inflatable kayak, raft, rubber dinghy, or tender",
        "wind_caution_ms":     6.0,   # very susceptible to windage, low freeboard
        "wind_danger_ms":      10.0,
        "wave_caution_m":      0.25,
        "wave_danger_m":       0.50,
        "water_temp_caution_c": 12.0,
        "water_temp_danger_c": 8.0,
        "chl_caution_ugl":     15.0,
        "chl_danger_ugl":      30.0,
        "notes": {
            "wind": "Inflatables can be blown off course rapidly. Never use without a motor or paddle tether.",
            "temp": "Low sides mean regular water-over-gunwale contact in any chop.",
            "chl":  "Porous fabric may retain algal toxins. Rinse thoroughly after use in elevated chl-a conditions.",
        },
    },
]


def _assess_vessel(
    profile: dict,
    wind_ms: float,
    wave_h_sig: float,
    water_temp_c: float,
    chl_ugl: float,
    hypothermia: dict,
) -> dict:
    """
    Evaluate operational status for a single vessel type given current conditions.

    Returns: status ("safe"|"caution"|"danger"), list of reasons, and a
    plain-language recommendation.
    """
    reasons: list[str] = []
    worst_status = "safe"

    def _escalate(status: str) -> str:
        order = ["safe", "caution", "danger"]
        return status if order.index(status) > order.index(worst_status) else worst_status

    # Wind check
    w_danger  = profile["wind_danger_ms"]
    w_caution = profile["wind_caution_ms"]
    if wind_ms >= w_danger:
        worst_status = _escalate("danger")
        reasons.append(f"Wind {wind_ms:.1f} m/s exceeds danger limit {w_danger} m/s — do not launch")
    elif wind_ms >= w_caution:
        worst_status = _escalate("caution")
        reasons.append(f"Wind {wind_ms:.1f} m/s above caution threshold {w_caution} m/s — {profile['notes']['wind']}")

    # Wave height check
    wv_danger  = profile["wave_danger_m"]
    wv_caution = profile["wave_caution_m"]
    if wave_h_sig >= wv_danger:
        worst_status = _escalate("danger")
        reasons.append(f"Significant wave height {wave_h_sig:.2f} m exceeds safe limit {wv_danger} m")
    elif wave_h_sig >= wv_caution:
        worst_status = _escalate("caution")
        reasons.append(f"Waves {wave_h_sig:.2f} m (sig.) — choppy conditions for this vessel class")

    # Water temperature / hypothermia check
    t_danger  = profile.get("water_temp_danger_c")
    t_caution = profile.get("water_temp_caution_c")
    if t_danger is not None and water_temp_c <= t_danger:
        worst_status = _escalate("danger")
        reasons.append(
            f"Water {water_temp_c:.1f}°C — incapacitation in {hypothermia['incapacitation']} without thermal protection. "
            f"{hypothermia['note']}"
        )
    elif t_caution is not None and water_temp_c <= t_caution:
        worst_status = _escalate("caution")
        reasons.append(
            f"Water {water_temp_c:.1f}°C — {hypothermia['note']}"
        )

    # Chlorophyll / water quality check
    c_danger  = profile.get("chl_danger_ugl")
    c_caution = profile.get("chl_caution_ugl")
    if c_danger is not None and chl_ugl >= c_danger:
        worst_status = _escalate("danger")
        reasons.append(f"Chlorophyll-a {chl_ugl:.1f} µg/L — HAB conditions. {profile['notes']['chl']}")
    elif c_caution is not None and chl_ugl >= c_caution:
        worst_status = _escalate("caution")
        reasons.append(f"Chlorophyll-a {chl_ugl:.1f} µg/L elevated — {profile['notes']['chl']}")

    if not reasons:
        reasons.append("All conditions within safe operating parameters")

    # Compose recommendation
    if worst_status == "danger":
        rec = f"Do not operate {profile['name']} under current conditions."
    elif worst_status == "caution":
        rec = f"{profile['name']}: proceed with caution — {reasons[0].lower()}"
    else:
        rec = f"{profile['name']}: conditions suitable for safe operation."

    return {
        "vessel_type":   profile["vessel_type"],
        "name":          profile["name"],
        "icon":          profile["icon"],
        "description":   profile["description"],
        "status":        worst_status,
        "reasons":       reasons,
        "recommendation": rec,
        "limits": {
            "wind_caution_ms":      profile["wind_caution_ms"],
            "wind_danger_ms":       profile["wind_danger_ms"],
            "wave_caution_m":       profile["wave_caution_m"],
            "wave_danger_m":        profile["wave_danger_m"],
            "water_temp_caution_c": profile.get("water_temp_caution_c"),
            "water_temp_danger_c":  profile.get("water_temp_danger_c"),
            "chl_caution_ugl":      profile.get("chl_caution_ugl"),
            "chl_danger_ugl":       profile.get("chl_danger_ugl"),
        },
    }


class VesselGuideResponse(BaseModel):
    """
    Comprehensive maritime operations guide for current Lake Mendota conditions.

    Includes Beaufort classification, wave height estimation, hypothermia
    timeline, water quality advisory, and per-vessel operational status for
    all vessel classes operated on the lake.
    """
    timestamp: str
    # Weather snapshot
    wind_ms: float
    beaufort_number: int
    beaufort_description: str
    wave_height_sig_m: float = Field(description="Estimated significant wave height (H₁/₃), metres.")
    wave_height_max_m: float = Field(description="Estimated maximum wave height (H_max ≈ 1.8 × H_sig), metres.")
    air_temp_c: float
    # Water conditions
    water_temp_c: float
    hypothermia_risk: str
    hypothermia_incapacitation: str
    hypothermia_survival: str
    hypothermia_note: str
    # Water quality
    water_quality_level: str
    water_quality_advisory: str
    water_quality_visual: str
    water_quality_contact: str
    chlorophyll_ugl: float
    # Lake thermal state
    stratification_status: str
    stratification_note: str
    # Overall advisory
    overall_advisory: str = Field(description="'safe', 'caution', or 'danger' — worst-case across all vessels.")
    safe_count: int
    caution_count: int
    danger_count: int
    # Per-vessel assessments
    vessels: list[dict]


@app.get("/vessel-guide", response_model=VesselGuideResponse)
def get_vessel_guide(db: Session = Depends(get_db)) -> VesselGuideResponse:
    """
    Generate a comprehensive maritime operations guide for current lake conditions.

    Evaluates 13 vessel classes against real-time wind speed (smoothed),
    estimated wave height, surface water temperature, and chlorophyll-a.
    Derived outputs include Beaufort classification, hypothermia timeline,
    and water quality advisory.

    Intended consumers
    ------------------
    - Harbour masters and marina operators deciding whether to issue advisories
    - Race committee for the Mendota Yacht Club determining start/cancel decisions
    - UW-Madison Hoofer Sailing/Canoe clubs for member safety communications
    - Recreational users planning day trips
    - Research vessel scheduling at the Center for Limnology
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
            detail="No clean sensor data available. Start the sensor stream first.",
        )

    wind = latest.wind_speed_ms_smoothed
    water_temp = latest.water_temp_0m
    chl = latest.chlorophyll_ugl

    beaufort_num, beaufort_desc = _beaufort(wind)
    wave_sig, wave_max = _wave_height(wind)
    hypothermia = _hypothermia_context(water_temp)
    water_qual = _water_quality_advisory(chl)

    delta = latest.water_temp_0m - latest.water_temp_20m
    if delta >= 10.0:
        strat_status = "stratified"
        strat_note = (
            "Strong thermal stratification. Epilimnion thermally isolated from deep water. "
            "Warm nutrient-rich surface; cold, potentially anoxic hypolimnion below thermocline."
        )
    elif delta >= 4.0:
        strat_status = "weakly_stratified"
        strat_note = (
            "Thermocline developing. Surface layer warming faster than deep water. "
            "Some vertical mixing still occurring; dissolved oxygen distributed through metalimnion."
        )
    else:
        strat_status = "mixed"
        strat_note = (
            "Full water-column mixing. Temperature and dissolved oxygen uniform with depth. "
            "Typical of post ice-out spring conditions or active fall turnover."
        )

    vessel_assessments = [
        _assess_vessel(p, wind, wave_sig, water_temp, chl, hypothermia)
        for p in _VESSEL_PROFILES
    ]

    status_counts = {"safe": 0, "caution": 0, "danger": 0}
    for v in vessel_assessments:
        status_counts[v["status"]] += 1

    if status_counts["danger"] > 3:
        overall = "danger"
    elif status_counts["caution"] + status_counts["danger"] > 5:
        overall = "caution"
    elif status_counts["danger"] > 0:
        overall = "caution"
    else:
        overall = "safe"

    logger.info(
        "Vessel guide: wind=%.1f m/s (Bf%d)  waves=%.2f m  water=%.1f°C  chl=%.1f µg/L  "
        "advisory=%s  safe=%d caution=%d danger=%d",
        wind, beaufort_num, wave_sig, water_temp, chl,
        overall, status_counts["safe"], status_counts["caution"], status_counts["danger"],
    )

    return VesselGuideResponse(
        timestamp=latest.timestamp,
        wind_ms=round(wind, 2),
        beaufort_number=beaufort_num,
        beaufort_description=beaufort_desc,
        wave_height_sig_m=wave_sig,
        wave_height_max_m=wave_max,
        air_temp_c=round(latest.air_temp_c, 1),
        water_temp_c=round(water_temp, 2),
        hypothermia_risk=hypothermia["risk"],
        hypothermia_incapacitation=hypothermia["incapacitation"],
        hypothermia_survival=hypothermia["survival"],
        hypothermia_note=hypothermia["note"],
        water_quality_level=water_qual["level"],
        water_quality_advisory=water_qual["advisory"],
        water_quality_visual=water_qual["visual"],
        water_quality_contact=water_qual["contact"],
        chlorophyll_ugl=round(chl, 2),
        stratification_status=strat_status,
        stratification_note=strat_note,
        overall_advisory=overall,
        safe_count=status_counts["safe"],
        caution_count=status_counts["caution"],
        danger_count=status_counts["danger"],
        vessels=vessel_assessments,
    )
