#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
from dataclasses import dataclass
from typing import Any, Optional, List, Tuple, Dict, Set


@dataclass
class Event:
    raw: str
    day: Optional[int] = None
    game_time: Optional[str] = None
    event_type: Optional[str] = None
    source_name: Optional[str] = None
    source_faction: Optional[str] = None
    target_name: Optional[str] = None
    target_faction: Optional[str] = None
    location: Optional[str] = None
    detail: Optional[str] = None


DAY_PREFIX_RE = re.compile(r"^\[Day (?P<day>\d+),\s*(?P<time>\d{2}:\d{2})\]\s*", re.IGNORECASE)
EVENT_TYPE_RE = re.compile(r"^\[(?P<event_type>[^\]]+)\]\s*", re.IGNORECASE)
NAME_FACTION_RE = re.compile(r"^(?P<name>.*?)\s*\((?P<faction>.*?)\)$")
TRAILING_ENTITY_ID_RE = re.compile(r"\|[-]?\d+\b")


def canonical_spaces(text: Optional[str]) -> str:
    text = TRAILING_ENTITY_ID_RE.sub("", (text or ""))
    return re.sub(r"\s+", " ", text).strip()


def split_name_and_faction(text: str) -> Tuple[str, Optional[str]]:
    text = canonical_spaces(text)
    if text == "None":
        return "None", None

    m = NAME_FACTION_RE.match(text)
    if m:
        name = canonical_spaces(m.group("name"))
        faction = canonical_spaces(m.group("faction"))
    else:
        name = text
        faction = None

    name = TRAILING_ENTITY_ID_RE.sub("", name).strip()
    return name, faction


def find_last_sep_outside_parens(text: str, sep: str) -> int:
    depth = 0
    for i in range(len(text) - len(sep), -1, -1):
        ch = text[i]
        if ch == ")":
            depth += 1
        elif ch == "(":
            depth = max(0, depth - 1)
        if depth == 0 and text[i:i + len(sep)] == sep:
            return i
    return -1


def find_first_sep_outside_parens(text: str, sep: str) -> int:
    depth = 0
    for i in range(len(text) - len(sep) + 1):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if depth == 0 and text[i:i + len(sep)] == sep:
            return i
    return -1


def parse_event_line(line: str, current_day: Optional[int]) -> Tuple[Optional[Event], Optional[int]]:
    original_line = canonical_spaces(line)
    if not original_line or original_line.lower() == "unconscious":
        return None, current_day

    line = original_line
    day = current_day
    game_time = None

    m = DAY_PREFIX_RE.match(line)
    if m:
        day = int(m.group("day"))
        game_time = m.group("time")
        line = line[m.end():]

    m = EVENT_TYPE_RE.match(line)
    if not m:
        return None, current_day

    event_type = canonical_spaces(m.group("event_type")).lower()
    line = line[m.end():]

    detail_sep = find_last_sep_outside_parens(line, ": ")
    if detail_sep == -1:
        return None, day

    left = canonical_spaces(line[:detail_sep])
    detail = canonical_spaces(line[detail_sep + 2:])

    location = None
    loc_sep = find_last_sep_outside_parens(left, " @ ")
    if loc_sep != -1:
        location = canonical_spaces(left[loc_sep + 3:])
        left = canonical_spaces(left[:loc_sep])

    arrow_sep = find_first_sep_outside_parens(left, " -> ")
    if arrow_sep == -1:
        return None, day

    source_text = canonical_spaces(left[:arrow_sep])
    target_text = canonical_spaces(left[arrow_sep + 4:])

    source_name, source_faction = split_name_and_faction(source_text)
    target_name, target_faction = split_name_and_faction(target_text)

    event = Event(
        raw=original_line,
        day=day,
        game_time=game_time,
        event_type=event_type,
        source_name=source_name,
        source_faction=source_faction,
        target_name=target_name,
        target_faction=target_faction,
        location=location,
        detail=detail,
    )
    return event, day


def normalize_faction(faction: Optional[str], name: Optional[str]) -> str:
    if faction:
        return canonical_spaces(faction)
    if name and name != "None":
        return canonical_spaces(name)
    return "Unknown enemies"


def is_unknown_faction_name(name: Optional[str]) -> bool:
    return canonical_spaces(name).lower() in {"unknown", "unknown enemies", "unknown people"}


