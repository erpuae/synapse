__version__ = "1.0.0"

# Public API for other apps that add custom tools. See synapse/extend.py.
from synapse.extend import tool

__all__ = ["tool"]
