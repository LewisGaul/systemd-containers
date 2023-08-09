from __future__ import annotations

import logging
from pathlib import Path

import pytest

from ...utils import CtrClient, Mount


logger = logging.getLogger(__name__)


@pytest.fixture(scope="package", autouse=True)
def host_check_systemd(cgroup_version: int, ctr_client: CtrClient) -> None:
    """
    Check properties of the container host for running systemd containers.
    """
    # Check /sys/fs/cgroup/systemd exists if host is on cgroups v1.
    if cgroup_version == 1:
        mounts = [
            Mount(*L.split()[:4]) for L in Path("/proc/mounts").read_text().splitlines()
        ]
        if ("/sys/fs/cgroup/systemd", "cgroup") not in [
            (m.path, m.type) for m in mounts
        ]:
            pytest.fail(
                "Default systemd containers cannot run on a cgroup v1 host that "
                "doesn't have /sys/fs/cgroup/systemd mounted"
            )
