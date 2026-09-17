"""M0 smoke test: the package imports and the console script surface works."""

import subprocess
import sys

import pytest

import alarm_cli
from alarm_cli.cli import main


def test_package_exposes_a_version():
    assert alarm_cli.__version__


def test_version_flag_prints_the_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert alarm_cli.__version__ in capsys.readouterr().out


def test_bare_invocation_prints_help_and_exits_2(capsys):
    assert main([]) == 2
    assert "usage: alarm" in capsys.readouterr().err


def test_console_script_runs_as_a_module():
    result = subprocess.run(
        [sys.executable, "-m", "alarm_cli.cli", "--version"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert alarm_cli.__version__ in result.stdout
