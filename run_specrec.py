"""Launcher used by PyInstaller (and for running without `-m`)."""
import sys

from specrec.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
