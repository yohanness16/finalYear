import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
from app.services.trainer import _is_peak_hour, train_from_db

def test_is_peak_hour_logic():
    # Morning peak (7:00 - 9:59)
    assert _is_peak_hour(8) == 1
    # Evening peak (16:00 - 19:59)
    assert _is_peak_hour(17) == 1
    # Off-peak
    assert _is_peak_hour(12) == 0
    assert _is_peak_hour(22) == 0

@pytest.mark.asyncio
async def test_train_from_db_insufficient_data():
    # Mock DB to return 0 rows
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = mock_result
    
    success, message = await train_from_db(mock_db)
    
    assert success is False
    assert "Need at least 50 samples" in message

@pytest.mark.asyncio
@patch("joblib.dump")
async def test_train_from_db_success(mock_joblib_dump):
    # Mock DB to return 50 fake trip records
    mock_db = AsyncMock()
    
    # Create 50 mock trip objects
    mock_trips = []
    for i in range(55):
        trip = MagicMock()
        trip.stop_id = 1
        trip.arrival_time = None # Logic defaults to 12:00 if None
        trip.occupancy_level = 1
        trip.actual_travel_time = 300.0
        mock_trips.append(trip)
        
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = mock_trips
    mock_db.execute.return_value = mock_result
    
    # Run trainer
    test_path = Path("test_model.joblib")
    success, message = await train_from_db(mock_db, model_path=test_path)
    
    assert success is True
    assert "Trained on" in message  # Changed to match your actual function output
    mock_joblib_dump.assert_called_once()