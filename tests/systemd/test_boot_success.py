import logging

import pytest

from ..utils import CtrMgr
from . import CtrCtxType

logger = logging.getLogger(__name__)


def test_privileged(ctr_ctx: CtrCtxType, ctr_mgr: CtrMgr):
    if ctr_mgr is CtrMgr.DOCKER:
        # Docker does not set the 'container' env var, which systemd
        # uses to determine it should run in container mode.
        envs = dict(container="docker")
    with ctr_ctx(
        privileged=True,
        envs=envs,
        log_boot_output=True,
    ) as ctr:
        pass


def test_privileged_systemd_mode(ctr_ctx: CtrCtxType):
    with ctr_ctx(
        privileged=True,
        systemd=True,
        log_boot_output=True,
    ) as ctr:
        pass


@pytest.mark.setup_mode([None])
@pytest.mark.cgroupns(["host"])
def test_non_priv_with_host_cgroup_passthrough(
    ctr_ctx: CtrCtxType,
    ctr_mgr: CtrMgr,
    cgroup_version: int,
):
    """
    Non-privileged systemd container passing through the host's cgroupfs.

    Docker does not properly support running systemd in non-privileged
    containers, so the following workarounds are needed:
    1. Bind mount the host's /sys/fs/cgroup over the container's /sys/fs/cgroup
    2. Must not use a private cgroup namespace because of #1.
    3. Ensure /run is a tmpfs
    4. Set the 'container' env var to something (value not that important)
    """
    if ctr_mgr is CtrMgr.DOCKER:
        # Docker does not set the 'container' env var, which systemd
        # uses to determine it should run in container mode.
        envs = dict(container="docker")
    if cgroup_version == 1:
        # The tmpfs mount doesn't need to be writable on cgroups v1.
        cgroup_vol = ("/sys/fs/cgroup", "/sys/fs/cgroup", "ro")
    else:
        # The cgroup2 mount does need to be writable on cgroups v2.
        cgroup_vol = ("/sys/fs/cgroup", "/sys/fs/cgroup", "rw")

    with ctr_ctx(
        cap_add=["sys_admin"],
        tmpfs=["/run"],
        volumes=[cgroup_vol],
        cgroupns="host",
        envs=envs,
        log_boot_output=True,
    ) as ctr:
        pass


def test_non_priv_systemd_mode(ctr_ctx: CtrCtxType):
    """
    Test running with Podman's systemd mode, which automatically sets up the
    container for running systemd in non-privileged.
    """
    with ctr_ctx(
        cap_add=["sys_admin"],
        systemd=True,
        log_boot_output=True,
    ) as ctr:
        pass
