#!/usr/bin/env python3
"""顶层入口: python run.py <auth|read|run|raw-read> [...]"""

from tdweekly.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
