"""Checkpoint 1: the unified validator passes on every available repo."""

import pytest

from bench import check_data
from bench.common import data


@pytest.mark.parametrize("repo_id", data.available_repos())
def test_check_data_passes(repo_id):
    rep = check_data.validate_repo(repo_id)
    assert rep.checks > 0, f"{repo_id}: no checks ran"
    assert not rep.failures, f"{repo_id} failures:\n" + "\n".join(rep.failures)


def test_all_four_repos_present():
    repos = data.available_repos()
    assert set(repos) == {"ops-office", "orders-api", "release-tools", "shop-web"}, repos
