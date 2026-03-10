"""
Service d'authentification JWT.
Gère l'inscription, la connexion, et la vérification des tokens.
"""
from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse

from config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(business_id: int, email: str) -> str:
    expire = datetime.utcnow() + timedelta(days=settings.jwt_expire_days)
    payload = {
        "sub": str(business_id),
        "email": email,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


def get_current_business_id(request: Request) -> int:
    """Dependency : retourne le business_id depuis le cookie JWT. Redirige vers /login si absent."""
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    return int(payload["sub"])


def get_current_business_id_optional(request: Request) -> Optional[int]:
    """Retourne business_id ou None (pas de redirection)."""
    token = request.cookies.get("access_token")
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    return int(payload["sub"])
