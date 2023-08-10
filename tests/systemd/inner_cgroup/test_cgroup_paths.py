import logging
from typing import Any, Callable, ContextManager, Mapping

from python_on_whales import Container


logger = logging.getLogger(__name__)


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
