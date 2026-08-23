import pytest

from app.core.enums import IdleAttributionPolicy
from app.energy.model import (
    AttributionWeights,
    ContainerLoad,
    CpuCounters,
    HostLoad,
    PowerModelParams,
    attribute_power,
    compute_cpu_usage,
    compute_memory_working_set,
    compute_rate,
    gain_percent,
    host_power_from_model,
    host_power_from_rapl,
    kwh_to_co2_g,
    rapl_delta_uj,
    resource_share,
    split_power,
    watts_to_wh,
    wh_to_kwh,
)

WEIGHTS = AttributionWeights()
PARAMS = PowerModelParams(
    p_idle_watts=15.0, p_max_watts=65.0, mem_power_w_per_gb=0.38, non_cpu_overhead_ratio=0.35
)


class TestComputeCpuUsage:
    def test_no_previous_sample_yields_zero(self):
        current = CpuCounters(cpu_total_usage_ns=1_000, system_cpu_usage_ns=10_000, online_cpus=4)
        usage = compute_cpu_usage(current, None, host_cpu_cores=4)
        assert usage.cores_used == 0.0
        assert usage.percent_of_host == 0.0

    def test_half_a_core_on_four_core_host(self):
        previous = CpuCounters(0, 0, 4)
        current = CpuCounters(cpu_total_usage_ns=125, system_cpu_usage_ns=1_000, online_cpus=4)
        usage = compute_cpu_usage(current, previous, host_cpu_cores=4)
        assert usage.cores_used == pytest.approx(0.5)
        assert usage.percent_of_host == pytest.approx(12.5)

    def test_zero_system_delta_is_ignored(self):
        previous = CpuCounters(100, 1_000, 4)
        current = CpuCounters(200, 1_000, 4)
        assert compute_cpu_usage(current, previous, 4).cores_used == 0.0

    def test_counter_reset_is_ignored(self):
        previous = CpuCounters(5_000, 50_000, 4)
        current = CpuCounters(10, 60_000, 4)
        assert compute_cpu_usage(current, previous, 4).cores_used == 0.0

    def test_cores_used_is_clamped_to_online_cpus(self):
        previous = CpuCounters(0, 0, 2)
        current = CpuCounters(cpu_total_usage_ns=5_000, system_cpu_usage_ns=1_000, online_cpus=2)
        assert compute_cpu_usage(current, previous, 2).cores_used == 2.0


class TestMemoryWorkingSet:
    def test_page_cache_is_excluded(self):
        assert compute_memory_working_set(2_000, {"inactive_file": 1_400}) == 600

    def test_cgroup_v1_key_is_supported(self):
        assert compute_memory_working_set(2_000, {"total_inactive_file": 500}) == 1_500

    def test_missing_stats_falls_back_to_usage(self):
        assert compute_memory_working_set(2_000, None) == 2_000

    def test_never_negative(self):
        assert compute_memory_working_set(100, {"inactive_file": 900}) == 0


class TestRates:
    def test_rate_over_interval(self):
        assert compute_rate(3_000, 1_000, 20.0) == pytest.approx(100.0)

    def test_no_previous_yields_zero(self):
        assert compute_rate(3_000, None, 20.0) == 0.0

    def test_counter_reset_yields_zero(self):
        assert compute_rate(10, 5_000, 20.0) == 0.0


class TestRapl:
    def test_simple_delta(self):
        assert rapl_delta_uj(3_000_000, 1_000_000, max_range_uj=10_000_000) == 2_000_000

    def test_wraparound_is_handled(self):
        assert rapl_delta_uj(500, 9_999_000, max_range_uj=10_000_000) == 1_500

    def test_no_previous_yields_none(self):
        assert rapl_delta_uj(3_000_000, None) is None

    def test_package_power_scaled_by_overhead_ratio(self):
        watts = host_power_from_rapl(
            delta_uj=30_000_000, interval_seconds=30.0, non_cpu_overhead_ratio=0.35
        )
        assert watts == pytest.approx(1.35)


class TestHostPowerModel:
    def test_idle_host_draws_idle_power(self):
        assert host_power_from_model(0.0, 0, PARAMS) == pytest.approx(15.0)

    def test_full_load_reaches_max_power_plus_memory_term(self):
        watts = host_power_from_model(1.0, 0, PARAMS)
        assert watts == pytest.approx(65.0)

    def test_memory_term_is_added(self):
        watts = host_power_from_model(0.0, 8 * 1024**3, PARAMS)
        assert watts == pytest.approx(15.0 + 8 * 0.38)

    def test_utilization_is_clamped(self):
        assert host_power_from_model(4.0, 0, PARAMS) == pytest.approx(65.0)


class TestSplitPower:
    def test_dynamic_is_total_minus_idle(self):
        split = split_power(45.0, 15.0)
        assert (split.idle_watts, split.dynamic_watts) == (15.0, 30.0)

    def test_idle_never_exceeds_total(self):
        split = split_power(10.0, 15.0)
        assert split.idle_watts == pytest.approx(7.0)
        assert split.dynamic_watts == pytest.approx(3.0)

    def test_une_mesure_basse_laisse_toujours_une_part_dynamique(self):
        split = split_power(12.0, 15.0, max_idle_ratio=0.7)
        assert split.idle_watts == pytest.approx(8.4)
        assert split.dynamic_watts == pytest.approx(3.6)

    def test_le_plafond_ne_mord_pas_quand_la_mesure_est_haute(self):
        split = split_power(45.0, 15.0, max_idle_ratio=0.7)
        assert split.idle_watts == pytest.approx(15.0)
        assert split.dynamic_watts == pytest.approx(30.0)

    def test_plafond_nul_attribue_toute_la_puissance(self):
        split = split_power(12.0, 15.0, max_idle_ratio=0.0)
        assert split.idle_watts == pytest.approx(0.0)
        assert split.dynamic_watts == pytest.approx(12.0)

    def test_somme_toujours_egale_au_total(self):
        for total, idle, ratio in ((12.0, 15.0, 0.7), (45.0, 15.0, 0.7), (0.0, 15.0, 0.7)):
            split = split_power(total, idle, ratio)
            assert split.idle_watts + split.dynamic_watts == pytest.approx(split.total_watts)


