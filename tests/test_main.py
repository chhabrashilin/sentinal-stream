"""
tests/test_main.py — Sentinel-Stream API Test Suite

Covers the full request lifecycle: validation, outlier detection,
rolling-average accuracy, forecast minimum-data guard, and status health.

Each test runs against a **fresh in-memory SQLite database** injected via
FastAPI's dependency-override mechanism.  This ensures complete test
isolation — no shared state between tests, no leftover records from a
previous run, and no touching the production `weather_data.db` file.

The rolling_buffer deque in main.py is also cleared before each test to
prevent smoothing state from leaking between test cases.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Import the app and the objects we need to override / reset.
from main import (
    Base,
    SessionLocal,
    WeatherReading,
    app,
    get_db,
    rolling_buffer,
)

# ---------------------------------------------------------------------------
# In-memory test database factory
# ---------------------------------------------------------------------------

def make_test_engine():
    """
    Create a fresh SQLite in-memory engine and run all DDL migrations.

    Using ``check_same_thread=False`` mirrors the production engine config
    and is required for SQLite to work with FastAPI's threaded test runner.
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

    The dependency override replaces the production ``get_db`` dependency
    with one that yields sessions from the ephemeral in-memory engine,
    so no test writes to ``weather_data.db``.
    """
    # Each fixture invocation gets its own isolated engine.
    test_engine = make_test_engine()
    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=test_engine
    )

    def override_get_db():
        with TestingSessionLocal() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db

    # Clear the in-process rolling buffer so smoothing state from a previous
    # test cannot influence the current one.
    rolling_buffer.clear()

    with TestClient(app, raise_server_exceptions=True) as test_client:
        yield test_client

    # Restore the original dependency after the test completes.
    app.dependency_overrides.clear()
    rolling_buffer.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_payload(**overrides) -> dict:
    """
    Return a minimal valid sensor payload for the Port of Long Beach buoy.
    Any field can be overridden via keyword arguments.
    """
    base = {
        "timestamp": "2024-06-01T12:00:00Z",
        "lat": 33.7541,
        "long": -118.2130,
        "temp_c": 18.5,
        "pressure_hpa": 1013.25,
        "wind_ms": 5.2,
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
        A well-formed sensor payload should be accepted with HTTP 200 and
        return a smoothed_wind value in the response body.
        """
        response = client.post("/ingest", json=_valid_payload())

        assert response.status_code == 200, response.text

        body = response.json()
        assert body["status"] == "ok"
        assert isinstance(body["smoothed_wind"], float)
        assert body["is_outlier"] is False

    def test_ingest_outlier_flagged(self, client: TestClient) -> None:
        """
        A packet with wind_ms = 55.0 m/s exceeds the 30 m/s outlier
        threshold.  The API should accept it (HTTP 200) but set is_outlier=True
        so that downstream consumers can filter it from analytics.
        """
        payload = _valid_payload(wind_ms=55.0)
        response = client.post("/ingest", json=payload)

        assert response.status_code == 200, response.text

        body = response.json()
        assert body["is_outlier"] is True, (
            "Expected is_outlier=True for wind_ms=55.0 m/s"
        )

    def test_rolling_average_math(self, client: TestClient) -> None:
        """
        Send exactly 10 non-outlier packets with known wind_ms values and
        verify that the smoothed_wind returned on the 10th packet equals
        the arithmetic mean of all 10 values.

        This test pins the core correctness invariant of the smoothing layer:
        the rolling average must be the mean of the last WINDOW_SIZE clean
        readings, not a weighted or exponential average.
        """
        wind_values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        expected_average = sum(wind_values) / len(wind_values)  # 5.5

        last_response = None
        for wind in wind_values:
            last_response = client.post("/ingest", json=_valid_payload(wind_ms=wind))
            assert last_response.status_code == 200

        body = last_response.json()
        assert abs(body["smoothed_wind"] - expected_average) < 1e-6, (
            f"Expected smoothed_wind={expected_average}, got {body['smoothed_wind']}"
        )

    def test_outlier_excluded_from_rolling_buffer(self, client: TestClient) -> None:
        """
        An outlier packet must NOT enter the rolling buffer.  Send 5 clean
        packets, 1 outlier, then 4 more clean packets.  The smoothed_wind
        after the final packet should equal the mean of the 9 clean packets
        (not 10, because the buffer has only 9 clean entries).

        This guards the invariant that outliers are quarantined from
        smoothing state.
        """
        # 5 clean packets with wind = 4.0
        for _ in range(5):
            client.post("/ingest", json=_valid_payload(wind_ms=4.0))

        # 1 outlier — must NOT enter the buffer
        client.post("/ingest", json=_valid_payload(wind_ms=60.0))

        # 4 more clean packets with wind = 6.0
        last_response = None
        for _ in range(4):
            last_response = client.post("/ingest", json=_valid_payload(wind_ms=6.0))

        # Buffer should contain [4, 4, 4, 4, 4, 6, 6, 6, 6] — 9 clean values
        # mean = (5*4 + 4*6) / 9 = (20 + 24) / 9 = 44/9 ≈ 4.888...
        expected = (5 * 4.0 + 4 * 6.0) / 9
        body = last_response.json()
        assert abs(body["smoothed_wind"] - expected) < 1e-4, (
            f"Expected {expected:.4f}, got {body['smoothed_wind']}"
        )
        assert body["is_outlier"] is False


