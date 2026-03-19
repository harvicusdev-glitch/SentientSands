import random


MAJOR_FACTIONS = [
    "The Holy Nation", "United Cities", "Shek Kingdom",
    "Traders Guild", "Slave Traders", "Western Hive",
    "Anti-Slavers", "Flotsam Ninjas", "Mongrel", "The Hub",
    "Hounds", "Deadcat", "Black Desert City", "Northern Hive",
    "Midland Hive", "The Dominion", "The Order of Chitrin",
    "Hiningenteki Hantas", "Narkos Disciples", "Mechanical Hive"
]

ANIMAL_RACES = [
    "Bonedog", "Boneyard Wolf", "Garru", "Beak Thing", "Gorillo",
    "Landbat", "Goat", "Bull", "Leviathan", "Blood Spider", "Skin Spider",
    "Cave Crawler", "Crab", "Raptor", "Darkfinger", "Cleaner",
    "Crimper", "Skimmer", "Beeler", "Bat", "Spider", "Wolf", "Scorpion",
    "Antelope", "Lizard Bird", "Beak Bot", "ogre", "Cage Beast", "Waste Fiend",
    "Fog Fiend", "Mist Fiend", "Hyena", "Bone Jackal", "Bone Mutt", "Bog Dog",
    "Dune Dog", "False Scorpions", "Mist Ghoul", "Mist Horror", "Mist Mother",
    "Grievewraith"
]

# Mechanical "animal" units — robots designed in animal/vehicle form.
# Unlike biological animals they produce no organic sounds; respond only with mechanical status emissions.
MACHINE_RACES = [
    "Sailback", "Thrasher", "Iron Hound", "Grigori", "MEGAHAULER", "Dreadnought Strider",
    "Iron Skimmer", "Wheel Spider", "Processor unit", "Blood carrier", "Iron Wasp", "Security Spiders",
    "Hydra Security Spider", "Iron Horror", "Pack Paracer", "Automated Mining Drone"
]

_LOYALTY_OPTIONS = ["Fanatical", "Loyal", "Moderate", "Wavering", "Disenchanted"]
_OUTLOOK_OPTIONS = [
    "angry", "sad", "joyful", "content", "at peace",
    "adventurous", "calculating", "callous", "melancholic",
    "lazy", "curious", "hedonistic", "psychopathic"
]

_LOYALTY_WEIGHTS = {
    # [Fanatical, Loyal, Moderate, Wavering, Disenchanted]
    "the holy nation":      [35, 35, 20,  8,  2],
    "united cities":        [8, 20, 35, 25, 12],
    "shek kingdom":         [25, 40, 25,  8,  2],
    "traders guild":        [5, 20, 40, 25, 10],
    "slave traders":        [5, 15, 35, 30, 15],
    "western hive":         [45, 35, 15,  4,  1],
    "northern hive":        [45, 35, 15,  4,  1],
    "midland hive":         [45, 35, 15,  4,  1],
    "mechanical hive":      [45, 35, 15,  4,  1],
    "dark hive":            [10, 20, 35, 25, 10],
    "anti-slavers":         [20, 35, 30, 10,  5],
    "flotsam ninjas":       [15, 30, 35, 15,  5],
    "mongrel":              [5, 15, 35, 30, 15],
    "the hub":              [2, 10, 35, 33, 20],
    "hounds":               [5, 15, 30, 30, 20],
    "deadcat":              [5, 15, 35, 30, 15],
    "black desert city":    [5, 15, 35, 30, 15],
    "the dominion":         [20, 35, 30, 10,  5],
    "the order of chitrin": [30, 35, 25,  8,  2],
    "hiningenteki hantas":  [25, 35, 25, 10,  5],
    "narkos disciples":     [20, 30, 30, 15,  5],
    "tech hunters":         [5, 15, 35, 30, 15],
    "guild of surgeons":    [5, 20, 40, 25, 10],
    "shinobi thieves":      [10, 25, 35, 20, 10],
    "manhunters":           [5, 20, 35, 25, 15],
    "dust bandits":         [3, 10, 30, 35, 22],
    "starving bandits":     [2,  8, 25, 35, 30],
    "dune renegades":       [3, 10, 30, 32, 25],
    "reavers":              [5, 15, 30, 30, 20],
    "nomads":               [3, 10, 35, 30, 22],
    "holy nation outlaws":  [5, 10, 25, 35, 25],
    "skin bandits":         [10, 20, 30, 25, 15],
    "cannibals":            [5, 15, 35, 30, 15],
    "kral's chosen":        [30, 40, 20,  7,  3],
    "band of bones":        [25, 40, 25,  7,  3],
    "berserkers":           [20, 35, 30, 10,  5],
    "scorched ones":        [5, 15, 35, 30, 15],
    "reawakened":           [5, 15, 35, 30, 15],
    "highlanders":          [10, 25, 35, 20, 10],
    "_default":             [5, 15, 40, 25, 15],
}

