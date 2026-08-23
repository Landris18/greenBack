from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, Query
from pydantic import BaseModel

from app.core.enums import Granularity


class TimeWindow(BaseModel):
    start: datetime
    end: datetime
    granularity: Granularity

    @property
    def duration_hours(self) -> float:
        return max((self.end - self.start).total_seconds() / 3600.0, 0.0)


def time_window(
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    hours: int = Query(24, ge=1, le=8760),
    granularity: Granularity = Query(Granularity.HOUR),
) -> TimeWindow:
    end = date_to or datetime.now(UTC)
    start = date_from or (end - timedelta(hours=hours))
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    if start > end:
        start, end = end, start
    return TimeWindow(start=start, end=end, granularity=granularity)


TimeWindowDep = Annotated[TimeWindow, Depends(time_window)]
