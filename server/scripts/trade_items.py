"""
trade_items.py — item name normalization for the action parser.

Call load_item_aliases(path) once at startup.
Then use normalize_trade_item_name(text) before building GIVE_ITEM / SPAWN_ITEM tags.
"""
import json
import logging
import re

_ALIASES: dict = {}
_ARTICLES = re.compile(r'^(a|an|the)\s+', re.IGNORECASE)


def load_item_aliases(path: str) -> None:
    global _ALIASES
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        _ALIASES = {k.strip().lower(): v for k, v in raw.items() if not k.startswith("_")}
        logging.debug(f"Loaded {len(_ALIASES)} item aliases from {path}")
    except Exception as e:
        logging.warning(f"Could not load item_aliases.json ({e}) — item normalization disabled")


def _clean(name: str) -> str:
    """Normalize a raw item string for alias lookup."""
    s = name.strip().lower()
    s = re.sub(r'\s+', ' ', s)           # collapse whitespace
    s = s.strip('.,;:!?\'"()[]{}')       # strip surrounding punctuation
    s = _ARTICLES.sub('', s)             # strip leading articles
    return s


def normalize_trade_item_name(name: str) -> str:
    """Return the canonical Kenshi template string ID for name, or the original unchanged."""
    key = _clean(name)
    canonical = _ALIASES.get(key)
    if canonical and canonical != name:
        logging.info(f"TRADE: normalized item alias '{name}' -> '{canonical}'")
        return canonical
    return name
