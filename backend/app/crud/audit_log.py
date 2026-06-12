"""Audit log CRUD operations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


async def create_audit_log(
    db: AsyncSession,
    action: str,
    admin_id: int | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    details: dict | None = None,
) -> AuditLog:
    """Create an audit log entry."""
    entry = AuditLog(
        admin_id=admin_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details,
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return entry


async def list_audit_logs(
    db: AsyncSession,
    *,
    admin_id: int | None = None,
    action: str | None = None,
    target_type: str | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[AuditLog]:
    """List audit logs with optional filters and pagination."""
    stmt = select(AuditLog)
    if admin_id is not None:
        stmt = stmt.where(AuditLog.admin_id == admin_id)
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    if target_type is not None:
        stmt = stmt.where(AuditLog.target_type == target_type)
    stmt = stmt.order_by(AuditLog.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())
