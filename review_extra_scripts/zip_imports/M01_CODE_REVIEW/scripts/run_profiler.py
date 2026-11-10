from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.datamate.m01_data_processing.generic_profiler import main

if __name__ == "__main__":
    main()