# Named religion pools: list of (label, weight) tuples per faction.
# Hard-coded before table lookup: Skeletons → "N/A", in-faction Hivers → "Hive-Bound",
# out-of-faction Hivers → "Hiveless", Cannibals → "Cannibalism", Fogmen → "Fogmen".
# None of these use this table.
_RELIGION_TABLE = {
    "the holy nation": [
        ("Zealot Okranite", 40), ("Devout Okranite", 35), ("Observant Okranite", 15),
        ("Secular", 5), ("Narkoite", 5),
    ],
    "narkos disciples": [
        ("Zealot Narkoite", 35), ("Devout Narkoite", 35), ("Follower of Narko", 20),
        ("Secular", 10),
    ],
    "shek kingdom": [
        ("Devoted to Kral", 20), ("Follower of Kral", 35), ("Respectful of Kral", 25),
        ("Secular", 20),
    ],
    "kral's chosen": [
        ("Zealot of Kral", 45), ("Devoted to Kral", 35), ("Follower of Kral", 15),
        ("Secular", 5),
    ],
    "band of bones": [
        ("Zealot of Kral", 40), ("Devoted to Kral", 35), ("Follower of Kral", 20),
        ("Secular", 5),
    ],
    "berserkers": [
        ("Devoted to Kral", 30), ("Follower of Kral", 35), ("Zealot of Kral", 20),
        ("Secular", 15),
    ],
    "the order of chitrin": [
        ("Zealot Chitrinite", 35), ("Devout Chitrinite", 40), ("Chitrinite", 20),
        ("Secular", 5),
    ],
    "united cities": [
        ("Secular", 50), ("Agnostic", 20), ("Casual Okranite", 15),
        ("Observant Okranite", 10), ("Follower of Kral", 5),
    ],
    "traders guild": [
        ("Secular", 60), ("Agnostic", 25), ("Casual Okranite", 10),
        ("Follower of Kral", 5),
    ],
    "slave traders": [
        ("Secular", 50), ("Agnostic", 25), ("Casual Okranite", 20),
        ("Follower of Kral", 5),
    ],
    "anti-slavers": [
        ("Secular", 40), ("Agnostic", 25), ("Follower of Kral", 15),
        ("Casual Okranite", 10), ("Narkoite", 10),
    ],
    "flotsam ninjas": [
        ("Secular", 45), ("Agnostic", 30), ("Narkoite", 15),
        ("Follower of Kral", 10),
    ],
    "hounds": [
        ("Secular", 55), ("Agnostic", 30), ("Casual Okranite", 15),
    ],
    "tech hunters": [
        ("Secular", 55), ("Agnostic", 30), ("Casual Okranite", 10),
        ("Follower of Kral", 5),
    ],
    "holy nation outlaws": [
        ("Secular", 40), ("Agnostic", 25), ("Narkoite", 20),
        ("Casual Okranite", 10), ("Follower of Kral", 5),
    ],
    # "skin bandits" intentionally omitted — all members are Skeletons, religion is always N/A
    # "cannibals" intentionally omitted — all members always receive "Cannibalism" before table lookup
    "highlanders": [
        ("Secular", 35), ("Agnostic", 25), ("Casual Okranite", 25),
        ("Follower of Kral", 15),
    ],
    # "dark hive" intentionally omitted — all Hiver members get "Hiveless" before table lookup (collapsed Queen-structure)
    "_default": [
        ("Secular", 45), ("Agnostic", 25), ("Casual Okranite", 15),
        ("Follower of Kral", 10), ("Narkoite", 5),
    ],
}