class TestForecastEndpoint:
    """Tests for GET /forecast."""

    def test_forecast_insufficient_data(self, client: TestClient) -> None:
        """
        The forecast endpoint should return HTTP 422 when the database
        contains fewer than 10 clean records, since a linear regression
        on fewer points would be statistically meaningless.
        """
        response = client.get("/forecast")

        assert response.status_code == 422, (
            f"Expected 422 on empty DB, got {response.status_code}: {response.text}"
        )

    def test_forecast_returns_valid_structure(self, client: TestClient) -> None:
        """
        After ingesting enough clean records, /forecast should return a
        response with all required fields and a sensible trend value.
        """
        # Ingest 15 readings with a slight rising temperature trend.
        for i in range(15):
            client.post(
                "/ingest",
                json=_valid_payload(
                    timestamp=f"2024-06-01T12:{i:02d}:00Z",
                    temp_c=18.0 + i * 0.1,  # 0.1 °C per reading → rising
                    wind_ms=5.0,
                ),
            )

        response = client.get("/forecast")
        assert response.status_code == 200, response.text

        body = response.json()
        assert "current_temp" in body
        assert "forecast_5min_temp" in body
        assert body["trend"] in {"rising", "falling", "stable"}
        assert 0.0 <= body["r_squared"] <= 1.0
        assert body["records_used"] >= 10


class TestStatusEndpoint:
    """Tests for GET /status."""

    def test_status_endpoint(self, client: TestClient) -> None:
        """
        /status should always return HTTP 200 with status='healthy' even
        on an empty database — it is the Docker healthcheck target and must
        never return a non-2xx code under normal operating conditions.
        """
        response = client.get("/status")

        assert response.status_code == 200, response.text

        body = response.json()
        assert body["status"] == "healthy"
        assert isinstance(body["record_count"], int)
        assert "system" in body

    def test_status_record_count_increments(self, client: TestClient) -> None:
        """
        After ingesting a reading the record count returned by /status
        should increment by exactly 1.
        """
        before = client.get("/status").json()["record_count"]

        client.post("/ingest", json=_valid_payload())

        after = client.get("/status").json()["record_count"]
        assert after == before + 1


class TestPydanticValidation:
    """Tests for Pydantic schema validation on POST /ingest."""

    def test_pydantic_validation_missing_field(self, client: TestClient) -> None:
        """
        A payload missing a required field (temp_c) should be rejected
        with HTTP 422 Unprocessable Entity — FastAPI / Pydantic validates
        before the handler runs, so no database write should occur.
        """
        incomplete_payload = {
            "timestamp": "2024-06-01T12:00:00Z",
            "lat": 33.7541,
            "long": -118.2130,
            # temp_c intentionally omitted
            "pressure_hpa": 1013.25,
            "wind_ms": 5.2,
        }
        response = client.post("/ingest", json=incomplete_payload)

        assert response.status_code == 422, (
            f"Expected 422 for missing temp_c, got {response.status_code}"
        )

    def test_pydantic_validation_out_of_range_lat(self, client: TestClient) -> None:
        """
        Latitude outside [-90, 90] must be rejected — a safety guard against
        corrupted GPS fixes that would place the buoy on another planet.
        """
        response = client.post("/ingest", json=_valid_payload(lat=999.0))
        assert response.status_code == 422

    def test_pydantic_validation_negative_wind(self, client: TestClient) -> None:
        """
        Negative wind speed is physically impossible and indicates a sensor
        fault.  Pydantic's ``ge=0.0`` constraint should reject it.
        """
        response = client.post("/ingest", json=_valid_payload(wind_ms=-1.0))
        assert response.status_code == 422

    def test_pydantic_validation_empty_body(self, client: TestClient) -> None:
        """An empty JSON body should be rejected with HTTP 422."""
        response = client.post("/ingest", json={})
        assert response.status_code == 422


class TestReadingsEndpoint:
    """Tests for GET /readings."""

    def test_readings_empty_db(self, client: TestClient) -> None:
        """On an empty database /readings should return count=0 and an empty list."""
        response = client.get("/readings")
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 0
        assert body["readings"] == []

    def test_readings_returns_correct_count(self, client: TestClient) -> None:
        """
        After ingesting 5 records, GET /readings?n=3 should return exactly
        3 records (the most recent 3).
        """
        for i in range(5):
            client.post(
                "/ingest",
                json=_valid_payload(timestamp=f"2024-06-01T12:0{i}:00Z"),
            )

        response = client.get("/readings", params={"n": 3})
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 3
        assert len(body["readings"]) == 3
