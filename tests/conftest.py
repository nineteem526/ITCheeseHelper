"""Keep temporary tests in the project."""
from pathlib import Path
from uuid import uuid4


def pytest_configure(config):
    if not config.option.basetemp:
        parent = Path(__file__).resolve().parents[1] / "artifacts" / "tests"
        parent.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(parent / uuid4().hex)
