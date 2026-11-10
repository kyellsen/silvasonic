"""Unit tests for Recording ORM model defaults.

Validates that the ``Recording`` model's column metadata has the correct
Python-level defaults for boolean flags and JSONB columns, without
requiring a database connection.
"""

import uuid

import pytest
from silvasonic.core.database.models.recordings import Recording


@pytest.mark.unit
class TestRecordingModel:
    """Verify Recording ORM column defaults (Python-side)."""

    def test_analysis_state_default_empty_jsonb(self) -> None:
        """Analysis_state default produces an empty dict."""
        col = Recording.__table__.columns["analysis_state"]
        assert col.default is not None
        assert callable(col.default.arg)
        # SQLAlchemy CallableColumnDefault passes an ExecutionContext,
        # but the underlying built-in dict() accepts no args too.
        assert col.default.arg.__name__ == "dict"

    def test_deleted_at_default_null(self) -> None:
        """A recording is not deleted until deleted_at is set (ADR-0033)."""
        col = Recording.__table__.columns["deleted_at"]
        assert col.nullable is True
        assert col.default is None
        assert Recording.__table__.columns["deletion_reason"].nullable is True
        assert "local_deleted" not in Recording.__table__.columns

    def test_clock_synced_default_true(self) -> None:
        """Recordings are trusted unless the Recorder marked them (Issue 002)."""
        col = Recording.__table__.columns["clock_synced"]
        assert col.default.arg is True
        assert col.server_default is not None

    def test_uploaded_at_is_the_only_upload_fact(self) -> None:
        """uploaded_at replaces the uploaded flag (stored once)."""
        assert "uploaded" not in Recording.__table__.columns
        col = Recording.__table__.columns["uploaded_at"]
        assert col.nullable is True
        assert col.default is None

    def test_id_is_uuid_generated_by_database(self) -> None:
        """The id is a UUID with the database's uuidv7() default."""
        col = Recording.__table__.columns["id"]
        assert col.type.python_type is uuid.UUID
        assert col.server_default is not None
        assert "uuidv7()" in str(col.server_default.arg)

    def test_channels_default_one(self) -> None:
        """Channels defaults to mono."""
        col = Recording.__table__.columns["channels"]
        assert col.default.arg == 1
        assert col.server_default is not None

    def test_analysis_state_has_server_default(self) -> None:
        """Analysis_state column has a server_default for raw SQL inserts."""
        col = Recording.__table__.columns["analysis_state"]
        assert col.server_default is not None
