# Sentinel-Stream: Lake Mendota Digital Twin

Demo recording: https://youtu.be/jjXKpOC2HC8

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-18.3-61dafb?logo=react&logoColor=black)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)
![Tests](https://img.shields.io/badge/tests-17%20passing-brightgreen)

A full-stack environmental intelligence pipeline and live dashboard using UW-Madison SSEC and NTL-LTER Lake Mendota Buoy data (43.0988°N, 89.4045°W).

Sensor telemetry is ingested at 1 Hz, validated, filtered for outliers, smoothed, persisted, and served through a REST API. A React dashboard visualizes wind, water temperature at 4 depths, a 5-minute ML forecast, thermal stratification status, and real-time lake activity safety assessments.

---

## Data Sources

| Component | Status | Notes |
|---|---|---|
| `GET /buoy-status` | Live | Proxies `metobs.ssec.wisc.edu` directly |
| Sensor telemetry | Synthetic | Physical buoy is off-station until ~May. `sensor_emulator.py` generates calibrated 1 Hz data matching late-March post ice-out conditions. |
| `fetch_ssec.py --live` | Ready | When the buoy returns, this replaces the emulator with real hardware telemetry. No pipeline changes needed. |

---

## Running Locally

**Prerequisites:** Python 3.10+, Node.js 18+

```bash
# Terminal 1: API
pip install -r requirements.txt
uvicorn main:app --reload

# Terminal 2: Sensor emulator
python sensor_emulator.py

# Terminal 3: Dashboard
cd frontend
npm install
npm run dev
```

Dashboard at `http://localhost:5173` · API docs at `http://localhost:8000/docs`

> Wait ~15 seconds after starting the emulator before the forecast and stratification panels populate.

### Docker

```bash
docker-compose up --build
# API at :8000 — sensor starts automatically once API passes health check
```

---

## API

| Method | Path | Description |
|---|---|---|
| `POST` | `/ingest` | Ingest and process a buoy telemetry packet |
| `GET` | `/forecast` | 5-minute surface temperature forecast |
| `GET` | `/stratification` | Thermocline strength and stratification status |
| `GET` | `/buoy-status` | Live proxy to the SSEC MetObs API |
| `GET` | `/status` | Health probe (Docker healthcheck target) |
| `GET` | `/readings?n=20` | Last N records with full depth profile |
| `GET` | `/docs` | Interactive OpenAPI documentation |

### Ingest pipeline

Each packet passes through 5 steps:

1. **Pydantic validation** — rejects physically impossible values (negative wind, coordinates outside Lake Mendota bounding box, etc.)
2. **Outlier detection** — flags `is_outlier=True` if `wind_speed_ms > 20.0` or `chlorophyll_ugl > 100.0`
3. **Rolling buffer** — only clean readings enter the 10-point `deque`. Outliers are stored but never corrupt the smoothing state.
4. **Smoothed wind** — `mean(rolling_buffer)`, falls back to raw on cold start
5. **Persistence** — all fields written to SQLite including raw wind, smoothed wind, 4 depth temperatures, chlorophyll, and outlier flag

### Forecast

Fits `sklearn.LinearRegression` on the last 100 clean records `(time → surface_temp)` and predicts 5 minutes ahead. Returns HTTP 422 if fewer than 10 clean records exist. Trend label (`rising` / `falling` / `stable`) uses a ±0.1°C dead-band to prevent noise-driven flipping.

### Stratification

```
Δt = water_temp_0m − water_temp_20m
```

| Δt | Status | Meaning |
|---|---|---|
| ≥ 10°C | `stratified` | Epilimnion isolated; elevated HAB risk |
| 4–10°C | `weakly_stratified` | Thermocline developing |
| < 4°C | `mixed` | Full column turnover (current late-March state) |

---

## Sensor Emulator

Calibrated to **late-March post ice-out** conditions. Lake Mendota sits nearly isothermal at ~4°C after ice-off before spring stratification begins.

| Sensor | Baseline | Noise σ |
|---|---|---|
| Air temperature | 6.0°C | ±0.25°C |
| Wind speed | 6.0 m/s | ±0.4 m/s |
| Water temp 0m | 4.0°C | ±0.15°C |
| Water temp 5m | 3.8°C | ±0.15°C |
| Water temp 10m | 3.6°C | ±0.15°C |
| Water temp 20m | 3.4°C | ±0.15°C |
| Chlorophyll-a | 6.5 µg/L | ±0.8 µg/L |

Three fault modes exercise pipeline resilience:

| Mode | Default rate | Simulates |
|---|---|---|
| Gaussian noise | Every packet | Instrument noise |
| Packet drop | 10% | RF loss between buoy and shore station |
| Outlier injection | 5% | Anemometer saturation or fluorometer fouling |

Rates are overridable at runtime:
```bash
PACKET_DROP_RATE=0.20 OUTLIER_RATE=0.10 python sensor_emulator.py
```

---

## Tests

```bash
pytest tests/ -v
```

17 tests across 5 classes, all passing. Each test runs against a fresh in-memory SQLite database via `StaticPool` + `app.dependency_overrides[get_db]` — no shared state, no writes to disk.

| Class | Coverage |
|---|---|
| `TestIngestEndpoint` | Valid ingest, wind outlier, chlorophyll outlier, rolling average math, outlier excluded from buffer, surface temp in response |
| `TestForecastEndpoint` | HTTP 422 on insufficient data, rising trend detection |
| `TestStatusEndpoint` | Health probe, record count increments |
| `TestPydanticValidation` | Missing field, out-of-range lat, negative wind, negative chlorophyll, empty body |
| `TestReadingsEndpoint` | Empty DB, depth profile keys present |

---

## SSEC Integration

`scripts/fetch_ssec.py` connects to the real SSEC MetObs REST API.

```bash
# Check if the physical buoy is online
python scripts/fetch_ssec.py --status

# Seed the database with real summer 2024 data
python scripts/fetch_ssec.py --historical --begin 2024-07-01 --end 2024-07-31

# Stream live hardware telemetry (available ~May–November)
python scripts/fetch_ssec.py --live
```

---

## Design Notes

**Linear Regression for forecasting** — fits 100 records in under 1 ms, produces an interpretable slope (°C/s), and returns R² so callers can assess confidence. Appropriate for a slowly-changing limnological signal on a 5-minute horizon.

**SQLite** — zero configuration, single-file portability, mirrors local storage on buoy shore-station hardware. Swappable for TimescaleDB or InfluxDB by changing `DATABASE_URL`.

**Outliers stored, not discarded** — quarantined from the rolling buffer and forecast regression, but kept in the database. Discarding them destroys the forensic record needed to correlate false HAB alerts with sensor fouling events.

**Depth columns over JSON** — `water_temp_0m`, `water_temp_5m`, `water_temp_10m`, `water_temp_20m` as individual Float columns allows direct SQL aggregation for stratification queries without deserializing blobs.

---

## Stack

| Layer | Technology |
|---|---|
| API | FastAPI 0.111 + uvicorn |
| Validation | Pydantic 2.7 |
| ORM | SQLAlchemy 2.0 |
| ML | scikit-learn 1.4 |
| Frontend | React 18 + Vite + Recharts |
| Container | Docker + Compose |
| Testing | pytest + httpx |

---

*UW-Madison · [NTL-LTER](https://lter.limnology.wisc.edu/) · Lake Mendota*
