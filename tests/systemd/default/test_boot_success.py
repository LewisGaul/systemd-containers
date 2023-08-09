import logging
from typing import Callable, ContextManager

import pytest
from python_on_whales import Container

from ...utils import CtrClient, CtrMgr


logger = logging.getLogger(__name__)


@pytest.mark.parametrize("cgroupns", ["host", "private"])
def test_privileged(
    ctr_ctx: Callable[..., ContextManager[Container]],
    cgroupns: str,
    cgroup_mode: str,
):
    with ctr_ctx(
        privileged=True,
        cgroupns=cgroupns,
        legacy_cgroup_mode=(cgroup_mode == "legacy"),
        log_boot_output=True,
    ) as ctr:
        pass


@pytest.mark.parametrize("cgroupns", ["host", "private"])
def test_privileged_systemd_mode(
    ctr_ctx: Callable[..., ContextManager[Container]],
    ctr_client: CtrClient,
    cgroupns: str,
    cgroup_mode: str,
):
    if ctr_client.mgr is not CtrMgr.PODMAN:
        pytest.skip("Systemd mode only supported by Podman")
    with ctr_ctx(
        privileged=True,
        systemd=True,
        cgroupns=cgroupns,
        legacy_cgroup_mode=(cgroup_mode == "legacy"),
        log_boot_output=True,
    ) as ctr:
        pass


def test_non_priv_with_host_cgroup_passthrough(
    ctr_ctx: Callable[..., ContextManager[Container]],
    cgroup_mode: str,
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
    if cgroup_mode == "unified":
        cgroup_vol = ("/sys/fs/cgroup", "/sys/fs/cgroup", "rw")
    else:
        cgroup_vol = ("/sys/fs/cgroup", "/sys/fs/cgroup", "ro")

    with ctr_ctx(
        cap_add=["sys_admin"],
        tmpfs=["/run"],
        volumes=[cgroup_vol],
        cgroupns="host",
        legacy_cgroup_mode=(cgroup_mode == "legacy"),
        log_boot_output=True,
    ) as ctr:
        pass


@pytest.mark.parametrize("cgroupns", ["host", "private"])
def test_non_priv_systemd_mode(
    ctr_ctx: Callable[..., ContextManager[Container]],
    ctr_client: CtrClient,
    cgroupns: str,
    cgroup_mode: str,
):
    """
    Test running with Podman's systemd mode, which automatically sets up the
    container for running systemd in non-privileged.
    """
    if ctr_client.mgr is not CtrMgr.PODMAN:
        pytest.skip("Systemd mode only supported by Podman")
    with ctr_ctx(
        cap_add=["sys_admin"],
        systemd=True,
        cgroupns=cgroupns,
        legacy_cgroup_mode=(cgroup_mode == "legacy"),
        log_boot_output=True,
    ) as ctr:
        pass