_OUTLOOK_WEIGHTS = {
    # weights order matches _OUTLOOK_OPTIONS (13 values):
    # angry, sad, joyful, content, at peace, adventurous, calculating, callous, melancholic, lazy, curious, hedonistic, psychopathic
    "the holy nation":     [20,  5,  5, 10, 10,  5, 15, 10, 10,  2,  5,  1,  2],
    "shek kingdom":        [10,  5, 10, 15, 15, 20, 10,  8,  5,  0,  5,  2,  2],
    "traders guild":       [5,  5, 10, 20,  5, 10, 25,  8,  5,  2,  5,  8,  2],
    "slave traders":       [8,  5,  5, 10,  3,  5, 20, 20,  5,  5,  5,  8,  5],
    "anti-slavers":        [15,  8, 10, 10,  5, 15, 10,  5,  8,  2, 10,  1,  0],
    "flotsam ninjas":      [15,  8, 10, 12,  5, 15, 10,  8,  8,  2,  8,  3,  0],
    "hounds":              [15,  5,  8, 10,  3,  8, 15, 20,  5,  8,  2,  3,  5],
    "tech hunters":        [5,  5, 10, 15,  5, 20, 20,  5,  5,  2, 20,  3,  2],
    "dust bandits":        [20,  5,  5,  5,  2,  5, 10, 25, 10,  5,  3,  5,  5],
    "starving bandits":    [25, 15,  2,  5,  2,  5,  5, 20, 15, 10,  2,  2,  5],
    "dune renegades":      [18,  8,  5,  8,  3,  8, 12, 20,  8,  5,  3,  5,  5],
    "reavers":             [15,  3,  5,  8,  2,  8, 12, 25,  5,  5,  2,  8, 10],
    "manhunters":          [10,  3,  5, 10,  3,  8, 20, 20,  5,  5,  2,  5,  5],
    "skin bandits":        [10,  5,  5, 10,  5,  5, 20, 15, 10,  5,  5,  3,  7],
    "cannibals":           [15,  5,  3,  5,  2,  5,  5, 20, 10,  5,  5, 10, 15],
    "kral's chosen":       [5,  3, 15, 10, 20, 25, 10,  5,  5,  0, 10,  2,  0],
    "band of bones":       [5,  3, 15, 10, 20, 25, 10,  5,  5,  0, 10,  2,  0],
    "berserkers":          [10,  5, 15, 10, 15, 25,  8,  5,  5,  0,  5,  2,  0],
    "highlanders":         [10,  5, 10, 15, 10, 20, 10, 10,  5,  2, 10,  2,  2],
    "dark hive":           [20, 15,  5,  5,  3,  8,  8, 15, 18,  3,  5,  5,  5],
    "_default":            [8,  8,  8, 12,  8, 10, 12,  8,  8,  5,  8,  5,  2],
}

