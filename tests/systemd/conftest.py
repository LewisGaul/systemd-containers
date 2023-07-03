import contextlib
import logging
import textwrap
import time
from typing import ContextManager, Generator

import pytest
from python_on_whales import Container
from python_on_whales import DockerException as CtrException
from python_on_whales import Image as CtrImage

from .. import utils
from ..utils import CtrClient, CtrInitError


logger = logging.getLogger(__name__)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "cgroup_mode" in metafunc.fixturenames:
        if metafunc.config.option.cgroup_version == 1:
            metafunc.parametrize("cgroup_mode", ["legacy", "hybrid"])
        else:
            assert metafunc.config.option.cgroup_version == 2
            metafunc.parametrize("cgroup_mode", ["unified"])


@pytest.fixture(scope="package")
def systemd_image(ctr_client: CtrClient) -> CtrImage:
    dockerfile = textwrap.dedent(
        f"""\
        FROM ubuntu:20.04
        RUN apt-get update -y \\
            && apt-get install -y systemd \\
            && ln -s /lib/systemd/systemd /sbin/init \\
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
    # logger.info(
    #     "Cleaning up image %s (tags: %s)", image.id[:8], ", ".join(image.repo_tags)
    # )
    # image.remove(force=True, prune=True)


@pytest.fixture
def ctr_ctx(
    request: pytest.FixtureRequest, ctr_client: CtrClient, systemd_image: CtrImage
) -> ContextManager[Container]:
    """Context manager for starting a systemd container."""

    @contextlib.contextmanager
    def ctr_ctx_mgr(*args, **kwargs) -> Generator[Container, None, None]:
        kwargs.setdefault("tty", True)
        if not kwargs.setdefault("detach", True):
            raise TypeError("Running container attached is not supported")
        kwargs.setdefault("name", f"pow-tests-{time.time():.2f}")
        all_args_repr = (
            *(str(x) for x in args),
            *(f"{k}={v}" for k, v in kwargs.items()),
        )
        logger.info(
            "Running container with args: %s",
            ", ".join(all_args_repr),
        )
        ctr = ctr_client.run(systemd_image, *args, **kwargs)
        try:
            ctr.execute(["systemctl", "is-system-running", "--wait"])
        except CtrException as e:
            raise CtrInitError("Systemd container failed to start") from e
        finally:
            logger.debug("Container boot logs:\n%s", ctr.logs())
        with ctr:
            yield ctr

    return ctr_ctx_mgr
