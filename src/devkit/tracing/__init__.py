"""Tracing context, severity levels, and Logfire-backed spans."""

from pathlib import Path
from typing import Final

import logfire

from devkit.tracing.context import Context
from devkit.tracing.level import Level
from devkit.tracing.tracer import Tracer

__all__: Final[tuple[str, ...]] = ("Context", "Level", "Tracer")

logfire.add_non_user_code_prefix(str(Path(__file__).parent))