def is_player_faction(faction: Optional[str]) -> bool:
    return bool(faction and "player" in faction.lower())


def involves_player(event: Event) -> bool:
    return is_player_faction(event.source_faction) or is_player_faction(event.target_faction)


def get_player_faction_name(event: Event) -> str:
    for faction in (event.source_faction, event.target_faction):
        if faction:
            if is_player_faction(faction):
                m = re.search(r"Player's Squad:\s*(.+)$", faction, re.IGNORECASE)
                if m:
                    return canonical_spaces(m.group(1))
    return "Player squad"


def is_trade_event(event: Event) -> bool:
    return event.event_type == "trade"


def is_violent_event(event: Event) -> bool:
    return event.event_type in {"combat", "knockout", "slavery", "death", "dead", "imprisonment", "prison", "attack"}


def is_loss_event(event: Event) -> bool:
    return event.event_type in {"knockout", "death", "dead"}


def is_enslavement_event(event: Event) -> bool:
    return event.event_type == "slavery" and "forced into slavery" in (event.detail or "").lower()


def is_freed_slavery_event(event: Event) -> bool:
    return event.event_type == "slavery" and "freed from slavery" in (event.detail or "").lower()


def is_imprisonment_event(event: Event) -> bool:
    if event.event_type not in {"imprisonment", "prison"}:
        return False
    d = (event.detail or "").lower()
    return "imprison" in d or "jailed" in d


def is_released_imprisonment_event(event: Event) -> bool:
    if event.event_type not in {"imprisonment", "prison"}:
        return False
    d = (event.detail or "").lower()
    return "released from prison" in d


def render_event(event: Event) -> str:
    prefix = ""
    if event.day is not None and event.game_time:
        prefix = f"[Day {event.day}, {event.game_time}] "
    elif event.day is not None:
        prefix = f"[Day {event.day}] "

    source = event.source_name or "Unknown"
    if event.source_faction:
        source += f" ({event.source_faction})"

    target = event.target_name or "Unknown"
    if event.target_faction:
        target += f" ({event.target_faction})"

    middle = f"[{event.event_type}] {source} -> {target}"
    if event.location:
        middle += f" @ {event.location}"

    return f"{prefix}{middle}: {event.detail}"


def normalize_item_name(item: str) -> Optional[str]:
    item = canonical_spaces(item).replace('"', "")
    if not item:
        return None
    small = {"of", "and", "the", "in", "on", "to", "for", "a", "an"}
    words = item.split()
    out = []
    for i, w in enumerate(words):
        lw = w.lower()
        out.append(lw if i > 0 and lw in small else lw.capitalize())
    return " ".join(out)


def extract_bought_item(detail: str) -> Optional[str]:
    m = re.match(r"^Bought\s+(.+?)\s*$", detail or "", re.IGNORECASE)
    if not m:
        return None
    return normalize_item_name(m.group(1))


