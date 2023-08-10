import contextlib
import logging
import textwrap
import time
from typing import Any, Callable, ContextManager, Generator, Mapping, Optional

import pytest
from pytest import FixtureRequest
from python_on_whales import Container
from python_on_whales import DockerException as CtrException
from python_on_whales import Image as CtrImage

from .. import utils
from ..utils import CtrClient, CtrInitError, CtrMgr


logger = logging.getLogger(__name__)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parameterise tests based on test function parameters."""
    if "cgroup_mode" in metafunc.fixturenames:
        if metafunc.config.option.cgroup_version == 1:
            metafunc.parametrize("cgroup_mode", ["legacy", "hybrid"])
        else:
            assert metafunc.config.option.cgroup_version == 2
            metafunc.parametrize("cgroup_mode", ["unified"])


@pytest.fixture(scope="package")
def systemd_image(ctr_client: CtrClient) -> CtrImage:
    # Note that systemd-resolved.service requires CAP_NET_RAW, which is not
    # granted by podman by default. To avoid requiring this extra capability
    # we simply mask the service - it's not clear whether it makes sense in a
    # container anyway?
    dockerfile = textwrap.dedent(
        f"""\
        FROM ubuntu:20.04
        RUN apt-get update -y \\
            && apt-get install -y systemd \\
            && ln -s /lib/systemd/systemd /sbin/init \\
            && systemctl mask systemd-resolved.service \\
            && systemctl set-default multi-user.target
        RUN echo 'root:root' | chpasswd
        STOPSIGNAL SIGRTMIN+3
        ENTRYPOINT ["/sbin/init"]
        """
    )
    image = utils.build_with_dockerfile(
        ctr_client, dockerfile, tags="ubuntu-systemd:20.04"
    )
    yield image


@pytest.fixture(scope="package")
def pkg_image(systemd_image: CtrClient) -> CtrImage:
    """The default image for the package."""
    return systemd_image


@pytest.fixture
def ctr_ctx(
    request: pytest.FixtureRequest, ctr_client: CtrClient, pkg_image: CtrImage
) -> Callable[..., ContextManager[Container]]:
    """Fixture providing a context manager for starting a systemd container."""

    @contextlib.contextmanager
    def ctr_ctx_mgr(
        image: Optional[CtrImage] = None,
        *args,
        systemd: Optional[bool] = None,
        legacy_cgroup_mode: bool = False,
        log_boot_output: bool = False,
        wait: bool = True,
        **kwargs,
    ) -> Generator[Container, None, None]:
        """
        A context manager for running a systemd container.

        Sets some default argument values and waits for systemd to start up in
        the container before yielding.

        :param image:
            Override the container image from the default systemd image.
        :param systemd:
            Whether to enable systemd mode. Defaults to systemd mode being off,
            even for podman which normally defaults to it being on (this is
            done for consistency with docker).
        :param legacy_cgroup_mode:
            Whether to force systemd to run in legacy cgroup mode.
        :param log_boot_output:
            Whether to always log boot output (if waiting on boot completion).
        :param wait:
            Whether to wait for boot to complete successfully.
        :param args:
            Positional arguments passed through to Container.run().
        :param kwargs:
            Keyword arguments passed through to Container.run().
        :yield:
            The Container object.
        :raise CtrInitError:
            If systemd in the container fails to start.
        """
        # Determine args to use for the container.
        if image is None:
            image = pkg_image
        if systemd is None and ctr_client.mgr is CtrMgr.PODMAN:
            # Disable podman's systemd mode by default for consistency
            # when comparing with docker.
            systemd = False
        if systemd is not None:
            kwargs["systemd"] = systemd
        if ctr_client.mgr is CtrMgr.DOCKER:
            # Docker does not set the 'container' env var, which systemd
            # uses to determine it should run in container mode.
            kwargs.setdefault("envs", {}).setdefault("container", "docker")
        if legacy_cgroup_mode:
            # Force systemd to run in legacy cgroup v1 mode.
            assert request.config.option.cgroup_version == 1
            kwargs.setdefault("envs", {})[
                "SYSTEMD_PROC_CMDLINE"
            ] = "systemd.legacy_systemd_cgroup_controller=1"
        kwargs.setdefault("tty", True)
        if not kwargs.setdefault("detach", True):
            raise TypeError("Running container attached is not supported")
        if kwargs.setdefault("remove", False):
            raise TypeError(
                "Removing container on exit breaks logging so is not supported"
            )
        kwargs.setdefault("name", f"pow-tests-{time.time():.2f}")
        # Log container info.
        image_repr = image.repo_tags[0] if image.repo_tags else image.id[:8]
        all_args_repr = (
            *(str(x) for x in args),
            *(f"{k}={v}" for k, v in kwargs.items()),
        )
        logger.info(
            "Running container image %s with args: %s",
            image_repr,
            ", ".join(all_args_repr),
        )
        # Run the container, cleaning it up at the end.
        ctr = ctr_client.run(image or systemd_image, *args, **kwargs)
        try:
            # Wait for systemd to start up inside the container.
            if wait:
                error_occurred = False
                try:
                    try_until = time.time() + 5
                    while True:
                        try:
                            ctr.execute(["systemctl", "is-system-running", "--wait"])
                        except CtrException as e:
                            if (
                                e.stdout.strip() == "offline"
                                or "Failed to connect to bus" in e.stderr
                            ) and time.time() < try_until:
                                # Systemd not yet started, may still be in a
                                # pre-systemd init script, so retry.
                                time.sleep(0.1)
                                continue
                            error_occurred = True
                            raise CtrInitError(
                                f"Systemd container failed to start: {e.stdout.strip()}"
                            ) from e
                        else:
                            break
                finally:
                    if error_occurred or log_boot_output:
                        logger.debug("Container boot logs:\n%s", ctr.logs())
            yield ctr
        finally:
            with contextlib.suppress(CtrException):
                ctr.remove(force=True)

    return ctr_ctx_mgr


@pytest.fixture(params=["host", "private"])
def cgroupns_param(request: FixtureRequest) -> str:
    """Parameterise on cgroupns (host and private)."""
    return request.param


@pytest.fixture
def default_ctr_kwargs(
    ctr_client: CtrClient,
    cgroupns_param: str,
    cgroup_mode: str,
) -> Mapping[str, Any]:
    """
    Default arguments for running a systemd container.

    Automatically parameterises on cgroupns (host and private) and cgroup v1
    mode (legacy and hybrid) if applicable.
    """
    kwargs = dict(
        cgroupns=cgroupns_param,
        legacy_cgroup_mode=(cgroup_mode == "legacy"),
    )
    if ctr_client.mgr is CtrMgr.PODMAN:
        kwargs["systemd"] = "always"
        kwargs["cap_add"] = ["sys_admin"]
    else:
        kwargs["privileged"] = True
    return kwargs
