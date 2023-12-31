from __future__ import annotations

__all__ = (
    "CtrClient",
    "CtrInitError",
    "CtrMgr",
    "Mount",
    "build_with_dockerfile",
    "get_enabled_cgroup_controllers",
    "run_cmd",
    "strip_ansi_codes",
    "wait_for",
)

import enum
import logging
import os.path
import re
import shlex
import subprocess
import tempfile
import time
from collections import namedtuple
from pathlib import Path
from typing import Iterable, Optional, Callable

from python_on_whales import Container
from python_on_whales import DockerClient as POWCtrClient
from python_on_whales import DockerException as CtrException
from python_on_whales import Image as CtrImage

logger = logging.getLogger(__name__)


class CtrInitError(Exception):
    """Error when a container is starting up."""


class CtrMgr(str, enum.Enum):
    DOCKER = "docker"
    PODMAN = "podman"

    def __str__(self):
        return self.value

    @classmethod
    def from_exe(cls, exe: str) -> "CtrMgr":
        for mgr in cls:
            if mgr in os.path.basename(exe):
                return mgr
        raise ValueError(f"Unrecognised container manager executable {exe!r}")


class CtrClient(POWCtrClient):
    def __init__(self, *args, client_exe: str, host: Optional[str], **kwargs):
        self.exe: str = client_exe
        self.host: Optional[str] = host
        self.mgr: CtrMgr = CtrMgr.from_exe(client_exe)

        if host:
            if CtrMgr.from_exe(client_exe) is CtrMgr.PODMAN:
                ssh_key_path = Path("~/.ssh/id_rsa").expanduser()
                if not ssh_key_path.exists():
                    raise RuntimeError(
                        f"Must have SSH key {ssh_key_path} to use podman remote connection"
                    )
                os.environ["CONTAINER_HOST"] = f"{host}/run/podman/podman.sock"
                os.environ["CONTAINER_SSHKEY"] = str(ssh_key_path)
            else:
                os.environ["DOCKER_HOST"] = host

        super().__init__(*args, client_call=[client_exe], **kwargs)


Mount = namedtuple("Mount", "name, path, type, opts")


def run_cmd(
    cmd: list[str], *, log_output: bool = False, **kwargs
) -> subprocess.CompletedProcess[str]:
    """
    Run a command, capturing stdout and stderr by default, and raising on error.

    :param cmd:
        The command to run.
    :param log_output:
        Whether to log the output.
    :param kwargs:
        Passed through to subprocess.run().

    :raise subprocess.CalledProcessError:
        If the command returns non-zero exit status.
    :raise subprocess.TimeoutExpired:
        If timeout is given and the command times out.

    :return:
        Completed process object from subprocess.run().
    """
    logger.debug("Running command: %r", shlex.join(cmd))
    kwargs = {
        "check": True,
        "text": True,
        "encoding": "utf-8",
        **kwargs,
    }
    if not {"stdout", "stderr", "capture_output"}.intersection(kwargs) or kwargs.pop(
        "capture_output", False
    ):
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    elif "stdout" not in kwargs and kwargs.get("stderr", None) == subprocess.STDOUT:
        kwargs["stdout"] = subprocess.PIPE

    try:
        p: subprocess.CompletedProcess[str] = subprocess.run(cmd, **kwargs)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        if isinstance(e, subprocess.CalledProcessError):
            issue_desc = "failed"
            rc = e.returncode
        else:
            issue_desc = "timed out"
            rc = None
            # Workaround for https://github.com/python/cpython/issues/87597,
            # TimeoutExpired gives bytes rather than str.
            if isinstance(e.stdout, bytes):
                e.stdout = e.stdout.decode("utf-8")
            if isinstance(e.stderr, bytes):
                e.stderr = e.stderr.decode("utf-8")
        if e.stderr:
            logger.debug(
                "Command %s with exit code %s, stdout:\n%s\nstderr:\n%s",
                issue_desc,
                rc,
                e.stdout.strip("\n"),
                e.stderr.strip("\n"),
            )
        elif e.stdout:
            logger.debug(
                "Command %s with exit code %s, output:\n%s",
                issue_desc,
                rc,
                e.stdout.strip("\n"),
            )
        else:
            logger.debug("Command %s with exit code %s", issue_desc, rc)
        raise

    if log_output:
        logger.debug("Command stdout:\n%s", (p.stdout or "").strip("\n"))
        logger.debug("Command stderr:\n%s", (p.stderr or "").strip("\n"))

    return p


