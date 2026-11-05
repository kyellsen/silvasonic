"""Unit tests for scripts/check.py — the scan that refuses ``type: ignore``.

ty skips a mypy-coded ``# type: ignore[...]`` without a word and reads a bare
one as silencing its whole line, so the gate refuses both in the folders
``[tool.ty.src]`` includes.
"""

from __future__ import annotations

from pathlib import Path

import check
import pytest


def _project(tmp_path: Path, source: str) -> Path:
    """A project whose ty include holds one package module and one root file."""
    (tmp_path / "pyproject.toml").write_text(
        '[tool.ty.src]\ninclude = ["conftest.py", "pkg"]\n', encoding="utf-8"
    )
    (tmp_path / "conftest.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text(source, encoding="utf-8")
    return tmp_path


@pytest.mark.unit
class TestCheckTypeIgnores:
    """The Type-ignore Syntax stage."""

    @pytest.mark.parametrize(
        "comment", ["# type: ignore", "# type: ignore[assignment]", "#type:ignore[misc]"]
    )
    def test_refuses_a_type_ignore_comment(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        comment: str,
    ) -> None:
        """Bare or with mypy's codes, the comment fails the stage and is named."""
        monkeypatch.setattr(check, "PROJECT_ROOT", _project(tmp_path, f"x = 1  {comment}\n"))
        with pytest.raises(SystemExit, match="1"):
            check.check_type_ignores()
        assert f"pkg/mod.py:1: {comment}" in capsys.readouterr().out

    def test_passes_a_ty_ignore_and_a_quoted_type_ignore(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Only comments count, and ty's own suppression is the one to use."""
        source = 'x: int = "a"  # ty: ignore[invalid-assignment]\nhint = "# type: ignore"\n'
        monkeypatch.setattr(check, "PROJECT_ROOT", _project(tmp_path, source))
        check.check_type_ignores()
        assert "2 files without a type: ignore" in capsys.readouterr().out

    def test_fails_when_the_include_holds_no_python_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An include that matches nothing would pass vacuously."""
        (tmp_path / "pyproject.toml").write_text(
            '[tool.ty.src]\ninclude = ["missing"]\n', encoding="utf-8"
        )
        monkeypatch.setattr(check, "PROJECT_ROOT", tmp_path)
        with pytest.raises(SystemExit, match="1"):
            check.check_type_ignores()
