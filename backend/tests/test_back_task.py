from unittest.mock import AsyncMock

import pytest

from app.tasks.cleanup import run_cleanup


@pytest.mark.asyncio
async def test_run_cleanup_logic():
    # Mock the DB session
    mock_db = AsyncMock()
    mock_db.execute.return_value.rowcount = 5

    result = await run_cleanup(mock_db)

    assert "raw_telemetry_deleted" in result
    assert result["raw_telemetry_deleted"] == 5
    assert mock_db.execute.called
