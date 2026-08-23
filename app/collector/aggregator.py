import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.collector.frame import StatsFrame, is_stale, percent_of_limit
from app.collector.host_probe import HostProbe, HostReading
from app.core.enums import ContainerStatus, PowerSource
from app.energy.model import (
    Attribution,
    ContainerLoad,
    HostLoad,
    attribute_power,
    compute_cpu_usage,
    compute_rate,
    host_power_from_model,
    split_power,
    watts_to_wh,
    wh_to_co2_g,
)
from app.energy.models import EnergySample
from app.host.models import Host, HostMetricSample
from app.metric.models import ContainerMetricSample, LiveSample
from app.setting.models import GreenConfig
from app.setting.service import power_params_from_config, weights_from_config

logger = logging.getLogger("greensi.collector")


@dataclass(frozen=True)
class ContainerContext:
    container_id: int
    project_id: int
    docker_id: str
    name: str
    cpu_limit_cores: float | None
    memory_limit_bytes: int | None
    status: ContainerStatus
    started_at: datetime | None


@dataclass
class ContainerUsage:
    context: ContainerContext
    frame: StatsFrame
    cpu_cores_used: float
    cpu_percent_of_host: float
    cpu_percent_of_limit: float | None
    memory_working_set_bytes: int
    memory_percent_of_limit: float | None
    net_rate_bps: float
    io_rate_bps: float
    uptime_seconds: float


@dataclass
class Accumulator:
    energy_wh: float = 0.0
    co2_g: float = 0.0
    power_sum: float = 0.0
    ticks: int = 0
    cpu_cores_sum: float = 0.0
    share_sum: float = 0.0

    def add(self, watts: float, energy_wh: float, co2_g: float, share: float) -> None:
        self.energy_wh += energy_wh
        self.co2_g += co2_g
        self.power_sum += watts
        self.share_sum += share
        self.ticks += 1


@dataclass
class TickResult:
    now: datetime
    interval_seconds: float
    power_watts: float
    power_source: PowerSource
    live_rows: int
    persisted: bool
    stale_frames: int = 0