def join_with_and(parts: List[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f" and {parts[-1]}"


def pair_key(a: str, b: str) -> Tuple[str, str]:
    a, b = sorted((a, b))
    return a, b


def setback_word(n: int) -> str:
    return "setback" if n == 1 else "setbacks"


def member_word(n: int) -> str:
    return "member" if n == 1 else "members"


def was_were(n: int) -> str:
    return "was" if n == 1 else "were"


def location_label(loc: Optional[str]) -> str:
    return canonical_spaces(loc) if loc else "Unspecified area"


def extract_raw_events_from_text(text: str) -> List[Event]:
    events: List[Event] = []
    current_day: Optional[int] = None

    for raw_line in text.splitlines():
        ev, current_day = parse_event_line(raw_line, current_day)
        if ev is not None:
            events.append(ev)

    return events


def summarize_player_day(day: int, events: List[Event]) -> Optional[str]:
    player_events = [e for e in events if involves_player(e)]
    if not player_events:
        return None

    player_faction_name = get_player_faction_name(player_events[0])

    locations: Set[str] = set()
    enemy_factions: Set[str] = set()
    encountered_enemy_names: Set[str] = set()
    squad_setbacks = 0
    enemies_defeated = 0
    top_fighter: Dict[str, int] = {}
    kia: Set[str] = set()
    imprisoned: Set[str] = set()

    # First pass: identify all enemies encountered in combat to know who to count as an 'enemy defeat' later.
    for ev in player_events:
        if ev.event_type == "combat":
            if is_player_faction(ev.source_faction) and not is_player_faction(ev.target_faction):
                ef = normalize_faction(ev.target_faction, ev.target_name)
                if not is_unknown_faction_name(ef):
                    enemy_factions.add(ef)
                if ev.target_name and ev.target_name != "None":
                    encountered_enemy_names.add(ev.target_name)
            elif is_player_faction(ev.target_faction) and not is_player_faction(ev.source_faction):
                ef = normalize_faction(ev.source_faction, ev.source_name)
                if not is_unknown_faction_name(ef):
                    enemy_factions.add(ef)
                if ev.source_name and ev.source_name != "None":
                    encountered_enemy_names.add(ev.source_name)

    # Second pass: process all events with full context of who the enemies were.
    for ev in player_events:
        if ev.location:
            locations.add(location_label(ev.location))

        if ev.event_type == "combat":
            if is_player_faction(ev.source_faction) and ev.source_name and ev.source_name != "None":
                top_fighter[ev.source_name] = top_fighter.get(ev.source_name, 0) + 1

        if is_loss_event(ev):
            if is_player_faction(ev.target_faction):
                squad_setbacks += 1
            else:
                victim_faction = normalize_faction(ev.target_faction, ev.target_name)
                victim_name = ev.target_name or ""
                if victim_name in encountered_enemy_names or victim_faction in enemy_factions:
                    enemies_defeated += 1

        elif is_enslavement_event(ev):
            if is_player_faction(ev.source_faction):
                squad_setbacks += 1
            else:
                victim_faction = normalize_faction(ev.source_faction, ev.source_name)
                victim_name = ev.source_name or ""
                if victim_name in encountered_enemy_names or victim_faction in enemy_factions:
                    enemies_defeated += 1

        elif is_imprisonment_event(ev) and not is_released_imprisonment_event(ev):
            if is_player_faction(ev.source_faction):
                squad_setbacks += 1
                if ev.source_name and ev.source_name != "None":
                    imprisoned.add(ev.source_name)
            else:
                victim_faction = normalize_faction(ev.source_faction, ev.source_name)
                victim_name = ev.source_name or ""
                if victim_name in encountered_enemy_names or victim_faction in enemy_factions:
                    enemies_defeated += 1

        if ev.event_type in {"death", "dead"}:
            if is_player_faction(ev.source_faction) and ev.source_name and ev.source_name != "None":
                kia.add(ev.source_name)
            elif is_player_faction(ev.target_faction) and ev.target_name and ev.target_name != "None":
                kia.add(ev.target_name)

    has_activity = bool(enemy_factions or squad_setbacks or enemies_defeated or kia or imprisoned or top_fighter or locations)
    if not has_activity:
        return None

    parts: List[str] = []

    if locations:
        parts.append(f"Locations: {join_with_and(sorted(locations))}")

    if enemy_factions:
        parts.append(f"{player_faction_name} fought against {join_with_and(sorted(enemy_factions))}")

    if squad_setbacks > 0 or enemies_defeated > 0:
        parts.append(
            f"{player_faction_name} suffered {squad_setbacks} {setback_word(squad_setbacks)} and left {enemies_defeated} enemies defeated"
        )

    if top_fighter:
        fighter, _ = max(sorted(top_fighter.items()), key=lambda kv: kv[1])
        parts.append(f"{fighter} was the top fighter")

    if kia:
        parts.append(f"Killed in action: {join_with_and(sorted(kia))}")

    if imprisoned:
        parts.append(f"Imprisoned: {join_with_and(sorted(imprisoned))}")

    return f"[Day {day}] [player-summary] " + ". ".join(parts) + "."


def build_day_narrative(day: int, loc_summaries: Dict[str, Dict[str, Any]], player_summary: Optional[str]) -> Optional[str]:
    pieces: List[str] = []

    for loc, info in sorted(loc_summaries.items()):
        local_bits: List[str] = []

        trade_items = info.get("trade_items", [])
        violence_factions = info.get("violence_factions", [])
        preserved_count = info.get("preserved_count", 0)

        if trade_items:
            local_bits.append(f"trade moved through {loc}, especially {join_with_and(trade_items[:3])}")

        if violence_factions:
            local_bits.append(f"{loc} saw violence involving {join_with_and(violence_factions[:3])}")

        if preserved_count:
            local_bits.append(f"other incidents also unfolded in {loc}")

        if local_bits:
            pieces.append("; ".join(local_bits))

    if player_summary:
        pieces.append("the player's faction remained active across the wastes")

    if not pieces:
        return None

    return f"[Day {day}] [day-narrative] " + ". ".join(pieces) + "."


def summarize_player_trade_location(day: int, loc: str, player_faction_name: str, bought_items: Dict[str, int], sold_items: Dict[str, int]) -> Optional[str]:
    bought_parts = [f"{count} {item}" for item, count in sorted(bought_items.items())]
    sold_parts = [f"{count} {item}" for item, count in sorted(sold_items.items())]

    if not bought_parts and not sold_parts:
        return None

    if bought_parts and sold_parts:
        return (
            f"[Day {day}] [player-trade] @ {loc}: {player_faction_name} bought {join_with_and(bought_parts)}, "
            f"while selling {join_with_and(sold_parts)}."
        )

    if bought_parts:
        return f"[Day {day}] [player-trade] @ {loc}: {player_faction_name} bought {join_with_and(bought_parts)}."

    return f"[Day {day}] [player-trade] @ {loc}: {player_faction_name} sold {join_with_and(sold_parts)}."


def simplify_events_to_consolidated_text(events: List[Event]) -> str:
    player_member_names: Set[str] = set()
    global_player_faction_name = "Player squad"

    for ev in events:
        if involves_player(ev):
            global_player_faction_name = get_player_faction_name(ev)
            if is_player_faction(ev.source_faction) and ev.source_name and ev.source_name != "None":
                player_member_names.add(ev.source_name)
            if is_player_faction(ev.target_faction) and ev.target_name and ev.target_name != "None":
                player_member_names.add(ev.target_name)

    events_by_day: Dict[int, List[Event]] = {}
    preserved_by_day_loc: Dict[int, Dict[str, List[Tuple[str, str]]]] = {}
    trade_by_day_loc: Dict[int, Dict[str, Dict[str, int]]] = {}
    player_bought_by_day_loc: Dict[int, Dict[str, Dict[str, int]]] = {}
    player_sold_by_day_loc: Dict[int, Dict[str, Dict[str, int]]] = {}
    player_faction_by_day: Dict[int, str] = {}
    freed_by_day_faction_loc: Dict[int, Dict[str, Dict[str, int]]] = {}
    pair_stats_by_day_loc: Dict[int, Dict[str, Dict[Tuple[str, str], Dict[str, int]]]] = {}
    known_opponents_by_day_loc: Dict[int, Dict[str, Dict[str, Set[str]]]] = {}
    unknown_inflicted_by_day_loc: Dict[int, Dict[str, Dict[str, int]]] = {}

    for ev in events:
        if ev.day is None:
            continue

        events_by_day.setdefault(ev.day, []).append(ev)

        day = ev.day
        loc = location_label(ev.location)
        time_str = ev.game_time or "99:99"

        if is_trade_event(ev):
            item = extract_bought_item(ev.detail or "")
            if item:
                source_is_player = is_player_faction(ev.source_faction) or (ev.source_name in player_member_names)
                target_is_player = is_player_faction(ev.target_faction)
                target_is_player_counter = target_is_player and "shop counter" in canonical_spaces(ev.target_name).lower()

                if source_is_player and not target_is_player_counter:
                    player_bought_by_day_loc.setdefault(day, {}).setdefault(loc, {})
                    player_bought_by_day_loc[day][loc][item] = player_bought_by_day_loc[day][loc].get(item, 0) + 1
                    player_faction_by_day.setdefault(day, global_player_faction_name)
                    continue

                if target_is_player_counter:
                    player_sold_by_day_loc.setdefault(day, {}).setdefault(loc, {})
                    player_sold_by_day_loc[day][loc][item] = player_sold_by_day_loc[day][loc].get(item, 0) + 1
                    player_faction_by_day.setdefault(day, global_player_faction_name)
                    continue

                trade_by_day_loc.setdefault(day, {}).setdefault(loc, {})
                trade_by_day_loc[day][loc][item] = trade_by_day_loc[day][loc].get(item, 0) + 1
                continue

            if not involves_player(ev):
                preserved_by_day_loc.setdefault(day, {}).setdefault(loc, []).append((time_str, render_event(ev)))
            continue

        if involves_player(ev):
            continue

        if not is_violent_event(ev):
            preserved_by_day_loc.setdefault(day, {}).setdefault(loc, []).append((time_str, render_event(ev)))
            continue

        if ev.event_type == "combat":
            attacker = normalize_faction(ev.source_faction, ev.source_name)
            defender = normalize_faction(ev.target_faction, ev.target_name)

            if is_unknown_faction_name(attacker) or is_unknown_faction_name(defender):
                continue

            pk = pair_key(attacker, defender)
            pair_stats_by_day_loc.setdefault(day, {}).setdefault(loc, {}).setdefault(pk, {pk[0]: 0, pk[1]: 0})
            known_opponents_by_day_loc.setdefault(day, {}).setdefault(loc, {}).setdefault(defender, set()).add(attacker)
            known_opponents_by_day_loc.setdefault(day, {}).setdefault(loc, {}).setdefault(attacker, set()).add(defender)
            continue

        if is_freed_slavery_event(ev):
            faction = normalize_faction(ev.source_faction, ev.source_name)
            if is_unknown_faction_name(faction):
                continue
            freed_by_day_faction_loc.setdefault(day, {}).setdefault(loc, {})
            freed_by_day_faction_loc[day][loc][faction] = freed_by_day_faction_loc[day][loc].get(faction, 0) + 1
            continue

        victim = None
        attacker_hint = None

        if is_loss_event(ev):
            victim = normalize_faction(ev.target_faction, ev.target_name)
            attacker_hint = normalize_faction(ev.source_faction, ev.source_name)
        elif is_enslavement_event(ev):
            victim = normalize_faction(ev.source_faction, ev.source_name)
            attacker_hint = normalize_faction(ev.target_faction, ev.target_name)
        elif is_imprisonment_event(ev):
            victim = normalize_faction(ev.source_faction, ev.source_name)
            attacker_hint = normalize_faction(ev.target_faction, ev.target_name)

        if not victim or is_unknown_faction_name(victim):
            continue

        if attacker_hint and not is_unknown_faction_name(attacker_hint) and attacker_hint != "None":
            enemy = attacker_hint
            pk = pair_key(victim, enemy)
            pair_stats_by_day_loc.setdefault(day, {}).setdefault(loc, {}).setdefault(pk, {pk[0]: 0, pk[1]: 0})
            pair_stats_by_day_loc[day][loc][pk][victim] += 1
        else:
            opponents = known_opponents_by_day_loc.get(day, {}).get(loc, {}).get(victim, set())
            if len(opponents) == 1:
                enemy = next(iter(opponents))
                pk = pair_key(victim, enemy)
                pair_stats_by_day_loc.setdefault(day, {}).setdefault(loc, {}).setdefault(pk, {pk[0]: 0, pk[1]: 0})
                pair_stats_by_day_loc[day][loc][pk][victim] += 1
            else:
                unknown_inflicted_by_day_loc.setdefault(day, {}).setdefault(loc, {})
                unknown_inflicted_by_day_loc[day][loc][victim] = unknown_inflicted_by_day_loc[day][loc].get(victim, 0) + 1

    all_days = sorted(
        set(events_by_day.keys())
        | set(preserved_by_day_loc.keys())
        | set(trade_by_day_loc.keys())
        | set(player_bought_by_day_loc.keys())
        | set(player_sold_by_day_loc.keys())
        | set(pair_stats_by_day_loc.keys())
        | set(freed_by_day_faction_loc.keys())
        | set(unknown_inflicted_by_day_loc.keys())
    )

    out: List[str] = []

    for day in all_days:
        out.append(f"[Day {day}]")

        day_loc_summaries: Dict[str, Dict[str, object]] = {}

        all_locations = sorted(
            set(preserved_by_day_loc.get(day, {}).keys())
            | set(trade_by_day_loc.get(day, {}).keys())
            | set(player_bought_by_day_loc.get(day, {}).keys())
            | set(player_sold_by_day_loc.get(day, {}).keys())
            | set(pair_stats_by_day_loc.get(day, {}).keys())
            | set(freed_by_day_faction_loc.get(day, {}).keys())
            | set(unknown_inflicted_by_day_loc.get(day, {}).keys())
        )

        for loc in all_locations:
            out.append(f"@ {loc}")

            day_loc_summaries.setdefault(loc, {
                "trade_items": [],
                "violence_factions": [],
                "preserved_count": 0,
            })

            preserved_lines = sorted(preserved_by_day_loc.get(day, {}).get(loc, []), key=lambda x: (x[0], x[1]))
            if preserved_lines:
                for _, line in preserved_lines:
                    out.append(f"Other event: {line}")
                day_loc_summaries[loc]["preserved_count"] = len(preserved_lines)

            trade_items = trade_by_day_loc.get(day, {}).get(loc, {})
            if trade_items:
                parts = [f"{count} {item}" for item, count in sorted(trade_items.items())]
                out.append(f"Trade summary: sold {join_with_and(parts)} to people.")
                day_loc_summaries[loc]["trade_items"] = list(sorted(trade_items.keys()))

            violence_lines: List[Tuple[int, str]] = []
            violence_factions: Set[str] = set()

            for victim, count in sorted(unknown_inflicted_by_day_loc.get(day, {}).get(loc, {}).items()):
                violence_lines.append((count, f"Unknown enemies inflicted {count} {setback_word(count)} on {victim}"))
                violence_factions.add(victim)

            for (fa, fb), losses in pair_stats_by_day_loc.get(day, {}).get(loc, {}).items():
                loss_a = losses.get(fa, 0)
                loss_b = losses.get(fb, 0)
                if loss_a == 0 and loss_b == 0:
                    continue
                violence_lines.append(
                    (max(loss_a, loss_b), f"{fa} suffered {loss_a} {setback_word(loss_a)} while inflicting {loss_b} on {fb}")
                )
                violence_factions.add(fa)
                violence_factions.add(fb)

            for faction, count in sorted(freed_by_day_faction_loc.get(day, {}).get(loc, {}).items()):
                violence_lines.append((count, f"{count} {faction} {member_word(count)} {was_were(count)} freed from slavery"))
                violence_factions.add(faction)

            violence_lines.sort(reverse=True, key=lambda x: x[0])
            violence_text = [line for _, line in violence_lines]

            if violence_text:
                out.append("Violence summary: " + ". ".join(violence_text) + ".")
                day_loc_summaries[loc]["violence_factions"] = sorted(violence_factions)

            player_trade_line = summarize_player_trade_location(
                day,
                loc,
                player_faction_by_day.get(day, global_player_faction_name),
                player_bought_by_day_loc.get(day, {}).get(loc, {}),
                player_sold_by_day_loc.get(day, {}).get(loc, {}),
            )
            if player_trade_line:
                out.append(player_trade_line)

        player_summary = summarize_player_day(day, events_by_day.get(day, []))
        if player_summary:
            out.append(player_summary)

        day_narrative = build_day_narrative(day, day_loc_summaries, player_summary)
        if day_narrative:
            out.append(day_narrative)

        out.append("")

    return "\n".join(out).strip() + "\n"


def extra_token_reduction(text: str) -> str:
    lines = text.splitlines()
    cleaned: List[str] = []
    seen: Set[str] = set()

    for line in lines:
        if "(Overheard)" in line:
            continue

        if re.match(r"^Other event: \[Day \d+(?:, \d{2}:\d{2})?\] \[city_transfer\] No Faction \(No Faction\) -> .*", line):
            continue

        line = re.sub(r"\s+", " ", line).rstrip()
        if not line:
            cleaned.append("")
            continue

        if line.startswith("Other event:") and line in seen:
            continue

        if line in seen and not line.startswith("[Day "):
            continue

        seen.add(line)
        cleaned.append(line)

    final_lines: List[str] = []
    last_blank = False
    for line in cleaned:
        if line == "":
            if not last_blank:
                final_lines.append(line)
            last_blank = True
        else:
            final_lines.append(line)
            last_blank = False

    return "\n".join(final_lines).strip() + "\n"
