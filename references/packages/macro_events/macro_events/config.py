"""Configuration constants for macro event collection and classification."""

REPORT_TYPES = ["macro", "nfp", "cpi"]  # legacy nfp/cpi kept for compatibility

MACRO_SHOCK_TYPES = [
    "trade_tariff",
    "sanctions",
    "supply_chain",
    "labor_dispute",
    "financial_stability",
    "other",
]

IMPACT_CHANNELS = [
    "inflation",
    "employment",
    "growth",
    "financial_conditions",
]

# Unified search keyword templates across macro themes.
UNIFIED_QUERIES = [
    # Labor / employment shocks
    '("labor strike" OR "union walkout" OR "labor dispute" OR "UAW strike") AND ("United States" OR US)',
    '("mass layoffs" OR "job cuts" OR "hiring freeze") AND ("United States" OR US)',
    # Trade / sanctions / tariffs / industrial policy
    '("tariffs" OR "trade war" OR "import duties" OR "export controls" OR "sanctions" OR "entity list") AND ("United States" OR US)',
    '("industrial policy" OR "subsidy" OR "Made in America") AND ("tariff" OR "trade")',
    # Supply chain / logistics
    '("supply chain" OR "shipping disruption" OR "port congestion" OR "Red Sea" OR "Suez Canal" OR "Panama Canal") AND ("United States" OR US)',
    # Energy / prices
    '("energy prices" OR "oil prices" OR "gasoline prices" OR "natural gas prices") AND ("United States" OR US)',
    # Financial stability
    '("bank failure" OR "bank collapse" OR "liquidity crisis" OR "credit crunch" OR "bank run") AND ("United States" OR US)',
    # Geopolitical conflict / escalation with economic spillovers
    '("geopolitical tension" OR "military conflict" OR "escalation" OR "war") AND ("shipping" OR "energy" OR "trade") AND ("United States" OR US OR NATO)',
    '("sanctions" OR "export ban" OR "technology restrictions") AND ("China" OR "Russia" OR "Iran") AND ("United States" OR US)',
    # Global public health events
    '("pandemic" OR "public health emergency" OR "covid" OR "covid-19" OR "virus outbreak") AND ("World Health Organization" OR WHO OR CDC OR global)',
    # Global macro shocks catch-all
    '("global recession risk" OR "stagflation" OR "commodity shock" OR "energy shock") AND ("United States" OR US)',
]

# Legacy aliases kept for imports; both point to unified list.
NFP_QUERIES = UNIFIED_QUERIES
CPI_QUERIES = UNIFIED_QUERIES

# Version tags so callers can record which heuristic/prompt set was used.
QUERY_VERSION = "v1"
LLM_VERSION = "placeholder"
