from datetime import UTC, datetime, timedelta

import pytest

from app.comparison.schemas import ComparisonSideMetrics
from app.comparison.service import build_gains, build_warnings, gain_percent

BASE = datetime(2026, 8, 1, tzinfo=UTC)


def side(
    name: str = "Avant",
    duration_hours: float = 24.0,
    container_count: int = 4,
    cpu_percent_avg: float = 72.0,
    memory_bytes_avg: float = 6 * 1024**3,
    energy_kwh: float = 1.2,
    co2_kg: float = 0.48,
    image_bytes: int = 4_500_000_000,
    offset_hours: float = 0.0,
) -> ComparisonSideMetrics:
    start = BASE + timedelta(hours=offset_hours)
    end = start + timedelta(hours=duration_hours)
    return ComparisonSideMetrics(
        project_id=1,
        project_name=name,
        period_start=start,
        period_end=end,
        duration_hours=duration_hours,
        container_count=container_count,
        cpu_percent_avg=cpu_percent_avg,
        cpu_percent_p95=cpu_percent_avg * 1.2,
        memory_bytes_avg=memory_bytes_avg,
        memory_bytes_max=memory_bytes_avg * 1.1,
        total_image_size_bytes=image_bytes,
        energy_kwh=energy_kwh,
        co2_kg=co2_kg,
        energy_kwh_per_hour=energy_kwh / duration_hours if duration_hours else 0.0,
        co2_kg_per_hour=co2_kg / duration_hours if duration_hours else 0.0,
        energy_kwh_per_hour_per_container=(
            energy_kwh / duration_hours / container_count
            if duration_hours and container_count
            else 0.0
        ),
    )


class TestGainPercent:
    def test_reduction(self):
        assert gain_percent(120.0, 70.0) == pytest.approx(41.67, abs=0.01)

    def test_regression_is_negative(self):
        assert gain_percent(70.0, 120.0) == pytest.approx(-71.43, abs=0.01)

    def test_zero_baseline_is_undefined(self):
        assert gain_percent(0.0, 5.0) is None


class TestBuildGains:
    def test_all_expected_indicators_are_present(self):
        gains = build_gains(side(), side("Apres", cpu_percent_avg=35.0))
        keys = {gain.key for gain in gains}
        assert keys == {
            "cpu_percent_avg",
            "memory_bytes_avg",
            "total_image_size_bytes",
            "energy_kwh_per_hour",
            "co2_kg_per_hour",
            "energy_kwh_per_hour_per_container",
        }

    def test_energy_gains_are_flagged_as_normalized(self):
        gains = build_gains(side(), side("Apres"))
        normalized = {gain.key for gain in gains if gain.is_normalized}
        assert normalized == {
            "energy_kwh_per_hour",
            "co2_kg_per_hour",
            "energy_kwh_per_hour_per_container",
        }

    def test_gain_uses_hourly_rates_so_unequal_durations_do_not_fake_a_win(self):
        before = side(duration_hours=24.0, energy_kwh=2.4)
        after = side("Apres", duration_hours=6.0, energy_kwh=0.6)

        energy_gain = next(g for g in build_gains(before, after) if g.key == "energy_kwh_per_hour")
        assert energy_gain.gain_percent == pytest.approx(0.0)

    def test_energy_and_carbon_gains_stay_identical_at_tiny_scales(self):
        factor = 52.0 / 1000.0
        before = side(duration_hours=0.67, energy_kwh=0.0000268, co2_kg=0.0000268 * factor)
        after = side("Apres", duration_hours=0.67, energy_kwh=0.0000208, co2_kg=0.0000208 * factor)

        gains = {gain.key: gain.gain_percent for gain in build_gains(before, after)}
        assert gains["energy_kwh_per_hour"] == pytest.approx(gains["co2_kg_per_hour"], abs=0.01)
        assert gains["energy_kwh_per_hour"] is not None
        assert gains["energy_kwh_per_hour"] > 0

    def test_real_reduction_is_reported(self):
        before = side(duration_hours=24.0, energy_kwh=2.4)
        after = side("Apres", duration_hours=24.0, energy_kwh=1.2)

        energy_gain = next(g for g in build_gains(before, after) if g.key == "energy_kwh_per_hour")
        assert energy_gain.gain_percent == pytest.approx(50.0)


class TestBuildWarnings:
    def test_no_warning_for_identical_overlapping_periods(self):
        assert build_warnings(side(), side("Apres")) == []

    def test_warns_on_unequal_durations(self):
        warnings = build_warnings(side(duration_hours=24.0), side("Apres", duration_hours=4.0))
        assert any("durée" in warning for warning in warnings)

    def test_warns_on_unequal_container_counts(self):
        warnings = build_warnings(side(container_count=10), side("Apres", container_count=2))
        assert any("conteneurs observés diffère" in warning for warning in warnings)

    def test_warns_when_a_side_has_no_metrics(self):
        warnings = build_warnings(side(), side("Apres", container_count=0))
        assert any("aucune métrique" in warning for warning in warnings)

    def test_warns_when_periods_do_not_overlap(self):
        warnings = build_warnings(side(), side("Apres", offset_hours=100.0))
        assert any("ne se recouvrent pas" in warning for warning in warnings)
