"""Common schemas."""

from pydantic import BaseModel


class Message(BaseModel):
    """Generic message response."""

    message: str


class PaginatedParams(BaseModel):
    """Pagination parameters."""

    skip: int = 0
    limit: int = 20
