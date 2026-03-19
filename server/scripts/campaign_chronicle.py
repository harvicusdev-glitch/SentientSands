"""campaign_chronicle.py — Campaign chronicle storage and prompt injection.

Manages persistent major-event history for a campaign:
  - load_chronicle / save_chronicle: JSON read/write with archive overflow
  - append_major_event: atomic load → append → save (call this from routes)
  - build_chronicle_block: formats the [CAMPAIGN CHRONICLE] prompt section

No Flask or server imports — pure stdlib only.
Future Dack migration: swap load_chronicle / save_chronicle only.
"""

import json
import logging
import os

# ---------------------------------------------------------------------------
# Private constants (only used within this module)
# ---------------------------------------------------------------------------

_CHRONICLE_MAX_ACTIVE = 15

# Maps region name → set of faction names geographically present there.
_KENSHI_REGION_FACTIONS = {
    "Holy Lands":      {"Holy Nation", "Holy Nation Outlaws", "Flotsam Ninjas",
                        "Hiningenteki Hantas", "Highlanders"},
    "Great Desert":    {"United Cities", "Traders Guild", "Slave Traders",
                        "Anti-Slavers", "Tech Hunters", "Western Hive"},
    "South Wetlands":  {"United Cities", "Traders Guild", "Slave Traders", "Anti-Slavers"},
    "Stenn Desert":    {"Shek Kingdom", "Kral's Chosen", "Band of Bones", "Berserkers", "Reavers"},
    "Hook":            {"Shek Kingdom", "Reavers", "Band of Bones"},
    "Black Desert":    {"Mechanical Hive", "Second Empire Exile", "Tech Hunters", "Skeletons"},
    "Iron Valleys":    {"Mechanical Hive", "Tech Hunters"},
    "Grey Desert":     {"Mechanical Hive", "Skeletons", "Tech Hunters"},
    "The Swamp":       {"Blue Cleavers", "Green Katanas", "Swamp Ruffians", "Cold Bloods"},
    "Shun":            {"Desolate Plunderers", "Hook Raiders", "Tech Hunters"},
    "Border Zone":     {"United Cities", "Shek Kingdom", "Traders Guild",
                        "Tech Hunters", "Shinobi Thieves", "Nomads"},
    "The Hub":         {"Tech Hunters", "Shinobi Thieves", "Nomads"},
    # Isolated — only learn events if explicitly in factions_full
    "Cannibal Plains": set(),
    "Fog Islands":     set(),
    "The Gut":         set(),
    "Ashlands":        set(),
}

_KENSHI_REGION_NEIGHBORS = {
    "Holy Lands":      ["Great Desert", "Stenn Desert", "Border Zone"],
    "Great Desert":    ["Holy Lands", "South Wetlands", "Stenn Desert", "Border Zone", "The Hub"],
    "South Wetlands":  ["Great Desert", "The Swamp"],
    "Stenn Desert":    ["Great Desert", "Holy Lands", "Hook", "Black Desert", "Border Zone"],
    "Hook":            ["Stenn Desert", "Black Desert"],
    "Black Desert":    ["Stenn Desert", "Hook", "Iron Valleys", "Grey Desert"],
    "Iron Valleys":    ["Black Desert", "Border Zone"],
    "Grey Desert":     ["Black Desert", "Ashlands"],
    "The Swamp":       ["South Wetlands"],
    "Shun":            ["Stenn Desert", "Hook"],
    "Border Zone":     ["Holy Lands", "Great Desert", "Stenn Desert", "Iron Valleys", "The Hub"],
    "The Hub":         ["Great Desert", "Border Zone"],
    "Cannibal Plains": [], "Fog Islands": [], "The Gut": [], "Ashlands": ["Grey Desert"],
}

# These factions never receive vague awareness unless explicitly in factions_full
_ISOLATED_FACTIONS = frozenset({
    "Fogmen", "Cannibals", "Fishmen", "Skin Bandits",
    "Beak Things", "Spider Clan", "Reawakened", "Third Empire",
})

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def load_chronicle(cdir):
    """Load active events from campaign_chronicle.json. Returns [] on any error."""
    path = os.path.join(cdir, "campaign_chronicle.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        logging.error(f"CHRONICLE: Failed to load chronicle: {e}")
        return []


def save_chronicle(cdir, events):
    """Persist events to campaign_chronicle.json. Archives overflow to chronicle_archive.json.
    Returns the (possibly trimmed) active list."""
    if len(events) > _CHRONICLE_MAX_ACTIVE:
        overflow = events[:len(events) - _CHRONICLE_MAX_ACTIVE]
        events = events[len(events) - _CHRONICLE_MAX_ACTIVE:]
        archive_path = os.path.join(cdir, "chronicle_archive.json")
        try:
            existing = []
            if os.path.exists(archive_path):
                with open(archive_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            existing.extend(overflow)
            with open(archive_path, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)
            logging.info(f"CHRONICLE: Archived {len(overflow)} overflow events.")
        except Exception as e:
            logging.error(f"CHRONICLE: Failed to write archive: {e}")
    path = os.path.join(cdir, "campaign_chronicle.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(events, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error(f"CHRONICLE: Failed to save chronicle: {e}")
    return events


def append_major_event(cdir, event_dict):
    """Load active chronicle, append event_dict, save. Returns updated active list."""
    events = load_chronicle(cdir)
    events.append(event_dict)
    return save_chronicle(cdir, events)

# ---------------------------------------------------------------------------
# Prompt injection
# ---------------------------------------------------------------------------

def build_chronicle_block(npc_data, cdir):
    """Build the [CAMPAIGN CHRONICLE] block for this NPC.
    Returns a formatted string, or '' if no relevant events exist."""
    npc_faction = (npc_data or {}).get("Faction", "").strip()
    full_lines, vague_lines = [], []

    for event in load_chronicle(cdir):
        summary         = event.get("summary", "").strip()
        factions_full   = event.get("factions_full", [])
        radius          = event.get("radius", "local")
        location_region = event.get("location_region", "")
        location        = event.get("location", "the wasteland")
        day             = event.get("day", "")

        summary_vague = event.get("summary_vague") or (
            f"Word has it that something significant occurred in {location}"
            + (f" involving {factions_full[0]}." if factions_full else ".")
        )
        day_prefix = f"Day {day}: " if day else ""

        # Tier A: explicitly listed faction gets full detail
        if npc_faction and npc_faction in factions_full:
            full_lines.append(f"- {day_prefix}{summary}")
            continue

        # Isolated factions never receive vague awareness
        if npc_faction in _ISOLATED_FACTIONS:
            continue

        # Tier B: radius-based vague awareness
        if radius == "global":
            vague_lines.append(f"- {day_prefix}{summary_vague}")
        elif radius == "regional":
            candidates = {location_region} | set(_KENSHI_REGION_NEIGHBORS.get(location_region, []))
            if any(npc_faction in _KENSHI_REGION_FACTIONS.get(r, set()) for r in candidates):
                vague_lines.append(f"- {day_prefix}{summary_vague}")
        elif radius == "local":
            if npc_faction in _KENSHI_REGION_FACTIONS.get(location_region, set()):
                vague_lines.append(f"- {day_prefix}{summary_vague}")

    if not full_lines and not vague_lines:
        return ""
    parts = ["[CAMPAIGN CHRONICLE]"]
    if full_lines:
        parts += ["Historical events known to this NPC:"] + full_lines
    if vague_lines:
        parts += ["Distant rumors this NPC has heard:"] + vague_lines
    return "\n".join(parts)
