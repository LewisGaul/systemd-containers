"""
See https://systemd.io/CONTAINER_INTERFACE/ for systemd's statement on how to
run inside a container (how the container should be set up).
"""

__all__ = ("SYSTEMD_TEST_DIR", "CtrCtxType")

from pathlib import Path
from typing import Callable, ContextManager

from python_on_whales import Container

SYSTEMD_TEST_DIR: Path = Path(__file__).resolve().parent

CtrCtxType = Callable[..., ContextManager[Container]]
