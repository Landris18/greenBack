from datetime import datetime

from pydantic import BaseModel


class MetricPoint(BaseModel):
    timestamp: datetime
    value: float
    secondary_value: float | None = None


class MetricSeries(BaseModel):
    metric: str
    unit: str
    label: str
    secondary_label: str | None = None
    points: list[MetricPoint]


class MetricSummary(BaseModel):
    container_count: int
    running_count: int
    cpu_percent_avg: float
    cpu_percent_max: float
    memory_bytes_avg: float
    memory_bytes_max: float
    net_rate_bps_avg: float
    io_rate_bps_avg: float
    sample_count: int
    window_start: datetime | None
    window_end: datetime | None
