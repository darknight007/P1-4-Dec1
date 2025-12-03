import os
from pathlib import Path

class Settings:
    """
    Central configuration for the Savings Agent Suite.
    Manages file paths, global constants, and default fallback values.
    """
    
    # Project Base Directory (resolves to the root of the project)
    BASE_DIR = Path(__file__).resolve().parent.parent

    # Data Storage Directories
    DATA_DIR = BASE_DIR / "data"
    
    # Ensure data directory exists on startup
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # File Paths
    HUMAN_BENCHMARKS_FILE = DATA_DIR / "human_benchmarks.json"
    LOGS_DIR = BASE_DIR / "logs"

    # Calculation Constants
    # Used for converting annual/monthly values if only hourly is provided (Data Enrichment)
    WORK_HOURS_PER_DAY = 8
    WORK_DAYS_PER_MONTH = 21
    WORK_MONTHS_PER_YEAR = 12
    
    # Default Assumptions (used for Pricing Power Score heuristics)
    WEIGHT_VALUE_CREDITS = 0.4
    WEIGHT_ANNUAL_SAVINGS = 0.4
    WEIGHT_STICKINESS = 0.2
    
    # Validation Thresholds
    MIN_ACCURACY_THRESHOLD = 0.0  # 0%
    MAX_ACCURACY_THRESHOLD = 1.0  # 100%

    @classmethod
    def get_benchmark_path(cls) -> Path:
        """Returns the absolute path to the persistent benchmark storage."""
        return cls.HUMAN_BENCHMARKS_FILE

# Initialize settings instance
settings = Settings()