def wait_for(
    description: str,
    condition: Callable[[], bool],
    timeout: float,
    interval: float = 0.2,
    *,
    exc_type: type[Exception] | None = Exception,
) -> None:
    """
    Wait for a condition to complete within the given timeout.

    The given condition function should return True on success, return False or
    raise an exception of the type given in 'exc_type' for retry, or raise
    another exception type on unexpected error.

    :param description:
        Description of what's being waited for.
    :param condition:
        The callable representing the condition being waited for.
    :param timeout:
        The retry timeout in seconds.
    :param interval:
        The retry interval in seconds.
    :param exc_type:
        The exception type to catch from calling the condition function, or
        None to not catch exceptions.
    """
    logger.info("Waiting up to %s seconds for %s", timeout, description)
    exception: exc_type | None = None
    end_time = time.monotonic() + timeout
    ready = False
    while True:
        if exc_type:
            try:
                ready = condition()
            except exc_type as e:
                exception = e
        else:
            ready = condition()
        if ready:
            logger.debug("Ready condition met")
            return
        if time.monotonic() >= end_time:
            break
        logger.debug("Trying again in %s seconds...", interval)
        time.sleep(interval)

    msg = f"Timed out after {timeout} seconds waiting for {description}"
    if exception:
        raise TimeoutError(msg) from exception
    else:
        raise TimeoutError(msg)


def strip_ansi_codes(text: str) -> str:
    """Strip all ANSI escape codes from given text."""
    ansi_code = re.compile("\x1b" + r"\[\d+(?:;\d+)*m")
    return ansi_code.sub("", text)


def build_with_dockerfile(
    ctr_client: CtrClient,
    dockerfile: str,
    *,
    tags: str | Iterable[str] = (),
    build_root: Path | None = None,
    **kwargs,
) -> CtrImage:
    """Build a container image using a dockerfile in string form."""
    with tempfile.TemporaryDirectory(prefix="ctr-build-root-") as tmpdir:
        dockerfile_path = Path(tmpdir) / "Dockerfile"
        dockerfile_path.write_text(dockerfile)
        if not build_root:
            build_root = tmpdir
        logger.debug("Building image using Dockerfile:\n%s", dockerfile.strip())
        return ctr_client.legacy_build(
            build_root, file=dockerfile_path, tags=tags, **kwargs
        )


def get_enabled_cgroup_controllers(ctr: Container, cgroup_version: int) -> set[str]:
    if cgroup_version == 1:
        controllers = set()
        cgroup_paths = ctr.execute(
            ["find", "/sys/fs/cgroup", "-type", "d", "-name", "system.slice"]
        ).splitlines()
        return {
            p.removeprefix("/sys/fs/cgroup/").split("/")[0] for p in cgroup_paths
        } - {"systemd", "unified"}
    else:
        assert cgroup_version == 2
        pid_1_cgroup_relpath = (
            ctr.execute(["grep", "0::", "/proc/1/cgroup"]).split(":")[2].lstrip("/")
        )
        # Workaround for the pseudo-private cgroup bind mounts used in
        # cgroupns=host mode, finding the path that's actually visible inside
        # the container.
        try:
            ctr.execute(["ls", "/sys/fs/cgroup/" + pid_1_cgroup_relpath])
        except CtrException:
            *_, pid_1_cgroup_relpath = pid_1_cgroup_relpath.split("/", maxsplit=2)
        return set(
            ctr.execute(
                [
                    "cat",
                    os.path.join(
                        "/sys/fs/cgroup", pid_1_cgroup_relpath, "cgroup.controllers"
                    ),
                ]
            ).split()
        )