@dataclass
class Aggregator:
    host: Host
    probe: HostProbe
    previous_frames: dict[str, StatsFrame] = field(default_factory=dict)
    accumulators: dict[int, Accumulator] = field(default_factory=dict)
    overhead: Accumulator = field(default_factory=Accumulator)
    host_accumulator: Accumulator = field(default_factory=Accumulator)
    last_tick_at: datetime | None = None
    last_persist_at: datetime | None = None
    previous_host_sample: HostMetricSample | None = None
    tick_index: int = 0

    def compute_host_power(
        self, reading: HostReading, config: GreenConfig
    ) -> tuple[float, PowerSource]:
        if reading.measured_watts is not None and reading.measured_source is not None:
            return reading.measured_watts, reading.measured_source

        watts = host_power_from_model(
            reading.cpu_percent / 100.0,
            reading.memory_used_bytes,
            power_params_from_config(config),
        )
        return watts, PowerSource.MODEL

    def build_usages(
        self,
        frames: dict[str, StatsFrame],
        contexts: dict[str, ContainerContext],
        now: datetime,
        interval: float,
    ) -> tuple[list[ContainerUsage], int]:
        usages: list[ContainerUsage] = []
        stale = 0

        for docker_id, frame in frames.items():
            context = contexts.get(docker_id)
            if context is None:
                continue
            if is_stale(frame, now):
                stale += 1
                continue

            cpu = compute_cpu_usage(frame.counters, frame.previous_counters, self.host.cpu_cores)
            previous = self.previous_frames.get(docker_id)

            net_rate = compute_rate(
                frame.net_rx_bytes + frame.net_tx_bytes,
                (previous.net_rx_bytes + previous.net_tx_bytes) if previous else None,
                interval,
            )
            io_rate = compute_rate(
                frame.blk_read_bytes + frame.blk_write_bytes,
                (previous.blk_read_bytes + previous.blk_write_bytes) if previous else None,
                interval,
            )

            uptime = 0.0
            if context.started_at is not None:
                uptime = max(0.0, (now - context.started_at).total_seconds())

            memory_limit = context.memory_limit_bytes or frame.memory_limit_bytes

            usages.append(
                ContainerUsage(
                    context=context,
                    frame=frame,
                    cpu_cores_used=cpu.cores_used,
                    cpu_percent_of_host=cpu.percent_of_host,
                    cpu_percent_of_limit=percent_of_limit(cpu.cores_used, context.cpu_limit_cores),
                    memory_working_set_bytes=frame.memory_working_set_bytes,
                    memory_percent_of_limit=(
                        percent_of_limit(frame.memory_working_set_bytes, context.memory_limit_bytes)
                        if context.memory_limit_bytes
                        else percent_of_limit(frame.memory_working_set_bytes, memory_limit)
                    ),
                    net_rate_bps=net_rate,
                    io_rate_bps=io_rate,
                    uptime_seconds=uptime,
                )
            )

        return usages, stale

    def attribute(
        self, usages: list[ContainerUsage], reading: HostReading, split, config: GreenConfig
    ) -> Attribution:
        loads = [
            ContainerLoad(
                key=usage.context.container_id,
                cpu_cores_used=usage.cpu_cores_used,
                memory_bytes=float(usage.memory_working_set_bytes),
                io_rate_bps=usage.io_rate_bps,
                net_rate_bps=usage.net_rate_bps,
            )
            for usage in usages
            if usage.context.status is ContainerStatus.RUNNING
        ]
        host_load = HostLoad(
            cpu_cores_used=reading.cpu_percent / 100.0 * (self.host.cpu_cores or 1),
            memory_used_bytes=float(reading.memory_used_bytes),
            io_rate_bps=reading.io_rate_bps,
            net_rate_bps=reading.net_rate_bps,
        )
        return attribute_power(
            loads, host_load, split, weights_from_config(config), config.idle_attribution_policy
        )

    async def tick(
        self,
        session: AsyncSession,
        frames: dict[str, StatsFrame],
        contexts: dict[str, ContainerContext],
        config: GreenConfig,
    ) -> TickResult:
        now = datetime.now(UTC)
        interval = 1.0
        if self.last_tick_at is not None:
            interval = max((now - self.last_tick_at).total_seconds(), 0.05)
        if self.last_persist_at is None:
            self.last_persist_at = now

        reading = await self.probe.read(interval, config.non_cpu_overhead_ratio)
        power_watts, power_source = self.compute_host_power(reading, config)
        split = split_power(power_watts, config.p_idle_watts, config.max_idle_ratio)

        usages, stale = self.build_usages(frames, contexts, now, interval)
        attribution = self.attribute(usages, reading, split, config)

        factor = config.emission_factor_g_per_kwh
        live_rows: list[LiveSample] = []

        for usage in usages:
            container_id = usage.context.container_id
            watts = attribution.container_watts.get(container_id, 0.0)
            energy_wh = watts_to_wh(watts, interval)
            co2_g = wh_to_co2_g(energy_wh, factor)

            accumulator = self.accumulators.setdefault(container_id, Accumulator())
            accumulator.add(watts, energy_wh, co2_g, attribution.shares.get(container_id, 0.0))
            accumulator.cpu_cores_sum += usage.cpu_cores_used

            live_rows.append(
                LiveSample(
                    container_id=container_id,
                    project_id=usage.context.project_id,
                    collected_at=now,
                    interval_seconds=interval,
                    cpu_cores_used=usage.cpu_cores_used,
                    cpu_percent_of_host=usage.cpu_percent_of_host,
                    cpu_percent_of_limit=usage.cpu_percent_of_limit,
                    memory_working_set_bytes=usage.memory_working_set_bytes,
                    memory_percent_of_limit=usage.memory_percent_of_limit,
                    net_rate_bps=usage.net_rate_bps,
                    io_rate_bps=usage.io_rate_bps,
                    power_watts=watts,
                    energy_wh=energy_wh,
                    co2_g=co2_g,
                )
            )

        overhead_wh = watts_to_wh(attribution.overhead_watts, interval)
        self.overhead.add(
            attribution.overhead_watts, overhead_wh, wh_to_co2_g(overhead_wh, factor), 0.0
        )

        host_wh = watts_to_wh(split.total_watts, interval)
        self.host_accumulator.add(split.total_watts, host_wh, wh_to_co2_g(host_wh, factor), 0.0)

        session.add_all(live_rows)

        self.previous_frames = dict(frames)
        self.last_tick_at = now
        self.tick_index += 1

        persisted = False
        if self.tick_index % max(1, config.persist_every_n_ticks) == 0:
            self._persist(session, usages, now, power_source, split, reading, config)
            persisted = True

        await session.commit()

        return TickResult(
            now=now,
            interval_seconds=interval,
            power_watts=split.total_watts,
            power_source=power_source,
            live_rows=len(live_rows),
            persisted=persisted,
            stale_frames=stale,
        )

    def _persist(
        self,
        session: AsyncSession,
        usages: list[ContainerUsage],
        now: datetime,
        power_source: PowerSource,
        split,
        reading: HostReading,
        config: GreenConfig,
    ) -> None:
        elapsed = 1.0
        if self.last_persist_at is not None:
            elapsed = max((now - self.last_persist_at).total_seconds(), 0.05)

        hours = elapsed / 3600.0

        def average_power(energy_wh: float) -> float:
            return energy_wh / hours if hours > 0 else 0.0

        host_sample = HostMetricSample(
            host_id=self.host.id,
            collected_at=now,
            interval_seconds=elapsed,
            cpu_percent=reading.cpu_percent,
            memory_used_bytes=reading.memory_used_bytes,
            memory_total_bytes=reading.memory_total_bytes,
            rapl_energy_uj=reading.rapl_energy_uj,
            power_watts=average_power(self.host_accumulator.energy_wh),
            idle_power_watts=split.idle_watts,
            dynamic_power_watts=split.dynamic_watts,
            power_source=power_source,
            has_previous=self.previous_host_sample is not None,
        )
        session.add(host_sample)
        self.previous_host_sample = host_sample

        for usage in usages:
            context = usage.context
            accumulator = self.accumulators.get(context.container_id)
            frame = usage.frame

            session.add(
                ContainerMetricSample(
                    container_id=context.container_id,
                    collected_at=now,
                    interval_seconds=elapsed,
                    has_previous=frame.previous_counters is not None,
                    cpu_total_usage_ns=frame.counters.cpu_total_usage_ns,
                    system_cpu_usage_ns=frame.counters.system_cpu_usage_ns,
                    online_cpus=frame.counters.online_cpus,
                    net_rx_bytes=frame.net_rx_bytes,
                    net_tx_bytes=frame.net_tx_bytes,
                    blk_read_bytes=frame.blk_read_bytes,
                    blk_write_bytes=frame.blk_write_bytes,
                    cpu_cores_used=usage.cpu_cores_used,
                    cpu_percent=usage.cpu_percent_of_host,
                    cpu_percent_of_limit=usage.cpu_percent_of_limit,
                    memory_working_set_bytes=usage.memory_working_set_bytes,
                    memory_limit_bytes=context.memory_limit_bytes,
                    memory_percent_of_limit=usage.memory_percent_of_limit,
                    net_rx_rate=usage.net_rate_bps / 2.0,
                    net_tx_rate=usage.net_rate_bps / 2.0,
                    blk_read_rate=usage.io_rate_bps / 2.0,
                    blk_write_rate=usage.io_rate_bps / 2.0,
                    pids=frame.pids,
                    uptime_seconds=usage.uptime_seconds,
                )
            )

            if accumulator is None or accumulator.ticks == 0:
                continue

            session.add(
                EnergySample(
                    host_id=self.host.id,
                    project_id=context.project_id,
                    container_id=context.container_id,
                    green_config_id=config.id,
                    collected_at=now,
                    interval_seconds=elapsed,
                    share_ratio=accumulator.share_sum / accumulator.ticks,
                    power_watts=average_power(accumulator.energy_wh),
                    energy_wh=accumulator.energy_wh,
                    co2_g=accumulator.co2_g,
                    power_source=power_source,
                    is_overhead=False,
                )
            )

        if self.overhead.ticks > 0:
            session.add(
                EnergySample(
                    host_id=self.host.id,
                    project_id=None,
                    container_id=None,
                    green_config_id=config.id,
                    collected_at=now,
                    interval_seconds=elapsed,
                    share_ratio=0.0,
                    power_watts=average_power(self.overhead.energy_wh),
                    energy_wh=self.overhead.energy_wh,
                    co2_g=self.overhead.co2_g,
                    power_source=power_source,
                    is_overhead=True,
                )
            )

        self.accumulators.clear()
        self.overhead = Accumulator()
        self.host_accumulator = Accumulator()
        self.last_persist_at = now
