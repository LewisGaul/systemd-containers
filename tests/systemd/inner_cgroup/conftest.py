import logging
import textwrap
from pathlib import Path

import pytest
from python_on_whales import Image as CtrImage

from ... import utils
from ...utils import CtrClient


logger = logging.getLogger(__name__)


@pytest.fixture(scope="package")
def inner_cgroup_image(ctr_client: CtrClient, systemd_image: CtrImage) -> CtrImage:
    """Image running an init script before starting systemd."""
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
        build_root=Path(__file__).parent,
        tags="ubuntu-systemd-inner-cgroup:20.04",
    )
    yield image


@pytest.fixture(scope="package")
def pkg_image(inner_cgroup_image: CtrClient) -> CtrImage:
    """The default image for the package."""
    return inner_cgroup_image
