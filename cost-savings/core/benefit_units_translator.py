from typing import List, Dict
from models.schemas import ValueCredit, CreditType, BenefitUnitResult

class BenefitUnitsTranslator:
    """
    Translates abstract 'Value Credits' into tangible 'Benefit Units'.
    
    CRITICAL FIX: Includes expanded vocabulary to ensure upstream tags 
    (like 'invoices' or 'contracts') map to standard countable units.
    """

    # Mapping configuration: (CreditType, Context_Tag) -> Standardized Benefit Key
    _MAPPING_REGISTRY = {
        # --- Throughput (Volume) ---
        (CreditType.THROUGHPUT, "files"): "files_analyzed",
        (CreditType.THROUGHPUT, "leads"): "leads_enriched",
        (CreditType.THROUGHPUT, "rows"): "data_entries_processed",
        
        # Specific Business Objects (Fixes for "0 Savings" bugs)
        (CreditType.THROUGHPUT, "invoices"): "invoices_processed",
        (CreditType.THROUGHPUT, "appointments"): "appointments_scheduled",
        (CreditType.THROUGHPUT, "support_tickets"): "tickets_resolved",
        
        # --- Engagement ---
        (CreditType.ENGAGEMENT, "emails"): "emails_sent",
        (CreditType.ENGAGEMENT, "messages"): "conversations_handled",
        
        # --- Knowledge & Research ---
        (CreditType.KNOWLEDGE_DISCOVERY, "chunks"): "knowledge_chunks_retrieved",
        (CreditType.KNOWLEDGE_DISCOVERY, "reports"): "reports_generated",
        
        # --- Coverage ---
        (CreditType.COVERAGE, "sources"): "data_sources_monitored",
        (CreditType.COVERAGE, "signals"): "market_signals_detected",
        
        # --- Depth ---
        (CreditType.DEPTH, "insights"): "strategic_insights_generated",
        
        # --- Personalization ---
        (CreditType.PERSONALIZATION, "profiles"): "profiles_customized",
        
        # --- Risk / Compliance ---
        (CreditType.RISK_REDUCTION, "points"): "compliance_checks_executed",
        # FIX: Map legal items to 'files' so they match 'Analyst' benchmarks easily
        (CreditType.RISK_REDUCTION, "legal_contracts"): "files_analyzed",
        (CreditType.RISK_REDUCTION, "contracts"): "files_analyzed",
        (CreditType.RISK_REDUCTION, "patient_records"): "records_analyzed",
    }

    @classmethod
    def translate(cls, feature_id: str, credits: List[ValueCredit]) -> BenefitUnitResult:
        """
        Aggregates multiple credits for a single feature into consolidated benefit units.
        """
        consolidated_units: Dict[str, float] = {}

        for credit in credits:
            # Skip Accuracy credits here (handled in Quality Engine)
            if credit.credit_type == CreditType.ACCURACY:
                continue

            # 1. Determine the Standard Key
            key = cls._resolve_key(credit)
            
            # 2. Aggregate Values (Summation)
            if key in consolidated_units:
                consolidated_units[key] += credit.raw_value
            else:
                consolidated_units[key] = credit.raw_value

        return BenefitUnitResult(
            feature_id=feature_id,
            benefit_units=consolidated_units
        )

    @classmethod
    def _resolve_key(cls, credit: ValueCredit) -> str:
        """
        Helper to find the standardized key. 
        Falls back to generating a key from the context if no specific mapping exists.
        """
        # Try exact match in registry
        mapping_key = (credit.credit_type, credit.context_tag.lower())
        if mapping_key in cls._MAPPING_REGISTRY:
            return cls._MAPPING_REGISTRY[mapping_key]
        
        # Fallback Strategy: Create a readable key from context
        # e.g., Context "images" -> "images_processed"
        clean_context = credit.context_tag.lower().replace(" ", "_")
        return f"{clean_context}_processed"