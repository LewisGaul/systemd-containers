from __future__ import annotations

import logging

import pytest
from python_on_whales import DockerException as CtrException

from . import utils
from .utils import CtrClient, CtrMgr

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Pytest hooks
# -----------------------------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    """Pytest hook for adding CLI options."""
    group = parser.getgroup("python-on-whales", "python-on-whales")
    group.addoption(
        "--container-host",
        metavar="URI",
        help="Remote host to connect to for running containers",
    )
    group.addoption(
        "--container-exe",
        metavar="EXE",
        default="docker",
        help="The executable used to manage containers, defaults to 'docker'",
    )


def pytest_configure(config: pytest.Config) -> None:
    # Set 'ctr_client' config value.
    ctr_client = CtrClient(
        client_exe=config.getoption("--container-exe"),
        host=config.getoption("--container-host"),
    )
    config.option.ctr_client = ctr_client

    # Set 'cgroup_version' config value.
    try:
        output = ctr_client.run(
            "ubuntu:20.04",
            ["stat", "-f", "/sys/fs/cgroup/", "-c", "%T"],
            detach=False,
            remove=True,
        )
    except CtrException as e:
        pytest.exit(f"Failed to run simple container to determine cgroup version:\n{e}")
    else:
        output = output.strip()
        if output == "tmpfs":
            config.option.cgroup_version = 1
        elif output == "cgroup2fs":
            config.option.cgroup_version = 2
        else:
            pytest.exit(
                "Unable to determine cgroup version from container's "
                f"/sys/fs/cgroup filesystem type {output!r}"
            )
        logger.info("Determined cgroup version %d", config.option.cgroup_version)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture(scope="session")
def ctr_client(pytestconfig: pytest.Config) -> CtrClient:
    """A container client for performing container operations."""
    return pytestconfig.option.ctr_client


@pytest.fixture(scope="session")
def ctr_mgr(ctr_client: CtrClient) -> CtrMgr:
    """The container manager in use."""
    return ctr_client.mgr


@pytest.fixture(scope="session")
def cgroup_version(pytestconfig: pytest.Config) -> int:
    """The container host's cgroup version, either '1' or '2'."""
    return pytestconfig.option.cgroup_version


@pytest.fixture(scope="session", autouse=True)
def host_check(ctr_client: CtrClient) -> None:
    """Check and log properties of the container host."""
    logger.info(
        "Using container manager %s, see debug logs for detailed info",
        ctr_client.mgr,
    )
    utils.run_cmd([ctr_client.exe, "info"], log_output=True)
