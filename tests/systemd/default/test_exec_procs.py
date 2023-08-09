import logging
from typing import Callable, ContextManager

import pytest
from python_on_whales import Container


logger = logging.getLogger(__name__)


@pytest.mark.parametrize("cgroupns", ["host", "private"])
def test_exec_proc_cgroup(
    ctr_ctx: Callable[..., ContextManager[Container]],
    cgroupns: str,
    cgroup_mode: str,
):
    with ctr_ctx(
        privileged=True,
        cgroupns=cgroupns,
        legacy_cgroup_mode=(cgroup_mode == "legacy"),
    ) as ctr:
        output = ctr.execute(["cat", "/proc/self/cgroup"])
        logger.debug("Got exec proc cgroups:\n%s", output)
