from pathlib import Path


def pytest_addoption(parser):
    parser.addoption("--gsd-settings", default=str(Path(__file__).resolve().parents[2] / "lab-operator/settings.json"),
                     help="Existing operator settings; tests create independent temporary state and keys")
