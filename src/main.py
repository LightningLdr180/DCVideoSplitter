"""DC Video Splitter entry point."""

import sys
from pathlib import Path

# Allow running as script from src/
sys.path.insert(0, str(Path(__file__).resolve().parent))

if sys.platform != "win32":
    print("DC Video Splitter requires Windows.", file=sys.stderr)
    sys.exit(1)

from app.ui import run_app

if __name__ == "__main__":
    run_app()
