"""``python -m capkit <command> '<json>'`` - same as ``python -m capkit.api``."""
import sys

from .api import main

sys.exit(main())
