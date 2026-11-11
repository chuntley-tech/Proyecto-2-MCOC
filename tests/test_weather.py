"""Pruebas del pipeline meteorológico con respuestas FICTICIAS (no son datos de Open-Meteo)."""

import json
from urllib.parse import parse_qs, urlparse

import numpy as np
import pytest

from weather import (coverage, ensemble_members, fill_tail, from_open_meteo, latest_before, list_snapshots,
                     load_snapshot, save_snapshot)
from weather.open_meteo import build_request
from weather.series import HOUR, synthetic_series, to_epoch

START = "2026-11-27T07:00Z"


def fake_payload(first="2026-11-20T00:00", hours=240, members=0):
    """Respuesta con la forma de Open-Meteo; valores inventados para probar el código."""
    t0 = to_epoch(first)
    times = [np.datetime_as_string(np.datetime64(int(t0 + i * HOUR), "s"), unit="m") for i in range(hours)]
    hour = np.arange(hours) % 24
    hourly = {"time": times,
              "temperature_2m": list(np.round(10 + 4 * np.sin(2 * np.pi * (hour - 15) / 24), 2)),
              "wind_speed_10m": [3.0] * hours,
              "shortwave_radiation": list(np.round(np.clip(600 * np.sin(np.pi * (hour - 10) / 13), 0, None), 1))}
    units = {"time": "iso8601", "temperature_2m": "°C", "wind_speed_10m": "m/s", "shortwave_radiation": "W/m²"}
    for m in range(1, members + 1):
        hourly[f"temperature_2m_member{m:02d}"] = [v + m for v in hourly["temperature_2m"]]
        hourly[f"wind_speed_10m_member{m:02d}"] = hourly["wind_speed_10m"]
        hourly[f"shortwave_radiation_member{m:02d}"] = hourly["shortwave_radiation"]
    return {"latitude": -41.25, "longitude": -73.25, "utc_offset_seconds": 0, "timezone": "GMT",
            "hourly_units": units, "hourly": hourly}


def raw(payload):
    return json.dumps(payload).encode()


def test_request_uses_variables_units_and_gmt():
    request = build_request("forecast", -41.222539, -73.295603)
    query = parse_qs(urlparse(request["url"]).query)
    assert request["url"].startswith("https://api.open-meteo.com/v1/forecast")
    assert query["hourly"] == ["temperature_2m,wind_speed_10m,shortwave_radiation"]
    assert query["wind_speed_unit"] == ["ms"] and query["timezone"] == ["GMT"]
    assert query["forecast_days"] == ["16"]
    archive = build_request("archive", -41.2, -73.3, start_date="2025-11-27", end_date="2025-12-11")
    assert "archive-api" in archive["url"] and "forecast_days" not in archive["params"]
    with pytest.raises(ValueError):
        build_request("archive", -41.2, -73.3)
    with pytest.raises(ValueError):
        build_request("ensemble", -41.2, -73.3)
    with pytest.raises(ValueError):
        build_request("nowcast", -41.2, -73.3)
    with pytest.raises(ValueError, match="16"):
        build_request("forecast", -41.2, -73.3, forecast_days=17)
    previous = build_request("previous_runs", -41.2, -73.3, previous_day=3)
    assert previous["params"]["hourly"] == (
        "temperature_2m_previous_day3,wind_speed_10m_previous_day3,shortwave_radiation_previous_day3"
    )


def test_snapshot_is_immutable_and_hash_checked(tmp_path):
    request = build_request("forecast", -41.222539, -73.295603)
    folder = save_snapshot(raw(fake_payload()), request, root=tmp_path, retrieved_at="2026-11-20T12:00Z")
    assert folder.name == "2026-11-20T1200Z_forecast"
    metadata, payload = load_snapshot(folder)
    assert metadata["retrieved_at"] == "2026-11-20T12:00:00Z"
    assert metadata["variables"] == ["temperature_2m", "wind_speed_10m", "shortwave_radiation"]
    assert metadata["request_url"] == request["url"] and len(metadata["sha256"]) == 64
    with pytest.raises(FileExistsError):
        save_snapshot(raw(fake_payload()), request, root=tmp_path, retrieved_at="2026-11-20T12:00Z")
    (folder / "forecast.json").write_bytes(raw(fake_payload(hours=10)))
    with pytest.raises(ValueError, match="hash"):
        load_snapshot(folder)


def test_latest_before_reproduces_what_was_known(tmp_path):
    request = build_request("forecast", -41.2, -73.3)
    for stamp in ("2026-11-15T12:00Z", "2026-11-20T12:00Z", "2026-11-26T12:00Z"):
        save_snapshot(raw(fake_payload()), request, root=tmp_path, retrieved_at=stamp)
    assert len(list_snapshots(tmp_path)) == 3
    assert latest_before("2026-11-21T00:00Z", root=tmp_path).name == "2026-11-20T1200Z_forecast"
    assert latest_before("2026-11-30T00:00Z", root=tmp_path).name == "2026-11-26T1200Z_forecast"
    with pytest.raises(LookupError):
        latest_before("2026-11-01T00:00Z", root=tmp_path)


