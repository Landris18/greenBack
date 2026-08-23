from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.core.enums import UserRole
from app.core.exceptions import InvalidCredentialsError, PermissionDeniedError
from app.core.security import decode_token
from app.user.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_PREFIX}/auth/login", auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    session: SessionDep, token: Annotated[str | None, Depends(oauth2_scheme)]
) -> User:
    if not token:
        raise InvalidCredentialsError("Authentification requise.")

    payload = decode_token(token, expected_type="access")
    if payload is None:
        raise InvalidCredentialsError("Jeton invalide ou expire.")

    user = await session.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise InvalidCredentialsError("Compte introuvable ou désactivé.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*allowed_roles: UserRole):
    async def dependency(current_user: CurrentUser) -> User:
        if current_user.role not in allowed_roles:
            raise PermissionDeniedError(
                "Cette action est réservée aux profils : "
                + ", ".join(role.value for role in allowed_roles)
                + "."
            )
        return current_user

    return dependency


RequireAdmin = Annotated[User, Depends(require_role(UserRole.ADMIN))]
RequireTech = Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.TECH))]


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    statement = select(User).where(User.email == email.lower())
    return (await session.execute(statement)).scalar_one_or_none()
