import logging
import re

import pytest

from .. import utils
from ..utils import CtrMgr
from . import CtrCtxType

logger = logging.getLogger(__name__)


def _check_ctr_boot_logs(ctr_logs: str) -> list[str]:
    """
    Check for unexpected warnings/messages in the container's boot logs.

    :param ctr_logs:
        The systemd container logs to check.
    :return:
        A list of unexpected boot log lines.
    """
    # Split the boot logs into sections:
    #  1. First systemd output 'systemd <version> ...'
    #  2. Unit output from first '[  OK  ] ...'
    #  3. Startup completed, login prompt
    boot_log_lines = ctr_logs.splitlines()
    section = 0
    unexpected_lines = []
    reached_login_prompt = False
    for line in boot_log_lines:
        coloured_line = line
        line = utils.strip_ansi_codes(line)
        if not line.strip():
            continue
        if section == 0:
            allowed_line_regexes = [r".*"]
            if re.match(r"systemd \d+(?:\.\S+)? running in system mode", line):
                section = 1
                continue
        elif section == 1:
            allowed_line_regexes = [
                rf"Detected virtualization .*",
                r"Detected architecture .*",
                r"Welcome .*",
                r"Set hostname .*",
                r"Initializing machine ID .*",
            ]
            if line.startswith("[  OK  ] "):
                section = 2
                continue
        elif section == 2:
            allowed_line_regexes = [
                r"\[  OK  \] \S.*",
                r"         \S.*",
                r"modprobe@\w+\.service: Succeeded\.",
            ]
            if re.fullmatch(r"Ubuntu .* console", line):
                section = 3
                continue
        elif section == 3:
            allowed_line_regexes = [
                r"\w+ login: ",
            ]
            if re.fullmatch(r"\w+ login: ", line):
                reached_login_prompt = True

        if not any(re.fullmatch(rgx, line) for rgx in allowed_line_regexes):
            unexpected_lines.append(coloured_line)

    return unexpected_lines


def _warn_unexpected_boot_logs(ctr_logs: str) -> None:
    """Warn if there are unexpected lines in the boot logs."""
    unexpected_boot_lines = _check_ctr_boot_logs(ctr_logs)
    if unexpected_boot_lines:
        logger.warning(
            "Unexpected boot log lines:\n%s", "\n".join(unexpected_boot_lines)
        )


def test_privileged(ctr_ctx: CtrCtxType, ctr_mgr: CtrMgr):
    """Test running the container in privileged mode."""
    if ctr_mgr is CtrMgr.DOCKER:
        # Docker does not set the 'container' env var, which systemd
        # uses to determine it should run in container mode. Maybe not strictly
        # needed.
        envs = dict(container="docker")
    with ctr_ctx(
        privileged=True,
        envs=envs,
        log_boot_output=True,
    ) as ctr:
        _warn_unexpected_boot_logs(ctr.logs())


@pytest.mark.setup_mode([None])
@pytest.mark.cgroupns(["host"])
def test_non_priv_with_host_cgroup_passthrough(
    ctr_ctx: CtrCtxType,
    ctr_mgr: CtrMgr,
    cgroup_version: int,
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
    if ctr_mgr is CtrMgr.DOCKER:
        # Docker does not set the 'container' env var, which systemd
        # uses to determine it should run in container mode.
        envs = dict(container="docker")
    if cgroup_version == 1:
        # The tmpfs mount doesn't need to be writable on cgroups v1.
        cgroup_vol = ("/sys/fs/cgroup", "/sys/fs/cgroup", "ro")
    else:
        # The cgroup2 mount does need to be writable on cgroups v2.
        cgroup_vol = ("/sys/fs/cgroup", "/sys/fs/cgroup", "rw")

    with ctr_ctx(
        cap_add=["sys_admin"],
        tmpfs=["/run"],
        volumes=[cgroup_vol],
        cgroupns="host",
        envs=envs,
        log_boot_output=True,
    ) as ctr:
        _warn_unexpected_boot_logs(ctr.logs())


@pytest.mark.ctr_mgr(CtrMgr.PODMAN)
def test_non_priv_systemd_mode(ctr_ctx: CtrCtxType):
    """
    Test running with Podman's systemd mode, which automatically sets up the
    container for running systemd in non-privileged.
    """
    with ctr_ctx(
        cap_add=["sys_admin"],
        systemd=True,
        log_boot_output=True,
    ) as ctr:
        _warn_unexpected_boot_logs(ctr.logs())


@pytest.mark.ctr_mgr(CtrMgr.PODMAN)
def test_privileged_systemd_mode(ctr_ctx: CtrCtxType):
    """Test running the container in privileged with Podman's systemd mode."""
    with ctr_ctx(
        privileged=True,
        systemd=True,
        log_boot_output=True,
    ) as ctr:
        _warn_unexpected_boot_logs(ctr.logs())
