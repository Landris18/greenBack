from datetime import datetime

from pydantic import BaseModel


class LivePoint(BaseModel):
    timestamp: datetime
    power_watts: float
    energy_wh_cumulative: float
    co2_g_cumulative: float
    cpu_percent_of_host: float
    memory_bytes: int


class LiveSeries(BaseModel):
    project_id: int
    project_name: str
    container_count: int
    points: list[LivePoint]
    energy_wh_total: float
    co2_g_total: float
    average_power_watts: float


class LiveResponse(BaseModel):
    series: list[LiveSeries]
    window_start: datetime
    window_end: datetime
    interval_seconds: int
