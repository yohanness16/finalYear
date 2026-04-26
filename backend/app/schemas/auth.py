"""Auth-related schemas."""

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    """Passenger signup (email + password)."""

    username: str = Field(..., min_length=3, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=100)


class LoginRequest(BaseModel):
    """Email/password login."""

    username: str
    password: str


class GoogleAuthRequest(BaseModel):
    """Google OAuth ID token from frontend."""

    id_token: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AdminCreateUserRequest(BaseModel):
    """Admin creates driver or admin."""

    username: str = Field(..., min_length=3, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=100)
    role: str = Field(..., pattern="^(driver|admin)$")


class AdminUpdateUserRequest(BaseModel):
    """Admin updates driver or admin accounts."""

    username: str = Field(..., min_length=3, max_length=100)
    email: EmailStr
    password: str | None = Field(default=None, min_length=8, max_length=100)
    role: str = Field(..., pattern="^(driver|admin)$")
