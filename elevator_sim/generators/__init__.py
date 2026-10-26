"""Request generators: synthetic traffic for the simulator. Add new patterns as modules here."""

from .normal import generate_normal
from .random import generate_random
from .writer import write_requests

__all__ = ["generate_normal", "generate_random", "write_requests"]
