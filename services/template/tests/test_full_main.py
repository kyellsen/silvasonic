import pytest
from silvasonic.template.main import main


def test_main(capsys):
    """Test the main entry point of the template service."""
    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "Hello from Silvasonic Template Service!" in captured.out
