from __future__ import annotations

import contextlib
import logging
import os
import textwrap
import time
from pathlib import Path
from typing import Any, Generator, Mapping, Optional

import pytest
from pytest import Config, FixtureRequest, Item, Metafunc
from python_on_whales import Container
from python_on_whales import DockerException as CtrException
from python_on_whales import Image as CtrImage

from .. import utils
from ..utils import CtrClient, CtrInitError, CtrMgr, Mount
from . import SYSTEMD_TEST_DIR, CtrCtxType

logger = logging.getLogger(__name__)

_PARAMETERISATIONS = ["setup_mode", "cgroupns", "cgroup_mode"]


# -----------------------------------------------------------------------------
# Hooks
# -----------------------------------------------------------------------------


def pytest_configure(config: Config) -> None:
    for param in _PARAMETERISATIONS:
        config.addinivalue_line(
            "markers",
            f"{param}([...]): Values for the given parameter to use in the test",
        )
    config.addinivalue_line(
        "markers",
        f'ctr_mgr(MGR, reason="..."): Container manager required by the test',
    )


def pytest_generate_tests(metafunc: Metafunc) -> None:
    setup_mode_dirs = [
        os.path.basename(p) for p in os.listdir(SYSTEMD_TEST_DIR / "setup_modes")
    ]
    metafunc.parametrize(
        "setup_mode",
        [None] + setup_mode_dirs,
        ids=["default"] + setup_mode_dirs,
        scope="package",
        indirect=True,
    )


def pytest_collection_modifyitems(config: Config, items: list[Item]) -> None:
    cgroup_version: int = config.option.cgroup_version

    # Find paramaterisations that don't make sense and remove them from
    # the list of tests to be run.
    remove = []
    for item in items:
        if not isinstance(item, pytest.Function):
            # Not sure when this would be the case?
            continue
        test_params: Mapping[str, Any] = item.callspec.params
        valid_conditions = {}
        if cgroup_version == 1:
            valid_conditions["cgroupv1 non-unified"] = (
                test_params["cgroup_mode"] != "unified"
            )
        else:
            valid_conditions["cgroupv2 unified"] = (
                test_params["cgroup_mode"] == "unified"
            )
        for param in ["setup_mode", "cgroupns", "cgroup_mode"]:
            marker = item.get_closest_marker(param)
            if marker:
                valid_conditions[param] = test_params[param] in marker.args[0]
        if not all(valid_conditions.values()):
            remove.append(item)

    logger.debug("Removing %u test parameterisations that don't apply", len(remove))
    items[:] = [x for x in items if x not in remove]

    # Mark tests that cannot be executed to be skipped.
    for items in items:
        if ctr_mgr_marker := item.get_closest_marker("ctr_mgr"):
            required_ctr_mgr = ctr_mgr_marker.args[0]
            skip_reason = ctr_mgr_marker.kwargs.get("reason")
            if config.option.ctr_client.mgr is not required_ctr_mgr:
                item.add_marker(pytest.mark.skip(skip_reason))


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


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
def setup_mode(request: FixtureRequest) -> None:
    """
    The container setup mode, parameterising all tests at a package level.
    """
    if request.param is not None:
        # Check the directory for the setup mode exists.
        setup_mode_dir = SYSTEMD_TEST_DIR / "setup_modes" / request.param
        assert setup_mode_dir.is_dir()
        assert (setup_mode_dir / "init_script.sh").is_file()
    return request.param


@pytest.fixture(scope="package")
def pkg_image(
    ctr_client: CtrClient,
    systemd_image: CtrClient,
    setup_mode: Optional[str],
) -> CtrImage:
    """The image to use for the parameterised setup mode."""
    if setup_mode is None:
        return systemd_image

    dockerfile = textwrap.dedent(
        f"""\
        FROM {systemd_image.repo_tags[0]}
        COPY init_script.sh /init_script.sh
        ENTRYPOINT ["/init_script.sh"]
        """
    )
    image = utils.build_with_dockerfile(
        ctr_client,
        dockerfile,
        build_root=SYSTEMD_TEST_DIR / "setup_modes" / setup_mode,
        tags=f"ubuntu-systemd-{setup_mode}:20.04",
    )
    return image


