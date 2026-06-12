"""Add missing foreign key indexes.

Adds indexes on frequently-queried foreign key columns that were missing,
which causes full table scans on JOIN operations as data grows.

Uses IF NOT EXISTS so the migration is idempotent.

Note: notification_settings does NOT have a stop_id column — it only has
user_id, route_id, and lead_time_minutes. The stop_id field was added
later via the notification_setting model but is not in the DB schema.
"""

from alembic import op

revision = "0012_add_missing_fk_indexes"
down_revision = "0011"


def upgrade() -> None:
    # raw_telemetry — high-frequency time-series table
    op.execute("CREATE INDEX IF NOT EXISTS ix_raw_telemetry_vehicle_id ON raw_telemetry (vehicle_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_raw_telemetry_timestamp ON raw_telemetry (timestamp)")

    # trip_history — queried by assignment and stop for trip reconstruction
    op.execute("CREATE INDEX IF NOT EXISTS ix_trip_history_assignment_id ON trip_history (assignment_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_trip_history_stop_id ON trip_history (stop_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_trip_history_arrival_time ON trip_history (arrival_time)")

    # assignments — frequently filtered by driver/vehicle/route/status
    op.execute("CREATE INDEX IF NOT EXISTS ix_assignments_driver_id ON assignments (driver_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_assignments_vehicle_id ON assignments (vehicle_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_assignments_route_id ON assignments (route_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_assignments_status ON assignments (status)")

    # model_performance — queried by trip_history_id for analysis
    op.execute("CREATE INDEX IF NOT EXISTS ix_model_performance_trip_history_id ON model_performance (trip_history_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_model_performance_timestamp ON model_performance (timestamp)")

    # favorites — queried by user_id
    op.execute("CREATE INDEX IF NOT EXISTS ix_favorites_user_id ON favorites (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_favorites_route_id ON favorites (route_id)")

    # ratings — queried by user_id and assignment_id
    op.execute("CREATE INDEX IF NOT EXISTS ix_ratings_user_id ON ratings (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ratings_assignment_id ON ratings (assignment_id)")

    # notification_settings — queried by user_id for notification worker
    # Note: only user_id and route_id exist (no stop_id column)
    op.execute("CREATE INDEX IF NOT EXISTS ix_notif_settings_user_id ON notification_settings (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_notif_settings_route_id ON notification_settings (route_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_raw_telemetry_vehicle_id")
    op.execute("DROP INDEX IF EXISTS ix_raw_telemetry_timestamp")
    op.execute("DROP INDEX IF EXISTS ix_trip_history_assignment_id")
    op.execute("DROP INDEX IF EXISTS ix_trip_history_stop_id")
    op.execute("DROP INDEX IF EXISTS ix_trip_history_arrival_time")
    op.execute("DROP INDEX IF EXISTS ix_assignments_driver_id")
    op.execute("DROP INDEX IF EXISTS ix_assignments_vehicle_id")
    op.execute("DROP INDEX IF EXISTS ix_assignments_route_id")
    op.execute("DROP INDEX IF EXISTS ix_assignments_status")
    op.execute("DROP INDEX IF EXISTS ix_model_performance_trip_history_id")
    op.execute("DROP INDEX IF EXISTS ix_model_performance_timestamp")
    op.execute("DROP INDEX IF EXISTS ix_favorites_user_id")
    op.execute("DROP INDEX IF EXISTS ix_favorites_route_id")
    op.execute("DROP INDEX IF EXISTS ix_ratings_user_id")
    op.execute("DROP INDEX IF EXISTS ix_ratings_assignment_id")
    op.execute("DROP INDEX IF EXISTS ix_notif_settings_user_id")
    op.execute("DROP INDEX IF EXISTS ix_notif_settings_route_id")
