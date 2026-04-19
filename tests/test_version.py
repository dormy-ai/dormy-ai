"""Smoke test: package imports and version string is readable."""

import dormy


def test_version_string() -> None:
    assert isinstance(dormy.__version__, str)
    assert dormy.__version__.count(".") >= 2


def test_cli_importable() -> None:
    from dormy.cli.commands import app

    assert app is not None
