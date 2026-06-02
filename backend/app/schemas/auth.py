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
    """Admin updates driver or admin accounts. All fields are optional for partial updates."""

    username: str | None = Field(default=None, min_length=3, max_length=100)
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8, max_length=100)
    role: str | None = Field(default=None, pattern="^(driver|admin)$")


class DriverLoginRequest(BaseModel):
    """Driver login bound to a specific bus/device context."""

    username: str
    password: str
    device_id: str
    bus_token: str


class DriverLoginResponse(BaseModel):
    """Driver token and active bus-session metadata."""

    access_token: str
    token_type: str = "bearer"
    session_id: int
    driver_id: int
    vehicle_id: int
    device_id: str


class DriverLogoutRequest(BaseModel):
    """Close an active driver bus session."""

    session_id: int


class BusDashboardLoginRequest(BaseModel):
    """Authenticate a bus dashboard device."""

    vehicle_id: int
    device_id: str
    password: str


class BusDashboardLoginResponse(BaseModel):
    """Short-lived token for a specific bus dashboard."""

    access_token: str
    token_type: str = "bearer"
    vehicle_id: int
    device_id: str


class VerifyEmailRequest(BaseModel):
    """Verify email with token from email link."""

    token: str


class ResendVerificationRequest(BaseModel):
    """Resend verification email."""

    email: EmailStr


class ForgotPasswordRequest(BaseModel):
    """Request password reset email."""

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Reset password with token from email."""

    token: str
    new_password: str = Field(..., min_length=8, max_length=100)


class UserUpdateRequest(BaseModel):
    """Update own profile (PATCH /auth/me)."""

    username: str | None = Field(default=None, min_length=3, max_length=100)
    email: EmailStr | None = None


class ChangePasswordRequest(BaseModel):
    """Change own password (POST /auth/change-password)."""

    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=100)
