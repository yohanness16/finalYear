"""Add missing foreign key indexes.

Adds indexes on frequently-queried foreign key columns that were missing,
which causes full table scans on JOIN operations as data grows.

Tables affected:
  - raw_vehicle_tracking: vehicle_id, timestamp
  - trip_history: assignment_id, stop_id, arrival_time
  - assignments: driver_id, vehicle_id, route_id, status
  - model_performance: trip_history_id, timestamp
  - favorites: user_id, route_id (also adds unique constraint)
  - ratings: user_id, assignment_id
  - notification_settings: user_id, route_id, stop_id
"""

from alembic import op

revision = "0012_add_missing_fk_indexes"
down_revision = "0011_add_driver_bus_sessions_table"


def upgrade() -> None:
    # raw_telemetry — high-frequency time-series table
    op.create_index("ix_raw_telemetry_vehicle_id", "raw_telemetry", ["vehicle_id"])
    op.create_index("ix_raw_telemetry_timestamp", "raw_telemetry", ["timestamp"])

    # trip_history — queried by assignment and stop for trip reconstruction
    op.create_index("ix_trip_history_assignment_id", "trip_history", ["assignment_id"])
    op.create_index("ix_trip_history_stop_id", "trip_history", ["stop_id"])
    op.create_index("ix_trip_history_arrival_time", "trip_history", ["arrival_time"])

    # assignments — frequently filtered by driver/vehicle/route/status
    op.create_index("ix_assignments_driver_id", "assignments", ["driver_id"])
    op.create_index("ix_assignments_vehicle_id", "assignments", ["vehicle_id"])
    op.create_index("ix_assignments_route_id", "assignments", ["route_id"])
    op.create_index("ix_assignments_status", "assignments", ["status"])

    # model_performance — queried by trip_history_id for analysis
    op.create_index("ix_model_performance_trip_history_id", "model_performance", ["trip_history_id"])
    op.create_index("ix_model_performance_timestamp", "model_performance", ["timestamp"])

    # favorites — queried by user_id, should be unique per user+route
    op.create_index("ix_favorites_user_id", "favorites", ["user_id"])
    op.create_index("ix_favorites_route_id", "favorites", ["route_id"])
    op.create_unique_constraint("uq_favorites_user_route", "favorites", ["user_id", "route_id"])

    # ratings — queried by user_id and assignment_id
    op.create_index("ix_ratings_user_id", "ratings", ["user_id"])
    op.create_index("ix_ratings_assignment_id", "ratings", ["assignment_id"])

    # notification_settings — queried by user_id for notification worker
    op.create_index("ix_notif_settings_user_id", "notification_settings", ["user_id"])
    op.create_index("ix_notif_settings_route_id", "notification_settings", ["route_id"])
    op.create_index("ix_notif_settings_stop_id", "notification_settings", ["stop_id"])


def downgrade() -> None:
    op.drop_index("ix_raw_telemetry_vehicle_id", "raw_telemetry")
    op.drop_index("ix_raw_telemetry_timestamp", "raw_telemetry")
    op.drop_index("ix_trip_history_assignment_id", "trip_history")
    op.drop_index("ix_trip_history_stop_id", "trip_history")
    op.drop_index("ix_trip_history_arrival_time", "trip_history")
    op.drop_index("ix_assignments_driver_id", "assignments")
    op.drop_index("ix_assignments_vehicle_id", "assignments")
    op.drop_index("ix_assignments_route_id", "assignments")
    op.drop_index("ix_assignments_status", "assignments")
    op.drop_index("ix_model_performance_trip_history_id", "model_performance")
    op.drop_index("ix_model_performance_timestamp", "model_performance")
    op.drop_index("ix_favorites_user_id", "favorites")
    op.drop_index("ix_favorites_route_id", "favorites")
    op.drop_constraint("uq_favorites_user_route", "favorites", type_="unique")
    op.drop_index("ix_ratings_user_id", "ratings")
    op.drop_index("ix_ratings_assignment_id", "ratings")
    op.drop_index("ix_notif_settings_user_id", "notification_settings")
    op.drop_index("ix_notif_settings_route_id", "notification_settings")
    op.drop_index("ix_notif_settings_stop_id", "notification_settings")
