#!/usr/bin/env python3
"""QotDash entry point."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from QotDash.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
