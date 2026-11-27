import pytest

from bench.runner import data


@pytest.fixture(scope="session")
def repo():
    return data.load_repo("release-tools")
