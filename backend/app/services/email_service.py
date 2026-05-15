"""Email service using Resend API for transactional emails."""

import httpx

from app.core.config import get_settings

settings = get_settings()


async def send_email(to: str, subject: str, html_body: str) -> bool:
    """Send an email via Resend API. Returns True on success."""
    if not settings.RESEND_API_KEY:
        return False

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": settings.RESEND_FROM_EMAIL,
                "to": [to],
                "subject": subject,
                "html": html_body,
            },
            timeout=15.0,
        )
    return resp.status_code == 200


async def send_verification_email(to: str, username: str, token: str) -> bool:
    """Send email verification link to a newly registered user."""
    verify_url = f"{settings.APP_BASE_URL}/verify-email?token={token}"
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #1a73e8;">Welcome to BusTrack, {username}!</h2>
        <p>Please verify your email address to activate your account.</p>
        <a href="{verify_url}" style="display: inline-block; background: #1a73e8; color: white;
           padding: 12px 24px; text-decoration: none; border-radius: 6px; margin: 16px 0;">
            Verify Email
        </a>
        <p style="color: #666; font-size: 14px;">
            Or copy this link: {verify_url}
        </p>
        <p style="color: #999; font-size: 12px;">
            This link expires in 24 hours. If you didn't create this account, ignore this email.
        </p>
    </div>
    """
    return await send_email(to, "Verify your BusTrack email", html)


async def send_password_reset_email(to: str, username: str, token: str) -> bool:
    """Send password reset link to a user."""
    reset_url = f"{settings.APP_BASE_URL}/reset-password?token={token}"
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #1a73e8;">Password Reset — BusTrack</h2>
        <p>Hi {username}, we received a request to reset your password.</p>
        <a href="{reset_url}" style="display: inline-block; background: #1a73e8; color: white;
           padding: 12px 24px; text-decoration: none; border-radius: 6px; margin: 16px 0;">
            Reset Password
        </a>
        <p style="color: #666; font-size: 14px;">
            Or copy this link: {reset_url}
        </p>
        <p style="color: #999; font-size: 12px;">
            This link expires in 1 hour. If you didn't request this, ignore this email.
        </p>
    </div>
    """
    return await send_email(to, "Reset your BusTrack password", html)