@pytest.fixture(scope="package", autouse=True)
def host_check_systemd(
    cgroup_version: int,
    ctr_client: CtrClient,
    setup_mode: Optional[str],
) -> None:
    """
    Check properties of the container host for running systemd containers.
    """
    # Check /sys/fs/cgroup/systemd exists if host is on cgroups v1.
    if cgroup_version == 1:
        mounts = [
            Mount(*L.split()[:4]) for L in Path("/proc/mounts").read_text().splitlines()
        ]
        if ("/sys/fs/cgroup/systemd", "cgroup") not in [
            (m.path, m.type) for m in mounts
        ] and setup_mode is None:
            pytest.fail(
                "Default systemd containers cannot run on a cgroup v1 host that "
                "doesn't have /sys/fs/cgroup/systemd mounted"
            )


@pytest.fixture(params=["host", "private"])
def cgroupns(request: FixtureRequest) -> str:
    """Parameterise on cgroupns (host and private)."""
    return request.param


@pytest.fixture(params=["legacy", "hybrid", "unified"])
def cgroup_mode(request: FixtureRequest) -> str:
    """Parameterise on systemd cgroup mode."""
    return request.param


@pytest.fixture
def default_ctr_kwargs(ctr_mgr: CtrMgr, setup_mode: Optional[str]) -> dict[str, Any]:
    """
    Default, minimal arguments required for a systemd container to run.

    This accommodates both Docker and Podman, and takes into account the setup
    mode being used, hence documenting the different requirements imposed by
    these modes.
    """
    kwargs = {}
    if ctr_mgr is CtrMgr.PODMAN:
        # Enable Podman's systemd mode as a sensible default.
        # This only needs to be "always" rather than True (the Podman default)
        # for the case we're using a custom entrypoint, and True could be used
        # if we were to package that entrypoint to a path that Podman recognises
        # as a systemd entrypoint, such as /usr/sbin/init. But we might as well
        # just use "always" here to be explicit about the intent.
        kwargs["systemd"] = "always"
    else:
        # Docker does not set the 'container' env var, which systemd
        # uses to determine it should run in container mode.
        kwargs.setdefault("envs", {}).setdefault("container", "docker")

    # Privileged mode is required when running with Docker, unless certain
    # custom setup is performed. Otherwise, CAP_SYS_ADMIN is sufficient.
    if ctr_mgr is CtrMgr.DOCKER and setup_mode not in ["remount", "unmount"]:
        kwargs["privileged"] = True
    else:
        kwargs["cap_add"] = ["sys_admin"]

    return kwargs


@pytest.fixture
def ctr_ctx(
    request: pytest.FixtureRequest,
    ctr_client: CtrClient,
    pkg_image: CtrImage,
    cgroupns: str,
    cgroup_mode: str,
) -> CtrCtxType:
    """
    Fixture providing a context manager for starting a systemd container.

    This is expected to be used by all tests, and automatically parameterises
    on the following:
     - setup_mode
     - cgroupns
     - cgroup_mode
    """

    @contextlib.contextmanager
    def ctr_ctx_mgr(
        image: Optional[CtrImage] = None,
        *args,
        systemd: Optional[bool] = None,
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
            # Disable podman's systemd mode by default for consistency when
            # comparing with docker.
            systemd = False
        elif systemd is False and ctr_client.mgr is CtrMgr.DOCKER:
            # Docker doesn't have systemd mode, so no need to pass the arg for
            # it to be 'False'.
            systemd = None
        elif systemd is not None:
            if ctr_client.mgr is CtrMgr.DOCKER:
                pytest.skip("Systemd mode not supported by Docker")
            kwargs["systemd"] = systemd
        if cgroup_mode == "legacy":
            # Force systemd to run in legacy cgroup v1 mode.
            assert request.config.option.cgroup_version == 1
            kwargs.setdefault("envs", {})[
                "SYSTEMD_PROC_CMDLINE"
            ] = "systemd.legacy_systemd_cgroup_controller=1"
        kwargs.setdefault("tty", True)
        kwargs.setdefault("interactive", True)  # not needed, helps debugging
        if not kwargs.setdefault("detach", True):
            raise TypeError("Running container attached is not supported")
        if kwargs.setdefault("remove", False):
            raise TypeError(
                "Removing container on exit breaks logging so is not supported"
            )
        if kwargs.setdefault("cgroupns", cgroupns) != cgroupns:
            raise TypeError(
                "Cgroup namespace mode is parameterised, skip unwanted tests "
                "rather than overriding"
            )
        kwargs.setdefault("name", f"systemd-tests-{time.time():.2f}")
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
                    if error_occurred:
                        logger.error("Container boot logs:\n%s", ctr.logs())
                    elif log_boot_output:
                        logger.debug("Container boot logs:\n%s", ctr.logs())
            yield ctr
        finally:
            with contextlib.suppress(CtrException):
                ctr.remove(force=True)

    return ctr_ctx_mgr
