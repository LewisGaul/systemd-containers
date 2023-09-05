import logging
from typing import Callable, ContextManager

import pytest
from python_on_whales import Container

from ...utils import CtrClient, CtrMgr


logger = logging.getLogger(__name__)


def test_privileged(
    ctr_ctx: Callable[..., ContextManager[Container]],
    cgroupns_param: str,
    cgroup_mode: str,
):
    with ctr_ctx(
        privileged=True,
        cgroupns=cgroupns_param,
        legacy_cgroup_mode=(cgroup_mode == "legacy"),
        log_boot_output=True,
    ) as ctr:
        pass


def test_non_priv(
    ctr_ctx: Callable[..., ContextManager[Container]],
    cgroupns_param: str,
    cgroup_mode: str,
):
    with ctr_ctx(
        cap_add=["sys_admin"],
        cgroupns=cgroupns_param,
        legacy_cgroup_mode=(cgroup_mode == "legacy"),
        log_boot_output=True,
    ) as ctr:
        pass


def test_privileged_systemd_mode(
    ctr_ctx: Callable[..., ContextManager[Container]],
    ctr_client: CtrClient,
    cgroupns_param: str,
    cgroup_mode: str,
):
    if ctr_client.mgr is not CtrMgr.PODMAN:
        pytest.skip("Systemd mode only supported by Podman")
    with ctr_ctx(
        privileged=True,
        systemd=True,
        cgroupns=cgroupns_param,
        legacy_cgroup_mode=(cgroup_mode == "legacy"),
        log_boot_output=True,
    ) as ctr:
        pass


def test_non_priv_systemd_mode(
    ctr_ctx: Callable[..., ContextManager[Container]],
    ctr_client: CtrClient,
    cgroupns_param: str,
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
        cgroupns=cgroupns_param,
        legacy_cgroup_mode=(cgroup_mode == "legacy"),
        log_boot_output=True,
    ) as ctr:
        pass
