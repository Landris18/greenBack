from datetime import datetime

from pydantic import BaseModel


class EnergyTotals(BaseModel):
    energy_kwh: float
    co2_kg: float
    average_power_watts: float
    sample_count: int
    window_start: datetime
    window_end: datetime


class EnergyPoint(BaseModel):
    timestamp: datetime
    energy_kwh: float
    co2_kg: float


class ProjectEnergySeries(BaseModel):
    project_id: int
    project_name: str
    points: list["EnergyPoint"]


class BreakdownItem(BaseModel):
    entity_id: int
    label: str
    energy_kwh: float
    co2_kg: float


class EnergySummary(BaseModel):
    totals: EnergyTotals
    overhead: EnergyTotals
    breakdown: list[BreakdownItem]
    power_source: str
    current_power_source: str
    emission_factor_g_per_kwh: float
    emission_factor_label: str
