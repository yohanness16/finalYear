from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.services.ml_features import is_peak_hour
from app.services.trainer import train_from_db


def test_is_peak_hour_logic():
    # Morning peak (7:00 - 9:59)
    assert is_peak_hour(8) == 1
    # Evening peak (16:00 - 19:59)
    assert is_peak_hour(17) == 1
    # Off-peak
    assert is_peak_hour(12) == 0
    assert is_peak_hour(22) == 0


@pytest.mark.asyncio
async def test_train_from_db_insufficient_data():
    mock_db = AsyncMock()
    with patch(
        "app.services.trainer.build_training_rows", new=AsyncMock(return_value=[])
    ):
        success, message = await train_from_db(mock_db)

    assert success is False
    assert "Need at least 50 samples" in message


@pytest.mark.asyncio
@patch("joblib.dump")
async def test_train_from_db_success(mock_joblib_dump):
    mock_db = AsyncMock()
    rows = []
    for _ in range(55):
        rows.append({"feature_vector": [0.0] * 12, "target_residual": 5.0})

    test_path = Path("test_model.joblib")
    with patch(
        "app.services.trainer.build_training_rows", new=AsyncMock(return_value=rows)
    ):
        success, message = await train_from_db(mock_db, model_path=test_path)

    assert success is True
    assert "Trained on" in message
    mock_joblib_dump.assert_called_once()
