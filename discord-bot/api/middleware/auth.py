"""
JWT Authentication middleware for the FastAPI REST API.
Used by Bubble to authenticate API calls.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from config.settings import settings
from utils.logger import logger


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)


class TokenData(BaseModel):
    user_id: Optional[int] = None
    guild_id: Optional[int] = None
    username: Optional[str] = None
    is_admin: bool = False


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode["exp"] = expire
    to_encode["iat"] = datetime.now(timezone.utc)
    return jwt.encode(to_encode, settings.api_secret_key, algorithm=settings.api_algorithm)


def decode_token(token: str) -> TokenData:
    try:
        payload = jwt.decode(token, settings.api_secret_key, algorithms=[settings.api_algorithm])
        return TokenData(
            user_id=payload.get("user_id"),
            guild_id=payload.get("guild_id"),
            username=payload.get("username"),
            is_admin=payload.get("is_admin", False),
        )
    except JWTError as e:
        logger.warning("JWT decode error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> TokenData:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decode_token(credentials.credentials)


def require_admin(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user
