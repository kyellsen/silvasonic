"""Unit tests for Recording ORM model defaults.

Validates that the ``Recording`` model's column metadata has the correct
Python-level defaults for boolean flags and JSONB columns, without
requiring a database connection.
"""

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

    def test_local_deleted_default_false(self) -> None:
        """Local_deleted column defaults to False."""
        col = Recording.__table__.columns["local_deleted"]
        assert col.default.arg is False

    def test_uploaded_default_false(self) -> None:
        """Uploaded column defaults to False."""
        col = Recording.__table__.columns["uploaded"]
        assert col.default.arg is False

    def test_upload_info_default_empty_jsonb(self) -> None:
        """Upload_info default produces an empty dict."""
        col = Recording.__table__.columns["upload_info"]
        assert col.default is not None
        assert callable(col.default.arg)
        assert col.default.arg.__name__ == "dict"

    def test_analysis_state_has_server_default(self) -> None:
        """Analysis_state column has a server_default for raw SQL inserts."""
        col = Recording.__table__.columns["analysis_state"]
        assert col.server_default is not None
