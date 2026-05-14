import pytest
from unittest.mock import patch, MagicMock
from app.services.ai_predictor import model_loaded, predict_delay, get_model_version
from app.services.ml_features import FEATURE_NAMES

@patch("app.services.ai_predictor._model_path")
def test_model_health_checks(mock_path):
    # Test health check functions when no model is present
    mock_path.exists.return_value = False
    import app.services.ai_predictor
    app.services.ai_predictor._model = None
    assert model_loaded() is False
    assert get_model_version() is None

def test_predict_delay_no_model():
    # Should return None gracefully if model isn't loaded
    result = predict_delay(stop_id=1, occupancy_level=1)
    assert result is None

@patch("joblib.load")
@patch("app.services.ai_predictor._model_path")
def test_predict_delay_with_mock_model(mock_path, mock_load):
    # Simulate the model file existing and being loaded
    mock_path.exists.return_value = True
    mock_model = MagicMock()
    mock_model.predict.return_value = [120.5] # Simulate 120.5 seconds delay
    mock_load.return_value = {"model": mock_model, "feature_names": FEATURE_NAMES}
    
    # Reset internal state to force a reload with the mock
    import app.services.ai_predictor
    app.services.ai_predictor._model = None 
    
    result = predict_delay(stop_id=10, occupancy_level=2)
    assert result == 120.5