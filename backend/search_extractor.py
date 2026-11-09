"""
MemoryOS Search Query Extractor.
Extracts search queries from URLs across major search engines, developer docs,
marketplaces, video sites, and generic query parameter fallbacks.
"""

from typing import Dict, Optional, Tuple
from urllib.parse import parse_qs, unquote_plus, urlparse

from backend.scrubber import extract_domain, scrub_text


# Known search engines with their specific query parameters and path rules
SEARCH_ENGINE_RULES = [
    # Google (Search, Images, Maps)
    {
        "name": "Google",
        "domain_keyword": "google.",
        "params": ["q", "as_q"],
        "paths": ["/search", "/webhp", "/url"],
    },
    # Bing
    {
        "name": "Bing",
        "domain_keyword": "bing.com",
        "params": ["q"],
        "paths": ["/search"],
    },
    # DuckDuckGo
    {
        "name": "DuckDuckGo",
        "domain_keyword": "duckduckgo.com",
        "params": ["q"],
        "paths": ["/"],
    },
    # YouTube
    {
        "name": "YouTube",
        "domain_keyword": "youtube.com",
        "params": ["search_query", "q"],
        "paths": ["/results"],
    },
    # Wikipedia
    {
        "name": "Wikipedia",
        "domain_keyword": "wikipedia.org",
        "params": ["search"],
        "paths": ["/wiki/Special:Search", "/w/index.php"],
    },
    # GitHub
    {
        "name": "GitHub",
        "domain_keyword": "github.com",
        "params": ["q"],
        "paths": ["/search"],
    },
    # Amazon
    {
        "name": "Amazon",
        "domain_keyword": "amazon.",
        "params": ["k", "field-keywords"],
        "paths": ["/s", "/gp/search"],
    },
    # Reddit
    {
        "name": "Reddit",
        "domain_keyword": "reddit.com",
        "params": ["q"],
        "paths": ["/search", "/r/"],
    },
    # StackOverflow
    {
        "name": "StackOverflow",
        "domain_keyword": "stackoverflow.com",
        "params": ["q"],
        "paths": ["/search"],
    },
]

# Generic fallback query parameters ordered by commonality
GENERIC_QUERY_PARAMS = ["q", "query", "search", "search_query", "s", "k", "keyword", "keywords"]


def extract_search_query(url: Optional[str]) -> Optional[Tuple[str, str]]:
    """
    Extract search query and engine name from a given URL.
    Returns (cleaned_query, engine_name) or None if no query found.
    """
    if not url:
        return None

    try:
        parsed = urlparse(url)
        domain = (parsed.netloc or "").lower().split(":")[0]
        if not domain:
            return None

        # Parse query params
        params = parse_qs(parsed.query, keep_blank_values=False)
        if not params:
            return None

        # 1. Check known search engines first
        for rule in SEARCH_ENGINE_RULES:
            if rule["domain_keyword"] in domain:
                # Check path match if paths are specified
                path_match = True
                if rule.get("paths"):
                    path_match = any(parsed.path.startswith(p) for p in rule["paths"])

                if path_match or rule["domain_keyword"] in ["duckduckgo.com", "bing.com"]:
                    for param_key in rule["params"]:
                        if param_key in params and params[param_key]:
                            raw_val = params[param_key][0]
                            val = unquote_plus(raw_val).strip()
                            clean = scrub_text(val)
                            if clean and len(clean) >= 2:
                                return clean, rule["name"]

        # 2. Generic fallback for any domain using common query params
        for generic_key in GENERIC_QUERY_PARAMS:
            if generic_key in params and params[generic_key]:
                raw_val = params[generic_key][0]
                val = unquote_plus(raw_val).strip()
                clean = scrub_text(val)
                if clean and len(clean) >= 2:
                    # Format engine name from domain e.g. "docs.trychroma.com" -> "Trychroma"
                    engine_name = domain.replace("www.", "").split(".")[0].capitalize()
                    return clean, engine_name

    except Exception:
        return None

    return None


def extract_youtube_video_id(url: Optional[str]) -> Optional[str]:
    """
    Extract YouTube 11-character video ID from watch, embed, or short URLs.
    Supports youtube.com/watch?v=ID, youtu.be/ID, and youtube.com/embed/ID.
    """
    if not url:
        return None
    try:
        parsed = urlparse(url)
        domain = (parsed.netloc or "").lower().split(":")[0]
        if "youtube.com" in domain:
            params = parse_qs(parsed.query)
            if "v" in params and params["v"]:
                return params["v"][0]
            if parsed.path.startswith("/embed/") or parsed.path.startswith("/v/") or parsed.path.startswith("/shorts/"):
                parts = [p for p in parsed.path.split("/") if p]
                if len(parts) >= 2:
                    return parts[1]
        elif "youtu.be" in domain:
            parts = [p for p in parsed.path.split("/") if p]
            if parts:
                return parts[0]
    except Exception:
        pass
    return None