# (probability_of_having_one, pool)
_MOTIVATION_TABLE = {
    "the holy nation":     (0.70, ["anti-slavery", "anti-Anti-Slavers", "anti-Shek Kingdom", "anti-Flotsam Ninjas"]),
    "united cities":       (0.50, ["anti-slavery", "anti-Shek Kingdom", "anti-Flotsam Ninjas", "anti-Anti-Slavers"]),
    "shek kingdom":        (0.50, ["anti-Holy Nation", "anti-United Cities", "anti-slavery"]),
    "traders guild":       (0.40, ["anti-slavery", "anti-Shek Kingdom", "anti-Flotsam Ninjas", "agoraphobic"]),
    "slave traders":       (0.60, ["anti-Anti-Slavers", "anti-Flotsam Ninjas", "anti-Shek Kingdom"]),
    "anti-slavers":        (0.80, ["anti-slavery", "anti-Slave Traders", "anti-United Cities", "anti-Holy Nation"]),
    "flotsam ninjas":      (0.85, ["anti-slavery", "anti-United Cities", "anti-Holy Nation", "agoraphobic"]),
    "hounds":              (0.40, ["anti-United Cities", "anti-Traders Guild", "afraid of machines", "agoraphobic"]),
    "tech hunters":        (0.60, ["artifact hunting", "knowledge seeking", "anti-Holy Nation", "anti-slavery"]),
    "guild of surgeons":   (0.45, ["anti-Holy Nation", "knowledge seeking", "anti-slavery"]),
    "shinobi thieves":     (0.55, ["anti-United Cities", "anti-Traders Guild", "agoraphobic"]),
    "manhunters":          (0.50, ["anti-Anti-Slavers", "anti-Flotsam Ninjas", "anti-non-human"]),
    "dust bandits":        (0.35, ["anti-United Cities", "anti-Traders Guild", "agoraphobic"]),
    "starving bandits":    (0.30, ["anti-United Cities", "agoraphobic", "afraid of spiders"]),
    "dune renegades":      (0.35, ["anti-United Cities", "anti-Traders Guild", "agoraphobic"]),
    "reavers":             (0.45, ["anti-United Cities", "anti-Traders Guild", "anti-Shek Kingdom"]),
    "nomads":              (0.30, ["agoraphobic", "afraid of spiders", "anti-slavery"]),
    "holy nation outlaws": (0.60, ["anti-Holy Nation", "anti-slavery", "anti-Okranite doctrine"]),
    "skin bandits":        (0.90, ["anti-organic", "zealot of the flesh doctrine", "knowledge seeking"]),
    "cannibals":           (0.40, ["afraid of machines", "agoraphobic", "anti-slavery"]),
    "kral's chosen":       (0.85, ["seeking warrior's death", "anti-Holy Nation", "anti-United Cities"]),
    "band of bones":       (0.80, ["seeking warrior's death", "anti-Holy Nation", "anti-Shek Kingdom reformers"]),
    "berserkers":          (0.75, ["seeking warrior's death", "anti-Holy Nation", "anti-United Cities"]),
    "scorched ones":       (0.40, ["anti-Holy Nation", "agoraphobic", "afraid of machines"]),
    "dark hive":           (0.50, ["anti-Skeleton", "afraid of machines", "anti-Holy Nation"]),
    "highlanders":         (0.45, ["anti-Holy Nation", "anti-United Cities", "anti-slavery"]),
    "hiningenteki hantas": (0.90, ["anti-Holy Nation", "anti-slavery", "anti-non-human persecution", "anti-United Cities"]),
    "_skeleton":           (0.50, ["anti-Skeleton", "anti-slavery", "afraid of spiders", "afraid of machines"]),
    "_default":            (0.35, ["anti-slavery", "agoraphobic", "afraid of spiders", "afraid of machines"]),
}


