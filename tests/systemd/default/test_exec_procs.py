import logging
import time
from typing import Callable, ContextManager

import pytest
from python_on_whales import Container
from python_on_whales import DockerException as CtrException
from python_on_whales import Image as CtrImage

from ... import utils
from ...utils import CtrInitError


logger = logging.getLogger(__name__)


@pytest.mark.parametrize("cgroupns", ["host", "private"])
def test_late_exec_proc(
    ctr_ctx: Callable[..., ContextManager[Container]],
    cgroupns: str,
    cgroup_mode: str,
    cgroup_version: int,
):
    with ctr_ctx(
        privileged=True,
        cgroupns=cgroupns,
        legacy_cgroup_mode=(cgroup_mode == "legacy"),
    ) as ctr:
        output = ctr.execute(["cat", "/proc/self/cgroup"])
        logger.debug("Got exec proc cgroups:\n%s", output)
        enabled_controllers = utils.get_enabled_cgroup_controllers(ctr, cgroup_version)
        logger.debug("Enabled controllers: %s", enabled_controllers)
        assert enabled_controllers >= {"memory", "pids"}


@pytest.mark.parametrize("cgroupns", ["host", "private"])
def test_early_exec_proc(
    ctr_ctx: Callable[..., ContextManager[Container]],
    delayed_systemd_image: CtrImage,
    cgroupns: str,
    cgroup_mode: str,
    cgroup_version: int,
):
    with ctr_ctx(
        delayed_systemd_image,
        privileged=True,
        cgroupns=cgroupns,
        legacy_cgroup_mode=(cgroup_mode == "legacy"),
        wait=False,
    ) as ctr:
        ctr.execute(["sleep", "inf"], detach=True)
        exec_proc_ctr_pid = max(int(p) for p in ctr.execute(["pidof", "sleep"]).split())
        output = ctr.execute(["cat", f"/proc/{exec_proc_ctr_pid}/cgroup"])
        logger.debug("Got exec proc cgroups before systemd starts:\n%s", output)
        # Wait for systemd boot to complete inside the container.
        time.sleep(1)  # wait for the 1 sec sleep to finish
        try:
            ctr.execute(["systemctl", "is-system-running", "--wait"])
        except CtrException as e:
            logger.debug("Container boot logs:\n%s", ctr.logs())
            raise CtrInitError("Systemd container failed to start") from e
        output = ctr.execute(["cat", f"/proc/{exec_proc_ctr_pid}/cgroup"])
        logger.debug("Got exec proc cgroups after systemd started:\n%s", output)
        enabled_controllers = utils.get_enabled_cgroup_controllers(ctr, cgroup_version)
        logger.debug("Enabled controllers: %s", enabled_controllers)
        assert enabled_controllers >= {"memory", "pids"}


@pytest.mark.parametrize("cgroupns", ["host", "private"])
def test_exec_proc_spam(
    ctr_ctx: Callable[..., ContextManager[Container]],
    delayed_systemd_image: CtrImage,
    cgroupns: str,
    cgroup_mode: str,
    cgroup_version: int,
):
    with ctr_ctx(
        delayed_systemd_image,
        privileged=True,
        cgroupns=cgroupns,
        legacy_cgroup_mode=(cgroup_mode == "legacy"),
        wait=False,
    ) as ctr:
        # Spam creating sleeping exec processes for 2 seconds - 1 second before
        # systemd starts and 1 second while it starts up.
        end_time = time.time() + 2
        while time.time() < end_time:
            ctr.execute(["sleep", "inf"], detach=True)
        # Wait for systemd boot to complete inside the container.
        try:
            ctr.execute(["systemctl", "is-system-running", "--wait"])
        except CtrException as e:
            logger.debug("Container boot logs:\n%s", ctr.logs())
            raise CtrInitError("Systemd container failed to start") from e
        exec_proc_ctr_pids = sorted(
            int(p) for p in ctr.execute(["pidof", "sleep"]).split()
        )
        output = ctr.execute(["cat", "/proc/1/cgroup"])
        logger.debug("Got PID 1 cgroups:\n%s", output)
        for pid in exec_proc_ctr_pids:
            output = ctr.execute(["cat", f"/proc/{pid}/cgroup"])
            logger.debug("Got exec proc %d cgroups:\n%s", pid, output)
        enabled_controllers = utils.get_enabled_cgroup_controllers(ctr, cgroup_version)
        logger.debug("Enabled controllers: %s", enabled_controllers)
        assert enabled_controllers >= {"memory", "pids"}