class TestResourceShare:
    def test_share_is_relative_to_host_usage_not_capacity(self):
        host = HostLoad(cpu_cores_used=2.0, memory_used_bytes=8_000, io_rate_bps=0, net_rate_bps=0)
        load = ContainerLoad(
            key=1, cpu_cores_used=1.0, memory_bytes=4_000, io_rate_bps=0, net_rate_bps=0
        )
        assert resource_share(load, host, WEIGHTS) == pytest.approx(0.5)

    def test_unused_dimensions_are_dropped_and_weights_renormalized(self):
        host = HostLoad(cpu_cores_used=2.0, memory_used_bytes=0, io_rate_bps=0, net_rate_bps=0)
        load = ContainerLoad(
            key=1, cpu_cores_used=1.0, memory_bytes=4_000, io_rate_bps=0, net_rate_bps=0
        )
        assert resource_share(load, host, WEIGHTS) == pytest.approx(0.5)

    def test_completely_idle_host_yields_zero_share(self):
        host = HostLoad(cpu_cores_used=0, memory_used_bytes=0, io_rate_bps=0, net_rate_bps=0)
        load = ContainerLoad(key=1, cpu_cores_used=0, memory_bytes=0, io_rate_bps=0, net_rate_bps=0)
        assert resource_share(load, host, WEIGHTS) == 0.0


class TestAttribution:
    def _host(self):
        return HostLoad(
            cpu_cores_used=4.0, memory_used_bytes=8_000_000_000, io_rate_bps=0, net_rate_bps=0
        )

    def _loads(self):
        return [
            ContainerLoad(
                1, cpu_cores_used=2.0, memory_bytes=4_000_000_000, io_rate_bps=0, net_rate_bps=0
            ),
            ContainerLoad(
                2, cpu_cores_used=1.0, memory_bytes=2_000_000_000, io_rate_bps=0, net_rate_bps=0
            ),
        ]

    def test_energy_is_conserved(self):
        split = split_power(45.0, 15.0)
        result = attribute_power(self._loads(), self._host(), split, WEIGHTS)
        assert sum(result.container_watts.values()) + result.overhead_watts == pytest.approx(45.0)

    def test_unmonitored_load_lands_in_overhead(self):
        split = split_power(45.0, 15.0)
        result = attribute_power(self._loads(), self._host(), split, WEIGHTS)
        assert sum(result.shares.values()) == pytest.approx(0.75)
        assert sum(result.container_watts.values()) == pytest.approx(22.5)
        assert result.overhead_watts == pytest.approx(22.5)

    def test_overhead_is_at_least_idle_power(self):
        split = split_power(45.0, 15.0)
        result = attribute_power(self._loads(), self._host(), split, WEIGHTS)
        assert result.overhead_watts >= split.idle_watts

    def test_shares_are_renormalized_when_they_exceed_one(self):
        host = HostLoad(cpu_cores_used=1.0, memory_used_bytes=1_000, io_rate_bps=0, net_rate_bps=0)
        loads = [
            ContainerLoad(1, cpu_cores_used=1.0, memory_bytes=1_000, io_rate_bps=0, net_rate_bps=0),
            ContainerLoad(2, cpu_cores_used=1.0, memory_bytes=1_000, io_rate_bps=0, net_rate_bps=0),
        ]
        split = split_power(45.0, 15.0)
        result = attribute_power(loads, host, split, WEIGHTS)
        assert sum(result.shares.values()) == pytest.approx(1.0)
        assert result.overhead_watts == pytest.approx(15.0)
        assert sum(result.container_watts.values()) + result.overhead_watts == pytest.approx(45.0)

    def test_no_container_puts_everything_in_overhead(self):
        split = split_power(45.0, 15.0)
        result = attribute_power([], self._host(), split, WEIGHTS)
        assert result.overhead_watts == pytest.approx(45.0)

    def test_prorata_policy_distributes_idle_too(self):
        split = split_power(45.0, 15.0)
        result = attribute_power(
            self._loads(), self._host(), split, WEIGHTS, IdleAttributionPolicy.PRORATA
        )
        assert sum(result.container_watts.values()) == pytest.approx(33.75)
        assert sum(result.container_watts.values()) + result.overhead_watts == pytest.approx(45.0)


class TestConversions:
    def test_watts_over_an_hour(self):
        assert watts_to_wh(10.0, 3600.0) == pytest.approx(10.0)

    def test_watts_over_thirty_seconds(self):
        assert watts_to_wh(12.0, 30.0) == pytest.approx(0.1)

    def test_kwh_conversion(self):
        assert wh_to_kwh(2_500.0) == pytest.approx(2.5)

    def test_carbon_from_energy(self):
        assert kwh_to_co2_g(10.0, 52.0) == pytest.approx(520.0)


class TestGainPercent:
    def test_reduction_is_positive(self):
        assert gain_percent(120.0, 70.0) == pytest.approx(41.666, rel=1e-3)

    def test_increase_is_negative(self):
        assert gain_percent(70.0, 120.0) == pytest.approx(-71.428, rel=1e-3)

    def test_zero_baseline_is_undefined(self):
        assert gain_percent(0.0, 10.0) is None
