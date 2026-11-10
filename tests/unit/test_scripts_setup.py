"""Unit tests for scripts/setup.py — bootstrap check functions.

Tests the Podman version check and loginctl linger detection that
run during ``just setup``.  All subprocess calls are mocked.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from setup import (
    check_container_engine,
    check_linger,
    ensure_env_file,
    ensure_gateway_credentials,
)

# ── check_container_engine ────────────────────────────────────────────────────


@pytest.mark.unit
class TestCheckContainerEngine:
    """Verify Podman availability and version checks."""

    def test_podman_missing_exits(self) -> None:
        """Setup aborts with sys.exit(1) when podman is not in PATH."""
        with (
            patch("setup.shutil.which", return_value=None),
            pytest.raises(SystemExit, match="1"),
        ):
            check_container_engine()

    def test_podman_found_prints_success(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Podman found + version >= 4 prints success without warnings."""
        mock_result = MagicMock()
        mock_result.stdout = "podman version 5.3.1\n"

        with (
            patch("setup.shutil.which", return_value="/usr/bin/podman"),
            patch("setup.subprocess.run", return_value=mock_result),
        ):
            check_container_engine()

        captured = capsys.readouterr()
        assert "podman" in captured.out.lower()

    def test_podman_old_version_warns(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Podman version < 4.0 triggers a warning."""
        mock_result = MagicMock()
        mock_result.stdout = "podman version 3.4.7\n"

        with (
            patch("setup.shutil.which", return_value="/usr/bin/podman"),
            patch("setup.subprocess.run", return_value=mock_result),
        ):
            check_container_engine()

        captured = capsys.readouterr()
        assert "4.0" in captured.out

    def test_podman_version_parse_error_warns(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Graceful handling when podman --version output is unparseable."""
        with (
            patch("setup.shutil.which", return_value="/usr/bin/podman"),
            patch("setup.subprocess.run", side_effect=FileNotFoundError("podman")),
        ):
            check_container_engine()

        captured = capsys.readouterr()
        assert "could not determine" in captured.out.lower()


# ── check_linger ──────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestCheckLinger:
    """Verify loginctl enable-linger detection."""

    def test_no_loginctl_skips_silently(self, capsys: pytest.CaptureFixture[str]) -> None:
        """On systems without loginctl (e.g. containers), skip silently."""
        with patch("setup.shutil.which", return_value=None):
            check_linger()

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_linger_enabled_prints_success(self, capsys: pytest.CaptureFixture[str]) -> None:
        """When linger is enabled, print success message."""
        mock_result = MagicMock()
        mock_result.stdout = "Linger=yes\n"

        with (
            patch("setup.shutil.which", return_value="/usr/bin/loginctl"),
            patch("setup.subprocess.run", return_value=mock_result),
        ):
            check_linger()

        captured = capsys.readouterr()
        assert "linger" in captured.out.lower()

    def test_linger_disabled_warns(self, capsys: pytest.CaptureFixture[str]) -> None:
        """When linger is not enabled, warn the user with fix instructions."""
        mock_result = MagicMock()
        mock_result.stdout = "Linger=no\n"

        with (
            patch("setup.shutil.which", return_value="/usr/bin/loginctl"),
            patch("setup.subprocess.run", return_value=mock_result),
            patch.dict("os.environ", {"USER": "testuser"}),
        ):
            check_linger()

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "linger" in combined.lower()

    def test_loginctl_exception_handled_gracefully(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """If loginctl fails unexpectedly, print a warning instead of crashing."""
        with (
            patch("setup.shutil.which", return_value="/usr/bin/loginctl"),
            patch("setup.subprocess.run", side_effect=OSError("dbus not available")),
        ):
            check_linger()  # Must not raise

        captured = capsys.readouterr()
        assert "could not check linger" in captured.out.lower()


# ── ensure_env_file (UID auto-patch) ─────────────────────────────────────────

_ENV_TEMPLATE = """\
# Podman socket
SILVASONIC_PODMAN_SOCKET=/run/user/1000/podman/podman.sock
DOCKER_HOST=unix:///run/user/1000/podman/podman.sock
SILVASONIC_ENCRYPTION_KEY="test-key-abc"
"""


@pytest.mark.unit
class TestEnsureEnvFileUidPatch:
    """Verify that ensure_env_file() auto-patches UID 1000 to the actual UID."""

    def _setup_env(self, tmp_path: Path) -> tuple[Path, Path]:
        """Create a minimal .env.example and return (project_root, env_file)."""
        env_example = tmp_path / ".env.example"
        env_example.write_text(_ENV_TEMPLATE, encoding="utf-8")
        return tmp_path, tmp_path / ".env"

    def test_patches_uid_when_different(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """UID 1000 in .env is replaced with actual UID when they differ."""
        project_root, env_file = self._setup_env(tmp_path)

        with (
            patch("setup.PROJECT_ROOT", project_root),
            patch("setup.os.getuid", return_value=1500),
        ):
            ensure_env_file()

        content = env_file.read_text()
        assert "/run/user/1500/" in content
        assert "/run/user/1000/" not in content

        captured = capsys.readouterr()
        assert "1500" in captured.out

    def test_skips_patch_when_uid_is_1000(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """No patch needed when actual UID is already 1000."""
        project_root, env_file = self._setup_env(tmp_path)

        with (
            patch("setup.PROJECT_ROOT", project_root),
            patch("setup.os.getuid", return_value=1000),
        ):
            ensure_env_file()

        content = env_file.read_text()
        assert "/run/user/1000/" in content

        captured = capsys.readouterr()
        assert "patched" not in captured.out.lower()

    def test_skips_patch_when_already_correct(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """No patch when .env already has the correct UID (no 1000 present)."""
        project_root = tmp_path
        env_example = project_root / ".env.example"
        env_example.write_text(
            _ENV_TEMPLATE.replace("/run/user/1000/", "/run/user/1500/"),
            encoding="utf-8",
        )

        with (
            patch("setup.PROJECT_ROOT", project_root),
            patch("setup.os.getuid", return_value=1500),
        ):
            ensure_env_file()

        env_file = project_root / ".env"
        content = env_file.read_text()
        assert "/run/user/1500/" in content

        captured = capsys.readouterr()
        assert "patched" not in captured.out.lower()

    def test_patches_both_socket_variables(self, tmp_path: Path) -> None:
        """Both SILVASONIC_PODMAN_SOCKET and DOCKER_HOST are patched."""
        project_root, env_file = self._setup_env(tmp_path)

        with (
            patch("setup.PROJECT_ROOT", project_root),
            patch("setup.os.getuid", return_value=501),
        ):
            ensure_env_file()

        content = env_file.read_text()
        assert "SILVASONIC_PODMAN_SOCKET=/run/user/501/podman/podman.sock" in content
        assert "DOCKER_HOST=unix:///run/user/501/podman/podman.sock" in content


# ── ensure_gateway_credentials ────────────────────────────────────────────────


@pytest.mark.unit
class TestEnsureGatewayCredentials:
    """Every installation gets its own Gateway password; none is shared."""

    _HASH = "$2a$14$wWbsSaEpl6JMkDEtqNLdOOaJbkc3WKOt/InAQO7X9X1nzpu2YuSh."

    def _hashed(self) -> MagicMock:
        result = MagicMock()
        result.stdout = self._HASH + "\n"
        return result

    def test_generates_hash_into_placeholder(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The hash replaces the commented placeholder; the password is shown once."""
        env = tmp_path / ".env"
        env.write_text(
            "SILVASONIC_GATEWAY_USER=admin\n# SILVASONIC_GATEWAY_PASSWORD_HASH=\nOTHER=1\n"
        )

        with patch("setup.subprocess.run", return_value=self._hashed()) as run:
            ensure_gateway_credentials(env)

        content = env.read_text()
        assert f"SILVASONIC_GATEWAY_PASSWORD_HASH='{self._HASH}'" in content
        assert "OTHER=1" in content
        # The password goes to caddy on stdin, never on the command line
        password = run.call_args.kwargs["input"].strip()
        assert password not in " ".join(run.call_args.args[0])
        assert password not in content
        assert f"admin / {password}" in capsys.readouterr().out

    def test_appends_when_no_placeholder(self, tmp_path: Path) -> None:
        """An older .env without the variable gets it appended."""
        env = tmp_path / ".env"
        env.write_text("POSTGRES_USER=silvasonic\n")

        with patch("setup.subprocess.run", return_value=self._hashed()):
            ensure_gateway_credentials(env)

        assert env.read_text().rstrip().endswith(f"SILVASONIC_GATEWAY_PASSWORD_HASH='{self._HASH}'")

    def test_existing_hash_is_kept(self, tmp_path: Path) -> None:
        """A set password is never replaced."""
        env = tmp_path / ".env"
        env.write_text(f"SILVASONIC_GATEWAY_PASSWORD_HASH='{self._HASH}'\n")

        with patch("setup.subprocess.run") as run:
            ensure_gateway_credentials(env)

        run.assert_not_called()

    def test_empty_quotes_count_as_unset(self, tmp_path: Path) -> None:
        """An empty value would leave the Gateway without a password."""
        env = tmp_path / ".env"
        env.write_text("SILVASONIC_GATEWAY_PASSWORD_HASH=''\n")

        with patch("setup.subprocess.run", return_value=self._hashed()):
            ensure_gateway_credentials(env)

        assert env.read_text() == f"SILVASONIC_GATEWAY_PASSWORD_HASH='{self._HASH}'\n"

    def test_podman_failure_leaves_env_untouched(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Without podman the operator is told how to set the hash by hand."""
        env = tmp_path / ".env"
        env.write_text("# SILVASONIC_GATEWAY_PASSWORD_HASH=\n")

        with patch("setup.subprocess.run", side_effect=OSError("podman not found")):
            ensure_gateway_credentials(env)

        assert env.read_text() == "# SILVASONIC_GATEWAY_PASSWORD_HASH=\n"
        assert "caddy hash-password" in capsys.readouterr().out
