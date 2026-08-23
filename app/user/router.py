from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select

from app.core.deps import RequireAdmin, SessionDep, get_user_by_email
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.pagination import Page, PaginationParams, paginate, pagination_params
from app.core.security import hash_password
from app.user.models import User
from app.user.schemas import UserCreate, UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["User"])

PaginationDep = Annotated[PaginationParams, Depends(pagination_params)]


@router.get("", response_model=Page[UserRead], summary="Lister les utilisateurs")
async def list_users(
    session: SessionDep, current_user: RequireAdmin, params: PaginationDep
) -> Page[UserRead]:
    return await paginate(session, select(User).order_by(User.id), params, UserRead)


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un utilisateur",
)
async def create_user(
    payload: UserCreate, session: SessionDep, current_user: RequireAdmin
) -> UserRead:
    if await get_user_by_email(session, payload.email):
        raise ConflictError("Un utilisateur avec cet email existe déjà.")

    user = User(
        email=payload.email.lower(),
        full_name=payload.full_name,
        role=payload.role,
        is_active=payload.is_active,
        hashed_password=hash_password(payload.password),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return UserRead.model_validate(user)


@router.get("/{user_id}", response_model=UserRead, summary="Détail d'un utilisateur")
async def get_user(user_id: int, session: SessionDep, current_user: RequireAdmin) -> UserRead:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError("Utilisateur introuvable.")
    return UserRead.model_validate(user)


@router.put("/{user_id}", response_model=UserRead, summary="Modifier un utilisateur")
async def update_user(
    user_id: int, payload: UserUpdate, session: SessionDep, current_user: RequireAdmin
) -> UserRead:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError("Utilisateur introuvable.")

    data = payload.model_dump(exclude_unset=True)
    password = data.pop("password", None)
    for key, value in data.items():
        setattr(user, key, value)
    if password:
        user.hashed_password = hash_password(password)

    await session.commit()
    await session.refresh(user)
    return UserRead.model_validate(user)


@router.delete(
    "/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer un utilisateur"
)
async def delete_user(user_id: int, session: SessionDep, current_user: RequireAdmin) -> None:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError("Utilisateur introuvable.")
    if user.id == current_user.id:
        raise ValidationError("Vous ne pouvez pas supprimer votre propre compte.")

    await session.delete(user)
    await session.commit()