def test_latest_before_filters_archive_by_site_and_decision(tmp_path):
    site = (-41.222539, -73.295603)
    dates = {"start_date": "2025-11-27", "end_date": "2025-12-11"}
    archive = build_request("archive", *site, **dates)
    other = build_request("archive", -41.2, -73.3, **dates)
    expected = save_snapshot(raw(fake_payload()), archive, tmp_path, "2026-11-10T12:00Z")
    save_snapshot(raw(fake_payload()), other, tmp_path, "2026-11-11T12:00Z")
    save_snapshot(raw(fake_payload()), archive, tmp_path, "2026-11-13T12:00Z")
    assert latest_before("2026-11-12T00:00Z", tmp_path, "archive", coordinates=site) == expected


def test_series_rejects_wrong_units_and_timezone():
    payload = fake_payload()
    payload["hourly_units"]["wind_speed_10m"] = "km/h"
    with pytest.raises(ValueError, match="unidad"):
        from_open_meteo(payload)
    payload = fake_payload()
    payload["utc_offset_seconds"] = -10800
    with pytest.raises(ValueError):
        from_open_meteo(payload)


def test_shortwave_is_placed_at_middle_of_previous_hour():
    series = from_open_meteo(fake_payload(first="2026-11-27T00:00", hours=48))
    f = series.boundary_functions("2026-11-27T00:00Z")
    k = 15                                                    # marca 15:00 = media de 14:00–15:00
    assert f["shortwave_w_m2"](k * HOUR - HOUR / 2) == pytest.approx(series.shortwave_w_m2[k])
    assert f["air_c"](k * HOUR) == pytest.approx(series.air_c[k])
    with pytest.raises(ValueError, match="fuera"):
        f["air_c"](60 * HOUR)


def test_coverage_reports_missing_tail_and_fill_marks_origin():
    series = from_open_meteo(fake_payload(first="2026-11-20T00:00", hours=240), {"kind": "forecast"})
    report = coverage(series, START, 14)
    assert not report["complete"]
    assert report["needed_hours"] == pytest.approx(336)
    assert report["covered_hours"] == pytest.approx(239 - 7 * 24 - 7)
    assert report["missing_hours_at_end"] == pytest.approx(336 - report["covered_hours"])
    for method in ("persistencia", "conservador"):
        filled = fill_tail(series, START, 14, method=method)
        assert coverage(filled, START, 14)["complete"]
        origins = np.array(filled.origin)
        assert np.all(origins[:240] == "forecast") and np.all(origins[240:] == method)
        np.testing.assert_array_equal(filled.air_c[:240], series.air_c)      # el pronóstico no se toca
        assert filled.snapshot["tail_method"] == method
    cold = fill_tail(series, START, 14, method="conservador")
    assert np.all(cold.air_c[240:] < series.air_c.min()) and np.all(cold.shortwave_w_m2[240:] == 0)


def test_forecast_that_ends_before_construction_is_all_tail():
    """Descargado el 11-nov con 16 días: termina antes del 27-nov y todo el período es relleno."""
    series = from_open_meteo(fake_payload(first="2026-11-11T00:00", hours=384), {"kind": "forecast"})
    report = coverage(series, START, 14)
    assert report["covered_hours"] == 0 and not report["complete"]
    filled = fill_tail(series, START, 14, method="persistencia")
    f = filled.boundary_functions(START)
    assert np.isfinite(f["air_c"](14 * 24 * HOUR))


def test_climatology_needs_reference_and_uses_its_daily_cycle():
    series = from_open_meteo(fake_payload(hours=100), {"kind": "forecast"})
    with pytest.raises(ValueError):
        fill_tail(series, START, 14, method="climatologia")
    reference = from_open_meteo(fake_payload(first="2025-11-27T00:00", hours=24 * 15), {"kind": "archive"})
    reference.air_c[:] = 5.0
    filled = fill_tail(series, START, 14, method="climatologia", reference=reference)
    assert np.allclose(filled.air_c[100:], 5.0)


def test_internal_nulls_are_interpolated_and_marked():
    payload = fake_payload(hours=48)
    payload["hourly"]["temperature_2m"][10] = None
    series = from_open_meteo(payload, {"kind": "forecast"})
    with pytest.raises(ValueError):
        series.boundary_functions("2026-11-20T00:00Z")
    filled = fill_tail(series, "2026-11-20T00:00Z", 1, method="persistencia")
    assert filled.origin[10] == "interpolado" and np.isfinite(filled.air_c[10])


def test_ensemble_members_are_separate_series():
    members = ensemble_members(fake_payload(hours=48, members=3), {"kind": "ensemble"})
    assert len(members) == 4
    assert members[2].air_c[0] == pytest.approx(members[0].air_c[0] + 2)


def test_synthetic_series_is_labelled():
    series = synthetic_series(START, 14)
    assert set(series.origin) == {"sintetico"} and coverage(series, START, 14)["complete"]
    assert series.shortwave_w_m2.min() >= 0
