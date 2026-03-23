"""
tests/test_main.py — Sentinel-Stream Mendota Edition — API Test Suite

Covers the full request lifecycle: multivariate schema validation, outlier
detection (wind AND chlorophyll paths), rolling-average accuracy, forecast
minimum-data guard, and status health.

Each test runs against a **fresh in-memory SQLite database** injected via
FastAPI's dependency-override mechanism.  StaticPool ensures all connections
share the same in-memory database within a single test — without it, each
new connection would see an empty schema.

The rolling_buffer deque is also cleared before each test to prevent
smoothing state from leaking between test cases.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import (
    Base,
    BuoyReading,
    app,
    get_db,
    rolling_buffer,
)

# ---------------------------------------------------------------------------
# In-memory test database factory
# ---------------------------------------------------------------------------

def make_test_engine():
    """
    Create a fresh SQLite in-memory engine with all DDL applied.

    StaticPool forces all connections to share one underlying connection,
    so the tables created by Base.metadata.create_all() are visible to
    every subsequent session — necessary for in-memory SQLite testing.
    """
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=test_engine)
    return test_engine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    """
    Pytest fixture that yields a FastAPI TestClient backed by a fresh
    in-memory database and a cleared rolling-window buffer.

    The dependency override replaces the production get_db with one that
    yields sessions from the ephemeral in-memory engine, so no test
    writes to mendota_buoy.db.
    """
    test_engine = make_test_engine()
    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=test_engine
    )

    def override_get_db():
        with TestingSessionLocal() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    rolling_buffer.clear()

    with TestClient(app, raise_server_exceptions=True) as test_client:
        # Clear again AFTER lifespan runs — the lifespan seeds rolling_buffer
        # from the production DB (mendota_buoy.db), which would contaminate
        # smoothing-math tests with real data from previous manual runs.
        rolling_buffer.clear()
        yield test_client

    app.dependency_overrides.clear()
    rolling_buffer.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_payload(**overrides) -> dict:
    """
    Return a minimal valid Lake Mendota buoy payload.
    Any field can be overridden via keyword arguments.
    """
    base: dict = {
        "timestamp": "2026-03-22T20:27:00Z",
        "location": "Lake Mendota — 1.5 km NE of Picnic Point, Madison, WI",
        "lat": 43.0988,
        "long": -89.4045,
        "air_temp_c": 12.5,
        "wind_speed_ms": 5.2,
        "water_temp_profile": {
            "0m": 14.0,
            "5m": 10.5,
            "10m": 7.2,
            "20m": 5.1,
        },
        "chlorophyll_ugl": 8.5,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestIngestEndpoint:
    """Tests for POST /ingest."""

    def test_ingest_valid_packet(self, client: TestClient) -> None:
        """
        A well-formed multivariate buoy payload should be accepted with
        HTTP 200 and return smoothed_wind_ms and surface_water_temp_c.
        """
        response = client.post("/ingest", json=_valid_payload())

        assert response.status_code == 200, response.text

        body = response.json()
        assert body["status"] == "ok"
        assert isinstance(body["smoothed_wind_ms"], float)
        assert isinstance(body["surface_water_temp_c"], float)
        assert body["is_outlier"] is False

    def test_ingest_wind_outlier_flagged(self, client: TestClient) -> None:
        """
        A packet with wind_speed_ms = 25.0 m/s exceeds the 20 m/s inland
        lake outlier threshold.  The API must accept it (HTTP 200) but set
        is_outlier=True so it is excluded from smoothing and analytics.
        """
        payload = _valid_payload(wind_speed_ms=25.0)
        response = client.post("/ingest", json=payload)

        assert response.status_code == 200, response.text
        assert response.json()["is_outlier"] is True

    def test_ingest_chlorophyll_outlier_flagged(self, client: TestClient) -> None:
        """
        A packet with chlorophyll_ugl = 150.0 exceeds the 100 µg/L threshold
        for fluorometer fouling.  The API must flag it as an outlier even
        when wind speed is within bounds — either variable triggers the flag.
        """
        payload = _valid_payload(chlorophyll_ugl=150.0)
        response = client.post("/ingest", json=payload)

        assert response.status_code == 200, response.text
        assert response.json()["is_outlier"] is True, (
            "Expected is_outlier=True for chlorophyll_ugl=150.0 µg/L"
        )

    def test_rolling_average_math(self, client: TestClient) -> None:
        """
        Send exactly 10 clean packets with known wind_speed_ms values and
        verify the smoothed_wind_ms on the 10th packet equals their mean.

        This pins the core correctness invariant of the smoothing layer:
        a simple arithmetic mean of the last WINDOW_SIZE clean readings.
        """
        wind_values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        expected_avg = sum(wind_values) / len(wind_values)  # 5.5

        last_response = None
        for w in wind_values:
            last_response = client.post("/ingest", json=_valid_payload(wind_speed_ms=w))
            assert last_response.status_code == 200

        body = last_response.json()
        assert abs(body["smoothed_wind_ms"] - expected_avg) < 1e-6, (
            f"Expected smoothed_wind_ms={expected_avg}, got {body['smoothed_wind_ms']}"
        )

    def test_outlier_excluded_from_rolling_buffer(self, client: TestClient) -> None:
        """
        An outlier packet must NOT enter the rolling buffer.

        Send 5 clean packets (wind=4.0), 1 wind outlier (wind=25.0), then
        4 clean packets (wind=6.0).  The buffer should contain 9 clean values
        [4,4,4,4,4,6,6,6,6] with mean = (5*4 + 4*6) / 9 ≈ 4.888.

        This guards the invariant that outlier quarantine works across both
        fault types — a wind outlier must not enter the wind smoothing buffer.
        """
        for _ in range(5):
            client.post("/ingest", json=_valid_payload(wind_speed_ms=4.0))

        client.post("/ingest", json=_valid_payload(wind_speed_ms=25.0))  # outlier

        last_response = None
        for _ in range(4):
            last_response = client.post("/ingest", json=_valid_payload(wind_speed_ms=6.0))

        expected = (5 * 4.0 + 4 * 6.0) / 9  # ≈ 4.888
        body = last_response.json()
        assert abs(body["smoothed_wind_ms"] - expected) < 1e-4, (
            f"Expected {expected:.4f}, got {body['smoothed_wind_ms']}"
        )
        assert body["is_outlier"] is False

    def test_surface_water_temp_returned(self, client: TestClient) -> None:
        """
        The /ingest response must echo the ingested surface (0m) water
        temperature so callers can confirm the vertical profile was stored.
        """
        payload = _valid_payload()
        payload["water_temp_profile"]["0m"] = 16.7
        response = client.post("/ingest", json=payload)

        assert response.status_code == 200
        assert abs(response.json()["surface_water_temp_c"] - 16.7) < 1e-3


class TestForecastEndpoint:
    """Tests for GET /forecast."""

    def test_forecast_insufficient_data(self, client: TestClient) -> None:
        """
        /forecast must return HTTP 422 on an empty database — not enough
        signal to produce a meaningful linear regression.
        """
        response = client.get("/forecast")
        assert response.status_code == 422, (
            f"Expected 422 on empty DB, got {response.status_code}"
        )

    def test_forecast_returns_valid_structure(self, client: TestClient) -> None:
        """
        After ingesting 15 clean records with a rising surface temperature
        trend, /forecast must return a valid response with all required fields
        and trend='rising'.
        """
        for i in range(15):
            payload = _valid_payload(
                timestamp=f"2026-03-22T12:{i:02d}:00Z",
                wind_speed_ms=4.0,
            )
            # Rising surface temperature: 0.2 °C per reading
            payload["water_temp_profile"]["0m"] = 13.0 + i * 0.2
            client.post("/ingest", json=payload)

        response = client.get("/forecast")
        assert response.status_code == 200, response.text

        body = response.json()
        assert "current_surface_temp_c" in body
        assert "forecast_5min_surface_temp_c" in body
        assert body["trend"] in {"rising", "falling", "stable"}
        assert 0.0 <= body["r_squared"] <= 1.0
        assert body["records_used"] >= 10
        assert body["trend"] == "rising", (
            f"Expected trend='rising' for a steadily increasing surface temp, "
            f"got '{body['trend']}'"
        )


class TestStatusEndpoint:
    """Tests for GET /status."""

    def test_status_returns_healthy(self, client: TestClient) -> None:
        """
        /status must return HTTP 200 with status='healthy' even on an empty
        database — it is the Docker healthcheck target and must never 500.
        """
        response = client.get("/status")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "healthy"
        assert isinstance(body["record_count"], int)
        assert "Mendota" in body["system"]

    def test_status_record_count_increments(self, client: TestClient) -> None:
        """
        After ingesting a reading the record_count in /status must increment
        by exactly 1.
        """
        before = client.get("/status").json()["record_count"]
        client.post("/ingest", json=_valid_payload())
        after = client.get("/status").json()["record_count"]
        assert after == before + 1


class TestPydanticValidation:
    """Tests for Pydantic schema validation on POST /ingest."""

    def test_missing_required_field_rejected(self, client: TestClient) -> None:
        """
        A payload missing air_temp_c must be rejected with HTTP 422 before
        touching the database — Pydantic validates at the boundary.
        """
        payload = _valid_payload()
        del payload["air_temp_c"]
        response = client.post("/ingest", json=payload)
        assert response.status_code == 422

    def test_latitude_out_of_range_rejected(self, client: TestClient) -> None:
        """
        A latitude outside the Lake Mendota plausibility range (42.9–43.2)
        must be rejected with HTTP 422 — catching GPS spoofing or unit errors.
        """
        response = client.post("/ingest", json=_valid_payload(lat=0.0))
        assert response.status_code == 422

    def test_negative_wind_rejected(self, client: TestClient) -> None:
        """
        Negative wind speed is physically impossible and must be rejected.
        """
        response = client.post("/ingest", json=_valid_payload(wind_speed_ms=-1.0))
        assert response.status_code == 422

    def test_negative_chlorophyll_rejected(self, client: TestClient) -> None:
        """
        Negative chlorophyll concentration is physically impossible and must
        be rejected at the Pydantic boundary.
        """
        response = client.post("/ingest", json=_valid_payload(chlorophyll_ugl=-5.0))
        assert response.status_code == 422

    def test_empty_body_rejected(self, client: TestClient) -> None:
        """An empty JSON body must be rejected with HTTP 422."""
        response = client.post("/ingest", json={})
        assert response.status_code == 422


class TestReadingsEndpoint:
    """Tests for GET /readings."""

    def test_readings_empty_db(self, client: TestClient) -> None:
        """
        /readings on an empty database must return HTTP 200 with count=0
        and an empty list — not a 404 or 500.
        """
        response = client.get("/readings")
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 0
        assert body["readings"] == []

    def test_readings_includes_water_temp_profile(self, client: TestClient) -> None:
        """
        Each reading returned by /readings must include a water_temp_profile
        dict with all four depth keys from the NTL-LTER thermistor chain.
        """
        client.post("/ingest", json=_valid_payload())
        response = client.get("/readings?n=1")
        assert response.status_code == 200

        reading = response.json()["readings"][0]
        profile = reading["water_temp_profile"]
        for depth in ("0m", "5m", "10m", "20m"):
            assert depth in profile, f"Missing depth key '{depth}' in water_temp_profile"
            assert isinstance(profile[depth], float)
