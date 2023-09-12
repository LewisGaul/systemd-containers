from __future__ import annotations

import functools
import logging
import time
from typing import Any, Optional

import pytest
from python_on_whales import DockerException as CtrException
from python_on_whales import Image as CtrImage

from .. import utils
from ..utils import CtrInitError
from . import CtrCtxType

logger = logging.getLogger(__name__)


@pytest.fixture
def delayed_start_ctr_ctx(ctr_ctx: CtrCtxType, pkg_image: CtrImage) -> CtrCtxType:
    assert len(pkg_image.config.entrypoint) == 1
    orig_entrypoint = pkg_image.config.entrypoint[0]
    return functools.partial(
        ctr_ctx,
        entrypoint="",
        command=["bash", "-c", f"sleep 1 && exec {orig_entrypoint}"],
    )


def test_late_exec_proc(
    ctr_ctx: CtrCtxType,
    default_ctr_kwargs: dict[str, Any],
    cgroup_version: int,
    setup_mode: Optional[str],
):
    with ctr_ctx(**default_ctr_kwargs) as ctr:
        output = ctr.execute(["cat", "/proc/self/cgroup"])
        logger.debug("Got exec proc cgroups:\n%s", output)
        enabled_controllers = utils.get_enabled_cgroup_controllers(ctr, cgroup_version)
        logger.debug("Enabled controllers: %s", enabled_controllers)
        if setup_mode != "minimal":
            assert enabled_controllers >= {"memory", "pids"}
        else:
            logger.warning("Controllers not enabled with setup_mode=%s", setup_mode)


def test_early_exec_proc(
    delayed_start_ctr_ctx: CtrCtxType,
    default_ctr_kwargs: dict[str, Any],
    cgroup_version: int,
    setup_mode: Optional[str],
):
    with delayed_start_ctr_ctx(**default_ctr_kwargs, wait=False) as ctr:
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
        if setup_mode != "minimal":
            assert enabled_controllers >= {"memory", "pids"}
        else:
            logger.warning("Controllers not enabled with setup_mode=%s", setup_mode)


def test_exec_proc_spam(
    delayed_start_ctr_ctx: CtrCtxType,
    default_ctr_kwargs: dict[str, Any],
    cgroup_version: int,
    setup_mode: Optional[str],
):
    with delayed_start_ctr_ctx(**default_ctr_kwargs, wait=False) as ctr:
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
        if setup_mode != "minimal":
            assert enabled_controllers >= {"memory", "pids"}
        else:
            logger.warning("Controllers not enabled with setup_mode=%s", setup_mode)