def generate_npc_traits(faction, race, origin_faction=""):
    """Generate weighted-random NPC traits at profile creation. Returns {} for animals/machines."""
    race_lower = (race or "").lower()
    if any(a.lower() in race_lower for a in ANIMAL_RACES):
        return {}
    if any(m.lower() in race_lower for m in MACHINE_RACES):
        return {}

    faction_lower = (faction or "").lower().strip()
    origin_lower = (origin_faction or "").lower().strip()
    is_skeleton = "skeleton" in race_lower
    is_hiver = "hive" in race_lower
    is_shek = "shek" in race_lower
    # Dark Hive excluded: its Queen-structure collapsed; members are effectively severed
    is_in_hive_faction = "hive" in faction_lower and faction_lower != "dark hive"

    loy_w = _LOYALTY_WEIGHTS.get(faction_lower) or _LOYALTY_WEIGHTS.get(origin_lower) or _LOYALTY_WEIGHTS["_default"]
    loyalty = random.choices(_LOYALTY_OPTIONS, weights=loy_w, k=1)[0]

    if is_skeleton:
        religion = "N/A"
    elif is_hiver and is_in_hive_faction:
        religion = "Hive-Bound"
    elif is_hiver:
        # Hiver race outside any Hive faction — cut off from the Queen's pheromones
        religion = "Hiveless"
    elif faction_lower == "cannibals" or origin_lower == "cannibals":
        religion = "Cannibalism"
    elif faction_lower == "fogmen" or "fogman" in race_lower:
        religion = "Fogmen"
    else:
        rel_pool = (
            _RELIGION_TABLE.get(faction_lower)
            or _RELIGION_TABLE.get(origin_lower)
            or _RELIGION_TABLE["_default"]
        )
        if not is_shek:
            rel_pool = [(label, w) for label, w in rel_pool if "Kral" not in label]
        if not rel_pool:
            rel_pool = [("Secular", 1)]
        labels, weights = zip(*rel_pool)
        religion = random.choices(labels, weights=weights, k=1)[0]

    out_w = _OUTLOOK_WEIGHTS.get(faction_lower) or _OUTLOOK_WEIGHTS.get(origin_lower) or _OUTLOOK_WEIGHTS["_default"]
    outlook = random.choices(_OUTLOOK_OPTIONS, weights=out_w, k=1)[0]

    if is_skeleton and faction_lower == "skin bandits":
        mot_prob, mot_pool = _MOTIVATION_TABLE["skin bandits"]
    elif is_skeleton:
        mot_prob, mot_pool = _MOTIVATION_TABLE["_skeleton"]
    else:
        mot_prob, mot_pool = (
            _MOTIVATION_TABLE.get(faction_lower)
            or _MOTIVATION_TABLE.get(origin_lower)
            or _MOTIVATION_TABLE["_default"]
        )
    motivation = random.choice(mot_pool) if random.random() < mot_prob else None

    return {"Loyalty": loyalty, "Religion": religion, "Outlook": outlook, "Motivation": motivation}


def build_loyalty_note(npc_name, faction, player_faction, faction_id=None):
    notes = []
    if faction == player_faction or faction_id == "Nameless":
        # Preserve the existing Nameless factionID compatibility quirk for player-faction members.
        notes.append(f"CRITICAL CONTEXT: {npc_name} is a member of the PLAYER'S FACTION ({player_faction}).")
        notes.append(
            f"THE PLAYER IS THE LEADER of this group. {npc_name} understand that they and the player are cooperating, "
            "this can take many forms such as direct leadership, partnership, or even just individuals traveling together."
        )
    elif any(f.lower() in faction.lower() for f in MAJOR_FACTIONS):
        notes.append(
            f"LOYALTY NOTE: {npc_name} belongs to {faction}, a major world power. They are deeply rooted in their society. "
            "They will NOT desert their faction to join the player's minor squad without an EXTREMELY compelling narrative reason, "
            "high reputation, or having their life saved multiple times. Be highly resistant to recruitment."
        )
    return notes


def get_trait_parts(traits):
    traits = traits or {}
    parts = []
    if traits.get("Loyalty"):
        parts.append(f"Loyalty={traits['Loyalty']}")
    if traits.get("Religion") and traits["Religion"] != "N/A":
        parts.append(f"Religion={traits['Religion']}")
    if traits.get("Outlook"):
        parts.append(f"Outlook={traits['Outlook']}")
    if traits.get("Motivation"):
        parts.append(f"Motivation={traits['Motivation']}")
    return parts
