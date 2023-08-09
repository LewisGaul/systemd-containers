from __future__ import annotations

__all__ = (
    "CtrClient",
    "CtrInitError",
    "CtrMgr",
    "Mount",
    "build_with_dockerfile",
    "run_cmd",
)

import enum
import logging
import os.path
import shlex
import subprocess
import tempfile
from collections import namedtuple
from pathlib import Path
from typing import Iterable, Optional

from python_on_whales import DockerClient as POWCtrClient
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


def build_with_dockerfile(
    ctr_client: CtrClient,
    dockerfile: str,
    *,
    tags: str | Iterable[str] = (),
    build_root: Path | None = None,
) -> CtrImage:
    """Build a container image using a dockerfile in string form."""
    with tempfile.TemporaryDirectory(prefix="ctr-build-root-") as tmpdir:
        dockerfile_path = Path(tmpdir) / "Dockerfile"
        dockerfile_path.write_text(dockerfile)
        if not build_root:
            build_root = tmpdir
        logger.debug("Building image using Dockerfile:\n%s", dockerfile.strip())
        return ctr_client.legacy_build(build_root, file=dockerfile_path, tags=tags)
