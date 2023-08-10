import logging
import time
from typing import Any, Callable, ContextManager, Mapping

import pytest
from pytest import FixtureRequest
from python_on_whales import Container
from python_on_whales import DockerException as CtrException
from python_on_whales import Image as CtrImage

from ... import utils
from ...utils import CtrClient, CtrInitError, CtrMgr


logger = logging.getLogger(__name__)


@pytest.fixture(params=["host", "private"])
def cgroupns(request: FixtureRequest) -> str:
    return request.param


@pytest.fixture
def default_ctr_kwargs(
    ctr_client: CtrClient,
    cgroupns: str,
    cgroup_mode: str,
) -> Mapping[str, Any]:
    kwargs = dict(
        cgroupns=cgroupns,
        legacy_cgroup_mode=(cgroup_mode == "legacy"),
    )
    if ctr_client.mgr is CtrMgr.PODMAN:
        kwargs["systemd"] = "always"
        kwargs["cap_add"] = ["sys_admin"]
    else:
        kwargs["privileged"] = True
    return kwargs


def test_late_exec_proc(
    ctr_ctx: Callable[..., ContextManager[Container]],
    default_ctr_kwargs: Mapping[str, Any],
    cgroup_version: int,
):
    with ctr_ctx(**default_ctr_kwargs) as ctr:
        output = ctr.execute(["cat", "/proc/self/cgroup"])
        logger.debug("Got exec proc cgroups:\n%s", output)
        enabled_controllers = utils.get_enabled_cgroup_controllers(ctr, cgroup_version)
        logger.debug("Enabled controllers: %s", enabled_controllers)
        assert enabled_controllers >= {"memory", "pids"}


def test_early_exec_proc(
    ctr_ctx: Callable[..., ContextManager[Container]],
    default_ctr_kwargs: Mapping[str, Any],
    cgroup_version: int,
):
    with ctr_ctx(
        entrypoint="bash",
        command=["-c", "sleep 1 && exec /init_script.sh"],
        **default_ctr_kwargs,
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


def test_exec_proc_spam(
    ctr_ctx: Callable[..., ContextManager[Container]],
    default_ctr_kwargs: Mapping[str, Any],
    cgroup_version: int,
):
    with ctr_ctx(
        entrypoint="bash",
        command=["-c", "sleep 1 && exec /init_script.sh"],
        **default_ctr_kwargs,
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
        prev_exec_proc_cgroups = None
        for pid in exec_proc_ctr_pids:
            output = ctr.execute(["cat", f"/proc/{pid}/cgroup"])
            if output != prev_exec_proc_cgroups:
                logger.debug("Got exec proc %d cgroups:\n%s", pid, output)
                prev_exec_proc_cgroups = output
        enabled_controllers = utils.get_enabled_cgroup_controllers(ctr, cgroup_version)
        logger.debug("Enabled controllers: %s", enabled_controllers)
        assert enabled_controllers >= {"memory", "pids"}
