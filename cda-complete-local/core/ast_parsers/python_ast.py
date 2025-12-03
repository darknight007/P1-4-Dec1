from typing import List, Dict, Any

class PythonASTParser:
    def parse_file(self, file_path: str, content: str) -> Dict[str, Any]:
        return {"llm_calls": [], "functions": [], "confidence": "low"}
    
    def get_file_extensions(self) -> List[str]:
        return [".py"]
