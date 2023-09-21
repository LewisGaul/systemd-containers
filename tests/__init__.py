__all__ = (
    "ALL_SETUP_MODES",
    "CUSTOM_SETUP_MODES",
    "SYSTEMD_TEST_DIR",
    "CtrCtxType",
    "utils",
)

import os
from pathlib import Path
from typing import Callable, ContextManager, Optional

from python_on_whales import Container

from . import utils


SYSTEMD_TEST_DIR: Path = Path(__file__).resolve().parent

CUSTOM_SETUP_MODES: list[str] = [
    os.path.basename(p) for p in os.listdir(SYSTEMD_TEST_DIR / "setup_modes")
]

ALL_SETUP_MODES: list[Optional[str]] = [None] + CUSTOM_SETUP_MODES

CtrCtxType = Callable[..., ContextManager[Container]]
