"""DC Video Splitter entry point."""

import sys
from pathlib import Path

# Allow running as script from src/
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.ui import run_app

if __name__ == "__main__":
    run_app()
