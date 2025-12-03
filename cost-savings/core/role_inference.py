from typing import Dict, List, Tuple

class RoleInferenceEngine:
    """
    Deduces the Human Role from context keywords using a Weighted Taxonomy System.
    Replaces simple dictionary lookups with a scoring algorithm.
    """

    # Taxonomy: Role -> List of weighted keywords
    # Key is the Role Name. Value is list of related terms.
    _TAXONOMY = {
        "SDR": ["lead", "email", "outreach", "prospect", "sales", "contact", "enrich", "phone"],
        "Data Analyst": ["report", "chart", "trend", "dashboard", "insight", "csv", "excel", "forecast"],
        "Content Writer": ["blog", "article", "post", "social", "copy", "draft", "edit", "text"],
        "Customer Support": ["ticket", "resolution", "chat", "message", "refund", "complaint", "help"],
        "Legal Analyst": ["contract", "clause", "risk", "compliance", "audit", "policy", "agreement", "gdpr"],
        "Backend Developer": ["api", "db", "migration", "script", "cron", "json", "endpoint", "query"],
        "Document Specialist": ["ocr", "scan", "pdf", "invoice", "receipt", "digitize", "archive"]
    }

    @classmethod
    def infer_role(cls, context_tags: List[str]) -> str:
        """
        Scans context tags against the taxonomy and returns the highest scoring role.
        """
        scores: Dict[str, int] = {role: 0 for role in cls._TAXONOMY}
        
        # Flatten and clean tags
        # e.g. "django_migrations" -> ["django", "migrations"]
        clean_tokens = []
        for tag in context_tags:
            clean_tokens.extend(tag.lower().replace("_", " ").split())

        # Scoring Loop
        for role, keywords in cls._TAXONOMY.items():
            for token in clean_tokens:
                # Direct match
                if token in keywords:
                    scores[role] += 2
                # Partial match (e.g. "reporting" matches "report")
                else:
                    for kw in keywords:
                        if kw in token:
                            scores[role] += 1

        # Find Winner
        # Sort by score desc
        sorted_roles = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        
        best_role, best_score = sorted_roles[0]

        if best_score > 0:
            return best_role
        
        return "General Operations" # Fallback