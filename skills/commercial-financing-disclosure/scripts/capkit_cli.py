#!/usr/bin/env python3
"""Entry point for this CapKit skill. See SKILL.md.

    python scripts/capkit_cli.py list
    python scripts/capkit_cli.py describe <command>
    python scripts/capkit_cli.py <command> '<json args>'      (or '-' to read JSON from stdin)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from capkit.api import main  # noqa: E402  (vendored engine)

if __name__ == "__main__":
    sys.exit(main())
