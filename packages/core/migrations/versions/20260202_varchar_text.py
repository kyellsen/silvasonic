"""migrate_varchar_to_text.

Revision ID: 20260202_varchar_text
Revises: 833e0e6f1e08
Create Date: 2026-02-02 00:25:25.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260202_varchar_text"
down_revision: str | None = "833e0e6f1e08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Run migration upgrade."""
    # devices
    op.alter_column("devices", "name", type_=sa.Text(), existing_type=sa.String())
    op.alter_column("devices", "serial_number", type_=sa.Text(), existing_type=sa.String())
    op.alter_column("devices", "model", type_=sa.Text(), existing_type=sa.String())
    op.alter_column("devices", "status", type_=sa.Text(), existing_type=sa.String())

    # system_services
    op.alter_column("system_services", "name", type_=sa.Text(), existing_type=sa.String())
    op.alter_column("system_services", "status", type_=sa.Text(), existing_type=sa.String())

    # system_config
    op.alter_column("system_config", "key", type_=sa.Text(), existing_type=sa.String())

    # taxonomy
    op.alter_column("taxonomy", "worker", type_=sa.Text(), existing_type=sa.String())
    op.alter_column("taxonomy", "label", type_=sa.Text(), existing_type=sa.String())
    op.alter_column("taxonomy", "scientific_name", type_=sa.Text(), existing_type=sa.String())
    op.alter_column("taxonomy", "image_path", type_=sa.Text(), existing_type=sa.String())
    op.alter_column("taxonomy", "image_source", type_=sa.Text(), existing_type=sa.String())
    op.alter_column("taxonomy", "conservation_status", type_=sa.Text(), existing_type=sa.String())

    # weather
    op.alter_column("weather", "source", type_=sa.Text(), existing_type=sa.String())
    op.alter_column("weather", "station_code", type_=sa.Text(), existing_type=sa.String())

    # recordings
    op.alter_column("recordings", "sensor_id", type_=sa.Text(), existing_type=sa.String())
    op.alter_column("recordings", "file_raw", type_=sa.Text(), existing_type=sa.String())
    op.alter_column("recordings", "file_processed", type_=sa.Text(), existing_type=sa.String())

    # detections
    op.alter_column("detections", "worker", type_=sa.Text(), existing_type=sa.String())
    op.alter_column("detections", "label", type_=sa.Text(), existing_type=sa.String())
    op.alter_column("detections", "common_name", type_=sa.Text(), existing_type=sa.String())

    # uploads
    op.alter_column("uploads", "filename", type_=sa.Text(), existing_type=sa.String())
    op.alter_column("uploads", "error_message", type_=sa.Text(), existing_type=sa.String())


def downgrade() -> None:
    """Run migration downgrade."""
    # uploads
    op.alter_column("uploads", "error_message", type_=sa.String(), existing_type=sa.Text())
    op.alter_column("uploads", "filename", type_=sa.String(), existing_type=sa.Text())

    # detections
    op.alter_column("detections", "common_name", type_=sa.String(), existing_type=sa.Text())
    op.alter_column("detections", "label", type_=sa.String(), existing_type=sa.Text())
    op.alter_column("detections", "worker", type_=sa.String(), existing_type=sa.Text())

    # recordings
    op.alter_column("recordings", "file_processed", type_=sa.String(), existing_type=sa.Text())
    op.alter_column("recordings", "file_raw", type_=sa.String(), existing_type=sa.Text())
    op.alter_column("recordings", "sensor_id", type_=sa.String(), existing_type=sa.Text())

    # weather
    op.alter_column("weather", "station_code", type_=sa.String(), existing_type=sa.Text())
    op.alter_column("weather", "source", type_=sa.String(), existing_type=sa.Text())

    # taxonomy
    op.alter_column("taxonomy", "conservation_status", type_=sa.String(), existing_type=sa.Text())
    op.alter_column("taxonomy", "image_source", type_=sa.String(), existing_type=sa.Text())
    op.alter_column("taxonomy", "image_path", type_=sa.String(), existing_type=sa.Text())
    op.alter_column("taxonomy", "scientific_name", type_=sa.String(), existing_type=sa.Text())
    op.alter_column("taxonomy", "label", type_=sa.String(), existing_type=sa.Text())
    op.alter_column("taxonomy", "worker", type_=sa.String(), existing_type=sa.Text())

    # system_config
    op.alter_column("system_config", "key", type_=sa.String(), existing_type=sa.Text())

    # system_services
    op.alter_column("system_services", "status", type_=sa.String(), existing_type=sa.Text())
    op.alter_column("system_services", "name", type_=sa.String(), existing_type=sa.Text())

    # devices
    op.alter_column("devices", "status", type_=sa.String(), existing_type=sa.Text())
    op.alter_column("devices", "model", type_=sa.String(), existing_type=sa.Text())
    op.alter_column("devices", "serial_number", type_=sa.String(), existing_type=sa.Text())
    op.alter_column("devices", "name", type_=sa.String(), existing_type=sa.Text())
