from typing import List, Dict, Any

class PatternDetector:
    """
    TEMPORARY STUB - Detects LLM/API patterns in code.
    Full implementation: regex patterns + heuristics.
    """
    
    def __init__(self):
        self.patterns = []
    
    def detect_patterns(self, content: str) -> List[Dict[str, Any]]:
        return []
    
    def analyze_file(self, file_path: str, content: str) -> Dict[str, Any]:
        return {"patterns": [], "confidence": "low"}
