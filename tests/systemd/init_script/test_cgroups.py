import logging
from typing import Any, Callable, ContextManager, Mapping

from python_on_whales import Container

from ... import utils


logger = logging.getLogger(__name__)


def test_cgroup_mounts(
    ctr_ctx: Callable[..., ContextManager[Container]],
    default_ctr_kwargs: Mapping[str, Any],
):
    with ctr_ctx(**default_ctr_kwargs) as ctr:
        output = ctr.execute(["findmnt", "-R", "/sys/fs/cgroup"])
        logger.debug("Cgroup mounts:\n%s", output)


def test_cgroup_paths(
    ctr_ctx: Callable[..., ContextManager[Container]],
    default_ctr_kwargs: Mapping[str, Any],
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
    ctr_ctx: Callable[..., ContextManager[Container]],
    default_ctr_kwargs: Mapping[str, Any],
    cgroup_version: int,
):
    with ctr_ctx(**default_ctr_kwargs) as ctr:
        enabled_controllers = utils.get_enabled_cgroup_controllers(ctr, cgroup_version)
        logger.debug("Enabled controllers: %s", enabled_controllers)
