from datetime import datetime

from pydantic import BaseModel

from app.energy.schemas import BreakdownItem


class CarbonTotals(BaseModel):
    co2_kg: float
    energy_kwh: float
    emission_factor_g_per_kwh: float
    emission_factor_label: str
    window_start: datetime
    window_end: datetime


class CarbonPoint(BaseModel):
    timestamp: datetime
    co2_kg: float


class CarbonSummary(BaseModel):
    totals: CarbonTotals
    overhead_co2_kg: float
    breakdown: list[BreakdownItem]
    history: list[CarbonPoint]
