"""
See https://systemd.io/CONTAINER_INTERFACE/ for systemd's statement on how to
run inside a container (how the container should be set up).
"""

__all__ = (
    "ALL_SETUP_MODES",
    "CUSTOM_SETUP_MODES",
    "SYSTEMD_TEST_DIR",
    "CtrCtxType",
)

import os
from pathlib import Path
from typing import Callable, ContextManager, Optional

from python_on_whales import Container

SYSTEMD_TEST_DIR: Path = Path(__file__).resolve().parent

CUSTOM_SETUP_MODES: list[str] = [
    os.path.basename(p) for p in os.listdir(SYSTEMD_TEST_DIR / "setup_modes")
]

ALL_SETUP_MODES: list[Optional[str]] = [None] + CUSTOM_SETUP_MODES

CtrCtxType = Callable[..., ContextManager[Container]]
