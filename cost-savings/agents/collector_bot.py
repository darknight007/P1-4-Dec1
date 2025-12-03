import json
import os
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from models.schemas import HumanRole, BenchmarkRequest
from config.settings import settings

class BenchmarkCollectorBot:
    """
    Implements Section 5 & 7B: Data Collection Bot.
    Manages the 'human_benchmarks.json' persistent store.
    Now includes AUTO-CALCULATION logic to prevent NULL values.
    """

    def __init__(self):
        self.file_path = settings.HUMAN_BENCHMARKS_FILE
        self._ensure_storage_exists()

    def _ensure_storage_exists(self):
        """Creates the empty JSON store if it doesn't exist."""
        if not self.file_path.exists():
            with open(self.file_path, "w") as f:
                json.dump({}, f)

    def _load_db(self) -> Dict[str, dict]:
        """Reads the JSON database safely."""
        try:
            with open(self.file_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _save_db(self, data: Dict[str, dict]):
        """Writes to the JSON database."""
        with open(self.file_path, "w") as f:
            json.dump(data, f, indent=2)

    def get_role_data(self, role_name: str) -> Optional[HumanRole]:
        """Retrieves a specific role's benchmark data if it exists and is valid."""
        db = self._load_db()
        role_key = role_name.lower().strip()
        
        if role_key in db:
            try:
                return HumanRole(**db[role_key])
            except Exception:
                return None
        return None

    def analyze_gap(self, role_name: str) -> Tuple[Optional[HumanRole], Optional[BenchmarkRequest]]:
        """
        Checks if the role exists and has all 4 REQUIRED fields.
        """
        role = self.get_role_data(role_name)
        
        # Scenario 1: Role completely unknown
        if not role:
            return None, BenchmarkRequest(
                missing_role=role_name,
                missing_fields=[
                    "hourly_rate_usd", 
                    "throughput_per_hour", 
                    "avg_turnaround_time_hours",
                    "average_accuracy_rate"
                ],
                context_message=f"I found a workflow replacing '{role_name}', but I have no benchmarks for them."
            )

        # Scenario 2: Role exists but might have missing specific values
        missing = []
        # Note: We prioritize Hourly Rate as the source of truth, but check both
        if role.hourly_rate_usd <= 0 and (role.annual_salary_usd is None or role.annual_salary_usd <= 0):
            missing.append("hourly_rate_usd")
            
        if role.throughput_per_hour <= 0:
            missing.append("throughput_per_hour")
        if role.avg_turnaround_time_hours <= 0:
            missing.append("avg_turnaround_time_hours")
        
        if missing:
            return None, BenchmarkRequest(
                missing_role=role_name,
                missing_fields=missing,
                context_message=f"I have some data for '{role_name}', but I need updated metrics for: {', '.join(missing)}."
            )

        return role, None

    def update_benchmark(self, role_name: str, input_data: Dict) -> HumanRole:
        """
        Updates benchmark data and Auto-Calculates missing financial fields.
        """
        db = self._load_db()
        role_key = role_name.lower().strip()
        
        current_data = db.get(role_key, {"role_name": role_name})
        
        # 1. Merge new inputs
        current_data.update(input_data)
        
        # 2. AUTO-CALCULATION (Data Enrichment)
        # Calculate standard work hours per year (e.g. 8 * 21 * 12 = 2016)
        hours_per_year = (
            settings.WORK_HOURS_PER_DAY * 
            settings.WORK_DAYS_PER_MONTH * 
            settings.WORK_MONTHS_PER_YEAR
        )

        # Case A: User gave Hourly, but missing Annual -> Calculate Annual
        if current_data.get("hourly_rate_usd") and not current_data.get("annual_salary_usd"):
            current_data["annual_salary_usd"] = round(current_data["hourly_rate_usd"] * hours_per_year, 2)
            
        # Case B: User gave Annual, but missing Hourly -> Calculate Hourly
        elif current_data.get("annual_salary_usd") and not current_data.get("hourly_rate_usd"):
            current_data["hourly_rate_usd"] = round(current_data["annual_salary_usd"] / hours_per_year, 2)
        
        # 3. Validate & Save
        validated_role = HumanRole(**current_data)
        db[role_key] = validated_role.dict()
        self._save_db(db)
        
        return validated_role