from fastapi import APIRouter

from app.auth.schemas import LoginRequest, LoginResponse, MessageResponse, RefreshRequest, TokenPair
from app.core.deps import CurrentUser, SessionDep, get_user_by_email
from app.core.exceptions import InvalidCredentialsError
from app.core.security import create_token, decode_token, verify_password
from app.user.models import User
from app.user.schemas import UserRead

router = APIRouter(prefix="/auth", tags=["Auth"])


def _issue_tokens(user: User) -> TokenPair:
    return TokenPair(
        access_token=create_token(str(user.id), user.role.value, "access"),
        refresh_token=create_token(str(user.id), user.role.value, "refresh"),
    )


@router.post("/login", response_model=LoginResponse, summary="Se connecter")
async def login(payload: LoginRequest, session: SessionDep) -> LoginResponse:
    user = await get_user_by_email(session, payload.email)
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise InvalidCredentialsError("Email ou mot de passe incorrect.")
    if not user.is_active:
        raise InvalidCredentialsError("Ce compte est désactivé.")

    tokens = _issue_tokens(user)
    return LoginResponse(**tokens.model_dump(), user=UserRead.model_validate(user))


@router.post("/refresh", response_model=TokenPair, summary="Renouveler le jeton d'accès")
async def refresh(payload: RefreshRequest, session: SessionDep) -> TokenPair:
    claims = decode_token(payload.refresh_token, expected_type="refresh")
    if claims is None:
        raise InvalidCredentialsError("Jeton de rafraichissement invalide ou expire.")

    user = await session.get(User, int(claims["sub"]))
    if user is None or not user.is_active:
        raise InvalidCredentialsError("Compte introuvable ou désactivé.")
    return _issue_tokens(user)


@router.post("/logout", response_model=MessageResponse, summary="Se déconnecter")
async def logout(current_user: CurrentUser) -> MessageResponse:
    return MessageResponse(detail="Déconnexion effectuée.")


@router.get("/me", response_model=UserRead, summary="Profil de l'utilisateur connecte")
async def me(current_user: CurrentUser) -> UserRead:
    return UserRead.model_validate(current_user)
