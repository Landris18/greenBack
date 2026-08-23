from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T", bound=BaseModel)

DEFAULT_PER_PAGE = 12
MAX_PER_PAGE = 200


class PaginationParams(BaseModel):
    page_no: int = 1
    per_page: int = DEFAULT_PER_PAGE


class PaginationMeta(BaseModel):
    page_no: int
    per_page: int
    total_items: int
    total_pages: int


class Page(BaseModel, Generic[T]):
    dataset: list[T]
    pagination: PaginationMeta


def pagination_params(
    page_no: int = Query(1, ge=1),
    per_page: int = Query(DEFAULT_PER_PAGE, ge=1, le=MAX_PER_PAGE),
) -> PaginationParams:
    return PaginationParams(page_no=page_no, per_page=per_page)


async def paginate(
    session: AsyncSession,
    statement: Select,
    params: PaginationParams,
    schema: type[T],
) -> Page[T]:
    count_statement = select(func.count()).select_from(statement.order_by(None).subquery())
    total_items = (await session.execute(count_statement)).scalar_one()

    offset = (params.page_no - 1) * params.per_page
    rows = (await session.execute(statement.offset(offset).limit(params.per_page))).scalars().all()

    total_pages = (total_items + params.per_page - 1) // params.per_page if total_items else 0
    return Page[schema](
        dataset=[schema.model_validate(row) for row in rows],
        pagination=PaginationMeta(
            page_no=params.page_no,
            per_page=params.per_page,
            total_items=total_items,
            total_pages=total_pages,
        ),
    )
