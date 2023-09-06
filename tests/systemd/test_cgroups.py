from __future__ import annotations

import logging
from typing import Any

from .. import utils
from . import CtrCtxType

logger = logging.getLogger(__name__)


def test_cgroup_mounts(
    ctr_ctx: CtrCtxType,
    default_ctr_kwargs: dict[str, Any],
):
    with ctr_ctx(**default_ctr_kwargs) as ctr:
        output = ctr.execute(["findmnt", "-R", "/sys/fs/cgroup"])
        logger.debug("Cgroup mounts:\n%s", output)


def test_cgroup_paths(
    ctr_ctx: CtrCtxType,
    default_ctr_kwargs: dict[str, Any],
):
    with ctr_ctx(**default_ctr_kwargs) as ctr:
        output = ctr.execute(["cat", "/proc/1/cgroup"])
        logger.debug("Got PID 1 cgroups:\n%s", output)
        journald_ctr_pid = int(ctr.execute(["pidof", "systemd-journald"]))
        output = ctr.execute(["cat", f"/proc/{journald_ctr_pid}/cgroup"])
        logger.debug(
            "Got systemd-journald (PID %d) cgroups:\n%s", journald_ctr_pid, output
        )


def test_cgroup_controllers(
    ctr_ctx: CtrCtxType,
    default_ctr_kwargs: dict[str, Any],
    cgroup_version: int,
):
    with ctr_ctx(**default_ctr_kwargs) as ctr:
        enabled_controllers = utils.get_enabled_cgroup_controllers(ctr, cgroup_version)
        logger.debug("Enabled controllers: %s", enabled_controllers)
