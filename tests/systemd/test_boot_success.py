import logging
from typing import ContextManager

import pytest
from python_on_whales import Container

from ..utils import CtrClient, CtrMgr


logger = logging.getLogger(__name__)


@pytest.mark.parametrize("cgroupns", ["host", "private"])
def test_privileged(
    ctr_client: CtrClient,
    ctr_ctx: ContextManager[Container],
    cgroupns: str,
    cgroup_mode: str,
):
    extra_kwargs = {}
    envs = {}
    if cgroup_mode == "legacy":
        envs["SYSTEMD_PROC_CMDLINE"] = "systemd.legacy_systemd_cgroup_controller=1"
    if ctr_client.mgr is CtrMgr.PODMAN:
        # Disable systemd mode (on by default) for direct comparison to Docker.
        extra_kwargs["systemd"] = False
    else:
        # Docker does not set the 'container' env var.
        envs["container"] = str(ctr_client.mgr)

    with ctr_ctx(
        privileged=True,
        envs=envs,
        cgroupns=cgroupns,
        **extra_kwargs,
    ) as ctr:
        pass


@pytest.mark.parametrize("cgroupns", ["host", "private"])
def test_privileged_systemd_mode(
    ctr_client: CtrClient,
    ctr_ctx: ContextManager[Container],
    cgroupns: str,
    cgroup_mode: str,
):
    envs = {}
    if ctr_client.mgr is not CtrMgr.PODMAN:
        pytest.skip("Systemd mode only supported by Podman")
    if cgroup_mode == "legacy":
        envs["SYSTEMD_PROC_CMDLINE"] = "systemd.legacy_systemd_cgroup_controller=1"
    with ctr_ctx(
        privileged=True,
        envs=envs,
        systemd=True,
        cgroupns=cgroupns,
    ) as ctr:
        pass


def test_non_priv_with_host_cgroup_passthrough(
    ctr_client: CtrClient, ctr_ctx: ContextManager[Container], cgroup_mode: str
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
    extra_kwargs = {}
    envs = {}
    if cgroup_mode == "legacy":
        envs["SYSTEMD_PROC_CMDLINE"] = "systemd.legacy_systemd_cgroup_controller=1"
    if ctr_client.mgr is CtrMgr.PODMAN:
        # Disable systemd mode (on by default) for direct comparison to Docker.
        extra_kwargs["systemd"] = False
    else:
        # Docker does not set the 'container' env var.
        envs["container"] = str(ctr_client.mgr)

    with ctr_ctx(
        cap_add=["sys_admin"],
        tmpfs=["/run"],
        envs=envs,
        volumes=[("/sys/fs/cgroup", "/sys/fs/cgroup")],
        cgroupns="host",
        **extra_kwargs,
    ) as ctr:
        pass


@pytest.mark.parametrize("cgroupns", ["host", "private"])
def test_non_priv_systemd_mode(
    ctr_client: CtrClient,
    ctr_ctx: ContextManager[Container],
    cgroupns: str,
    cgroup_mode: str,
):
    if ctr_client.mgr is not CtrMgr.PODMAN:
        pytest.skip("Systemd mode only supported by Podman")
    envs = {}
    if cgroup_mode == "legacy":
        envs["SYSTEMD_PROC_CMDLINE"] = "systemd.legacy_systemd_cgroup_controller=1"
    with ctr_ctx(
        cap_add=["sys_admin"], envs=envs, systemd=True, cgroupns=cgroupns
    ) as ctr:
        pass
