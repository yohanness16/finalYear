"""Assignment validation: reject duplicate driver/vehicle."""

from app.crud.assignment import (
    get_active_assignment_by_driver,
    get_active_assignment_by_vehicle,
)


def test_crud_functions_exist():
    """Ensure validation CRUD functions are defined."""
    assert callable(get_active_assignment_by_driver)
    assert callable(get_active_assignment_by_vehicle)
