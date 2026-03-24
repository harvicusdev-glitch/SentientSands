# Sentient Sands - Kenshi AI Mod
# Copyright (C) 2026 Sentient Sands Team
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

from typing import Any, Union

from flask import render_template, send_from_directory
from trade_items import load_item_aliases, normalize_trade_item_name
from save_reader import build_world_index
from personality_rules import (
    ANIMAL_RACES,
    MACHINE_RACES,
    build_loyalty_note,
    generate_npc_traits,
    get_trait_parts,
)
from campaign_chronicle import append_major_event, build_chronicle_block, load_chronicle, save_chronicle
from configuration import (
    CAMPAIGNS_DIR,
    CHARACTERS_DIR as DEFAULT_CHARACTERS_DIR,
    GENERIC_NAMES_PATH,
    KENSHI_MOD_DIR,
    KENSHI_SERVER_DIR,
    LOCALIZATION_PATH,
    MODELS_PATH,
    NAMES_PATH,
    PROVIDERS_PATH,
    TEMPLATES_DIR,
    persist_current_settings,
    get_config_radii,
    load_settings,
    save_settings,
)
import dack
import os
import ctypes
import json
import logging
import subprocess
import signal
import requests
import re
import time
import hashlib
import threading
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request, jsonify
import sys
import logging.handlers
import traceback
import textwrap

# --- PATH DEFINITIONS (Bootstrap only for local imports) ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Explicitly add script dir to path for imports
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

_sge_parse, _sge_compress, _sge_reduce = None, None, None
try:
    from simplify_global_events import (
        extract_raw_events_from_text as _sge_parse,
        simplify_events_to_consolidated_text as _sge_compress,
        extra_token_reduction as _sge_reduce,
    )
    _HAVE_COMPRESSOR = True
except ImportError:
    _HAVE_COMPRESSOR = False
    logging.warning("simplify_global_events.py not found — narrative synthesis will use raw events.")

MODELS_CONFIG = {}
PROVIDERS_CONFIG = {}
NAMES_CONFIG = {}
GENERIC_CONFIG = {}
LOCALIZATION_CONFIG = {}
CURRENT_MODEL_KEY = "player2-default"  # Default
ACTIVE_CAMPAIGN = "Default"      # Default

CHARACTERS_DIR = DEFAULT_CHARACTERS_DIR  # Initial fallback; campaign switches overwrite this
CURRENT_CAMPAIGN = "Default"  # Global track for UI
LAST_GENERATE_TIME = 0  # Track last rumor timestamp
GLOBAL_SYNTHESIS_INTERVAL = 60  # Default minutes

EVENT_HISTORY = []
EVENT_HISTORY_SET = set()  # Parallel set for O(1) dedup lookup
SHOP_STOCK = {}
PROFILES_IN_PROGRESS = set()
PROGRESS_LOCK = threading.Lock()
LIVE_CONTEXTS = {}
LIVE_NAME_INDEX = {}
PLAYER_CONTEXT = {}
CHARACTER_CACHE = {}  # <-- NEW CACHE
CACHE_LOCK = threading.Lock()
LAST_NPC_NAME = None
LAST_NPC_KEY = None
PLAYER2_SESSION_KEY = None
EVENT_THROTTLE = {}
THROTTLE_LOCK = threading.Lock()
LAST_STATE_LOG = {}  # { "NPCName|etype": "last_msg" }
STATE_LOCK = threading.Lock()
AMBIENT_LOCK = threading.Lock()
LAST_DIRECT_CHAT_KEY = None
LAST_DIRECT_CHAT_AT = 0.0
AMBIENT_SPEAKER_LAST_AT = {}
AMBIENT_DIRECT_CHAT_COOLDOWN = 180.0
AMBIENT_SPEAKER_COOLDOWN = 180.0
PRIORITY_LOCK = threading.Lock()
ACTIVE_DIRECT_CHAT_COUNT = 0
CHAT_PRIORITY_UNTIL = 0.0
DEFERRED_PROFILE_QUEUE = {}
DIRECT_CHAT_GRACE_SECONDS = 2.0
SYNTHESIS_STATUS = {"elapsed": 0, "interval": 60}
_RUMORS_CACHE: list = []
_RUMORS_CACHE_MTIME: float = 0.0
_COMPONENT_CACHE: dict = {}   # { full_filepath: (mtime, content) } — avoids repeated template disk reads

# --- CORE GLOBALS & CONFIG PATHS ---
LLM_SESSION = requests.Session()

# --- LORE DATABASE CACHE ---
LORE_DATABASE = []

# Type-based grouping for fetch_dynamic_lore — controls prompt section order,
# headers, and per-type character budgets.
_LORE_TYPE_ORDER = ["global", "race", "faction", "theology", "region"]
_LORE_TYPE_HEADERS = {
    "global": "WORLD CONTEXT",
    "race": "RACE",
    "faction": "FACTION",
    "theology": "RELIGION",
    "region": "REGION",
}
_LORE_TYPE_BUDGETS = {
    "global": 650,   # world overview + commerce — always injected
    "race": 400,   # race biology/psychology — usually 1 chunk
    "faction": 1100,   # major faction + relevant minor factions (2 major chunks ~500 chars each)
    "theology": 400,   # faith/religion context
    "region": 500,   # environmental/location hazards (chunks are 330-450 chars)
}


def initialize_lore_database():
    """Parses the JSON lore file into system memory on server startup."""
    global LORE_DATABASE
    lore_db_path = os.path.join(TEMPLATES_DIR, "World_lore.json")
    try:
        if os.path.exists(lore_db_path):
            # utf-8-sig strips a Windows BOM if present, identical to utf-8 otherwise
            with open(lore_db_path, "r", encoding="utf-8-sig") as f:
                LORE_DATABASE = json.load(f)
            if not isinstance(LORE_DATABASE, list):
                logging.error(
                    f"SYSTEM: {lore_db_path} parsed as {type(LORE_DATABASE).__name__}, expected list. Resetting."
                )
                LORE_DATABASE = []
            else:
                logging.info(f"SYSTEM: Successfully cached {len(LORE_DATABASE)} lore chunks into memory.")
                # Validate each chunk has required fields and a recognized type
                _valid_types = set(_LORE_TYPE_ORDER)
                _required_keys = {"id", "type", "tags", "content"}
                _warnings = 0
                for chunk in LORE_DATABASE:
                    missing = _required_keys - chunk.keys()
                    if missing:
                        logging.warning(f"LORE VALIDATION: chunk '{chunk.get('id', '?')}' missing fields: {missing}")
                        _warnings += 1
                    elif chunk["type"] not in _valid_types:
                        logging.warning(f"LORE VALIDATION: chunk '{chunk['id']}' has unknown type '{chunk['type']}' — will be ignored by fetch_dynamic_lore")
                        _warnings += 1
                if _warnings == 0:
                    logging.info(f"SYSTEM: Lore validation passed — all {len(LORE_DATABASE)} chunks are well-formed.")
                else:
                    logging.warning(f"SYSTEM: Lore validation found {_warnings} issue(s). Check warnings above.")
        else:
            logging.warning(f"SYSTEM: {lore_db_path} not found. LLM will use static fallback text.")
    except Exception as e:
        logging.error(f"SYSTEM: Critical error parsing {lore_db_path}: {e}")
        LORE_DATABASE = []


# --- FACTION METADATA & LORE ENHANCEMENTS ---
FACTION_METADATA = {
    "The Holy Nation": {
        "Leader": "Holy Lord Phoenix LXII",
        "Desc": "A xenophobic, religious group worshipping Okran. They value human purity and despise Skeletons and non-humans."
    },
    "United Cities": {
        "Leader": "Emperor Tengu",
        "Desc": "A vast, corrupt empire where wealth is law. They rely on slavery and the Traders Guild."
    },
    "Shek Kingdom": {
        "Leader": "Esata the Stone Golem",
        "Desc": "A warrior race obsessed with honor and strength, currently attempting to move away from suicidal traditions."
    },
    "Traders Guild": {
        "Leader": "Longen",
        "Desc": "A powerful commercial alliance that controls much of the world's economy through slave labor and trade."
    },
    "Anti-Slavers": {
        "Leader": "Tinfist",
        "Desc": "A group of martial-artist Skeletons and humans dedicated to the total abolition of slavery."
    },
    "Second Empire": {
        "Leader": "Mad Cat-Lon",
        "Desc": "The fallen remains of a once-great robotic empire, now reduced to madness and decay in the Ashlands."
    },
    "Western Hive": {
        "Leader": "The Hive Queen",
        "Desc": "A reclusive insectoid society focused on industrious trade and pheromone-driven loyalty to their Queen."
    },
    "Southern Hive": {
        "Leader": "The Queen of the South",
        "Desc": "A territorial and aggressive Hive variant that views all outsiders as food for their King."
    },
    "Flotsam Ninjas": {
        "Leader": "Moll",
        "Desc": "Fugitive women who escaped the Holy Nation and now wage a guerrilla war against Lord Phoenix."
    },
    "Shinobi Thieves": {
        "Leader": "The Big Boss",
        "Desc": "A global network of spies, smugglers, and fences with safehouses in most major cities."
    },
    "Nameless": {
        "Leader": "The Player",
        "Desc": "A rising group of wanderers who are beginning to make their mark on the world."
    },
    "Deadcat": {
        "Leader": "None (Scattered remnant)",
        "Desc": "Survivors of a once-proud fishing nation, now largely wiped out by Cannibals."
    },
    "Mongrel": {
        "Leader": "None (The High Shack)",
        "Desc": "A haven for outcasts and 'Fog-free' exiles in the heart of the Fog Islands."
    },
    "Red Sabres": {
        "Leader": "Red Sabre Leader",
        "Desc": "Desperate bandits and deserters who raid travelers in the Swamp."
    },
    "Swamp Ninjas": {
        "Leader": "Shade",
        "Desc": "A skilled group of ninja outlaws specializing in swamp combat and drug running."
    }
}


def get_faction_info(faction_name):
    """Returns a formatted string describing the faction and its leader."""
    if not faction_name or faction_name == "Unknown":
        return "Unknown Faction (Remnant or Drifter)"

    # Normalization for Player and various squad names
    clean_name = faction_name
    if "Player" in faction_name or faction_name == "Nameless":
        clean_name = "Nameless"

    meta = FACTION_METADATA.get(clean_name)
    if not meta:
        # Case-insensitive fallback
        for k, v in FACTION_METADATA.items():
            if k.lower() in clean_name.lower() or clean_name.lower() in k.lower():
                meta = v
                break

    if meta:
        leader_part = f" (Led by {meta['Leader']})" if meta.get('Leader') else ""
        return f"{clean_name}{leader_part}: {meta['Desc']}"

    return f"{faction_name}: A minor or specialized group in the wasteland."


def sanitize_llm_text(text):
    if not text:
        return ""
    # Replace common unicode/smart characters that Kenshi's engine might choke on
    replacements = {
        '\u2018': "'", '\u2019': "'",  # Smart single quotes
        '\u201c': '"', '\u201d': '"',  # Smart double quotes
        '\u2013': '-', '\u2014': '-',  # En/Em dashes
        '\u2026': '...',             # Ellipsis
        '\u00a0': ' ',                # Non-breaking space
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    # Standardize line endings
    text = text.replace('\r\n', '\n')
    text = text.replace('\\n', '\n')  # Catch literal escaped newlines
    text = text.replace('\\r', '')    # Catch literal escaped carriage returns
    return text


def robust_json_parse(text):
    """Attempt to parse JSON while handling common LLM formatting errors."""
    if not text:
        return None

    # 1. Basic cleaning
    text = text.strip()

    # 2. Extract content between first { and last }
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1:
        return None

    json_str = text[start:end + 1]

    # 3. Remove trailing commas within arrays/objects using regex
    json_str = re.sub(r',\s*([}\]])', r'\1', json_str)

    # 4. Filter out any single-line comments // or multi-line /* */
    json_str = re.sub(r'//.*?\n', '\n', json_str)
    json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)

    try:
        # strict=False prevents crashes from unescaped LLM newlines
        return json.loads(json_str, strict=False)
    except Exception as eFirst:
        # 5. Attempt: Sanitize unescaped quotes in middle of strings
        try:
            sanitized = re.sub(r'(?<=[a-zA-Z0-9])"(?=[a-zA-Z0-9\s])', "'", json_str)
            return json.loads(sanitized, strict=False)
        except:
            logging.error(f"ROBUST_JSON_PARSE: Final failure on string: {json_str[:200]}...")
            return None


# Setup logging
_log_fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
_log_dir = os.path.join(SCRIPT_DIR, "..", "logs")
if not os.path.exists(_log_dir):
    try:
        os.makedirs(_log_dir)
    except:
        pass

# 1. Main Server Log (Circular/Limited)
_log_file = os.path.join(_log_dir, "server.log")
# 2. Comprehensive Debug Log (Last ~500 entries)
_debug_file = os.path.join(KENSHI_SERVER_DIR, "debug.log")

try:
    # server.log: 512KB limit, 3 backups
    _file_handler = logging.handlers.RotatingFileHandler(_log_file, maxBytes=512 * 1024, backupCount=3, encoding='utf-8')
    _file_handler.setFormatter(_log_fmt)

    _stream_handler = logging.StreamHandler()
    _stream_handler.setFormatter(_log_fmt)

    # debug.log: 1MB limit, 1 backup
    _debug_handler = logging.handlers.RotatingFileHandler(_debug_file, maxBytes=1024 * 1024, backupCount=1, encoding='utf-8')
    _debug_handler.setFormatter(_log_fmt)
    _debug_handler.setLevel(logging.DEBUG)

    # Global config
    logging.basicConfig(level=logging.INFO, handlers=[_stream_handler, _file_handler, _debug_handler])

    # Specialized logger for high-volume telemetry (prompts, raw data)
    # This prevents server.log from becoming a wall of text.
    debug_logger = logging.getLogger('kenshi_debug')
    debug_logger.setLevel(logging.DEBUG)
    debug_logger.addHandler(_debug_handler)
    debug_logger.propagate = False  # Do not double-log to root handlers

except Exception as e:
    # Fallback to stream only if file handler fails
    logging.basicConfig(level=logging.INFO)
    logging.error(f"Failed to initialize file logging: {e}")

# Silence noise
logging.getLogger('werkzeug').setLevel(logging.ERROR)
logging.getLogger('urllib3').setLevel(logging.WARNING)

initialize_lore_database()  # Deferred: logging must be configured first

# Kill any existing process on port 5000 before starting


def kill_old_servers():
    try:
        # Windows specific: find processes on port 5000
        result = subprocess.run(
            ['netstat', '-aon'], capture_output=True, text=True, shell=True
        )
        for line in result.stdout.splitlines():
            if ':5000' in line and 'LISTENING' in line:
                parts = line.strip().split()
                pid = int(parts[-1])
                # Never kill ourselves
                if pid > 0 and pid != os.getpid():
                    logging.info(f"Terminating old server process (PID {pid}) on port 5000...")
                    # Force kill to ensure it's gone
                    subprocess.run(['taskkill', '/F', '/PID', str(pid)],
                                   capture_output=True, shell=True)
                    time.sleep(1)  # Give it a moment to clear the port
    except Exception as e:
        logging.warning(f"Port cleanup diagnostic: {e}")


kill_old_servers()

app = Flask(__name__, template_folder=os.path.join(KENSHI_SERVER_DIR, "templates"))
# JSON_AS_ASCII = True is default, which is safer for our DLL pipe
app.config['JSON_AS_ASCII'] = True


@app.errorhandler(Exception)
def handle_exception(e):
    # Log the full stack trace for any unhandled exception in Flask routes
    logging.error(f"UNHANDLED SERVER EXCEPTION: {str(e)}")
    debug_logger.error(f"UNHANDLED SERVER EXCEPTION STACK:\n{traceback.format_exc()}")
    # Truncate request data if possible for the debug log
    try:
        if request.json:
            debug_logger.debug(f"Offending Request JSON: {json.dumps(request.json, indent=2)}")
    except:
        pass
    return jsonify({"error": str(e), "status": "error"}), 500

# 3. Load Configurations


def load_configs():
    global MODELS_CONFIG, PROVIDERS_CONFIG, NAMES_CONFIG
    logging.debug("Checking configurations...")

    # Create config dir if missing
    config_dir = os.path.join(KENSHI_SERVER_DIR, "config")
    if not os.path.exists(config_dir):
        os.makedirs(config_dir)

    if os.path.exists(MODELS_PATH):
        try:
            with open(MODELS_PATH, "r") as f:
                MODELS_CONFIG = json.load(f)
            logging.debug(f"Loaded {len(MODELS_CONFIG)} models.")
        except Exception as e:
            logging.error(f"Failed to load models.json: {e}")

    if os.path.exists(PROVIDERS_PATH):
        try:
            with open(PROVIDERS_PATH, "r") as f:
                PROVIDERS_CONFIG = json.load(f)
            logging.debug(f"Loaded {len(PROVIDERS_CONFIG)} providers.")
        except Exception as e:
            logging.error(f"Failed to load providers.json: {e}")

    load_item_aliases(os.path.join(KENSHI_SERVER_DIR, "config", "item_aliases.json"))

    if os.path.exists(NAMES_PATH):
        try:
            with open(NAMES_PATH, "r") as f:
                NAMES_CONFIG = json.load(f)
            logging.debug(f"Loaded {len(NAMES_CONFIG)} gender pools from names.json.")
        except Exception as e:
            logging.error(f"Failed to load names.json: {e}")

    if os.path.exists(GENERIC_NAMES_PATH):
        try:
            global GENERIC_CONFIG
            with open(GENERIC_NAMES_PATH, "r") as f:
                GENERIC_CONFIG = json.load(f)
            logging.debug(f"Loaded {len(GENERIC_CONFIG.get('prefixes', []))} generic prefixes from generic_names.json.")
        except Exception as e:
            logging.error(f"Failed to load generic_names.json: {e}")

    global LOCALIZATION_CONFIG
    LOCALIZATION_CONFIG = {}
    if os.path.exists(LOCALIZATION_PATH):
        try:
            with open(LOCALIZATION_PATH, "r", encoding="utf-8") as f:
                LOCALIZATION_CONFIG = json.load(f)
            logging.debug(f"Loaded {len(LOCALIZATION_CONFIG)} language localizations.")
        except Exception as e:
            logging.error(f"Failed to load localization.json: {e}")


# Event History Persistence
GLOBAL_EVENT_COUNTER = 0

# --- CAMPAIGN MANAGEMENT ---


def get_campaign_dir():
    if not os.path.exists(CAMPAIGNS_DIR):
        os.makedirs(CAMPAIGNS_DIR)
        logging.info(f"Created base campaigns directory: {CAMPAIGNS_DIR}")

    cdir = os.path.join(CAMPAIGNS_DIR, ACTIVE_CAMPAIGN)
    if not os.path.exists(cdir):
        os.makedirs(cdir)
        logging.info(f"Created campaign directory: {cdir}")
        # Automatically seed new campaigns created during startup/init
        ensure_campaign_seeded(cdir)
    return cdir


def ensure_campaign_seeded(cdir):
    """Populates a campaign directory with default templates and folders."""
    try:
        if not os.path.exists(os.path.join(cdir, "characters")):
            os.makedirs(os.path.join(cdir, "characters"))

        # Copy essential personal files to campaigns by default.
        # All other templates (rules, lore, etc.) remain global in TEMPLATES_DIR.
        for component in ["character_bio.txt", "player_faction_description.txt"]:
            src = os.path.join(TEMPLATES_DIR, component)
            dst = os.path.join(cdir, component)
            if os.path.exists(src) and not os.path.exists(dst):
                import shutil
                shutil.copy2(src, dst)
                logging.info(f"CAMPAIGN: Seeded '{os.path.basename(cdir)}' with {component}")

        # Ensure world_events.txt exists (Campaign-Specific History)
        ev_path = os.path.join(cdir, "world_events.txt")
        if not os.path.exists(ev_path):
            with open(ev_path, "w", encoding="utf-8") as f:
                f.write("# Dynamic rumors generated for this campaign\n")

        # Ensure campaign_chronicle.json exists (Persistent Major Events)
        chronicle_path = os.path.join(cdir, "campaign_chronicle.json")
        if not os.path.exists(chronicle_path):
            with open(chronicle_path, "w", encoding="utf-8") as f:
                json.dump([], f)
            logging.info(f"CAMPAIGN: Seeded '{os.path.basename(cdir)}' with campaign_chronicle.json")
    except Exception as e:
        logging.error(f"Failed to seed campaign directory {cdir}: {e}")


def migrate_to_campaigns():
    """Moves legacy data to campaigns/Default if not already migrated."""
    try:
        if not os.path.exists(CAMPAIGNS_DIR):
            os.makedirs(CAMPAIGNS_DIR)

        default_dir = os.path.join(CAMPAIGNS_DIR, "Default")
        is_new_default = not os.path.exists(default_dir)

        if is_new_default:
            os.makedirs(default_dir)
            logging.info("MIGRATION: Created Default campaign folder")

        import shutil
        # 1. Characters
        old_chars = os.path.join(KENSHI_SERVER_DIR, "characters")
        new_chars = os.path.join(default_dir, "characters")
        if os.path.exists(old_chars) and not os.path.exists(new_chars):
            try:
                shutil.move(old_chars, new_chars)
                logging.info("MIGRATION: Moved legacy characters to campaigns/Default")
            except Exception as e:
                logging.error(f"MIGRATION ERROR (Characters): {e}")

        # 2. Registry
        old_reg = os.path.join(KENSHI_MOD_DIR, "kenshi_ai_registry")
        if not os.path.exists(old_reg):
            old_reg = os.path.join(KENSHI_MOD_DIR, "sentient_sands_registry")

        new_reg = os.path.join(default_dir, "sentient_sands_registry")
        if os.path.exists(old_reg) and not os.path.exists(new_reg):
            try:
                shutil.move(old_reg, new_reg)
                logging.info("MIGRATION: Moved legacy registry to campaigns/Default")
            except Exception as e:
                logging.error(f"MIGRATION ERROR (Registry): {e}")

        # 3. World Events / Rumors
        old_events = os.path.join(KENSHI_SERVER_DIR, "world_events.txt")
        new_events = os.path.join(default_dir, "world_events.txt")
        if os.path.exists(old_events) and not os.path.exists(new_events):
            try:
                shutil.move(old_events, new_events)
                logging.info("MIGRATION: Moved legacy world_events.txt to campaigns/Default")
            except Exception as e:
                logging.error(f"MIGRATION ERROR (World Events): {e}")

        # 4. Global Event History
        old_hist = os.path.join(KENSHI_SERVER_DIR, "event_history.json")
        new_hist = os.path.join(default_dir, "event_history.json")
        if os.path.exists(old_hist) and not os.path.exists(new_hist):
            try:
                shutil.move(old_hist, new_hist)
                logging.info("MIGRATION: Moved legacy event_history.json to campaigns/Default")
            except Exception as e:
                logging.error(f"MIGRATION ERROR (History): {e}")

        # Ensure templates exist in Default (always check this during migration)
        ensure_campaign_seeded(default_dir)

    except Exception as e:
        logging.error(f"MIGRATION: Critical failure in migration logic: {e}")


def load_campaign_config():
    """Initializes paths based on the active campaign."""
    global CHARACTERS_DIR, EVENT_HISTORY, EVENT_HISTORY_SET, SHOP_STOCK
    try:
        cdir = get_campaign_dir()

        # 1. Update Directories
        CHARACTERS_DIR = os.path.join(cdir, "characters")
        if not os.path.exists(CHARACTERS_DIR):
            os.makedirs(CHARACTERS_DIR)

        # 2. Load Persisted Event History
        hist_path = os.path.join(cdir, "event_history.json")
        if os.path.exists(hist_path):
            try:
                with open(hist_path, "r", encoding="utf-8") as f:
                    EVENT_HISTORY = json.load(f)
                EVENT_HISTORY_SET = set(EVENT_HISTORY)
                logging.info(f"CAMPAIGN: Loaded {len(EVENT_HISTORY)} events for '{ACTIVE_CAMPAIGN}'")
            except Exception as e:
                logging.error(f"Failed to load event history: {e}")
                EVENT_HISTORY = []
                EVENT_HISTORY_SET = set()
        else:
            EVENT_HISTORY = []
            EVENT_HISTORY_SET = set()

        # 3. Load Shop Stock cache
        shop_stock_path = os.path.join(cdir, "shop_stock.json")
        if os.path.exists(shop_stock_path):
            try:
                with open(shop_stock_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    SHOP_STOCK = {k: v for k, v in raw.items() if not k.startswith("_")}
                logging.info(f"CAMPAIGN: Loaded shop stock for {len(SHOP_STOCK)} NPCs")
            except Exception as e:
                logging.error(f"Failed to load shop_stock.json: {e}")
                SHOP_STOCK = {}
        else:
            SHOP_STOCK = {}

        # 4. Push generic names to DLL
        push_generic_names_to_dll()
    except Exception as e:
        logging.error(f"CAMPAIGN: Critical failure loading config: {e}")


def send_to_pipe(cmd):
    """
    Robust pipe transmission. Prepends CMD: if not already present.
    """
    if not (cmd.startswith("CMD:") or cmd.startswith("NPC_") or cmd.startswith("PLAYER_") or cmd.startswith("SHOW_HISTORY") or cmd.startswith("NOTIFY:")):
        cmd = "CMD: " + cmd

    try:
        with open(r'\\.\pipe\SentientSands', 'wb') as f:
            f.write(cmd.encode('utf-8'))
    except:
        pass


def push_generic_names_to_dll():
    """Syncs generic name lists to the C++ renamer via pipe."""
    try:
        prefixes = GENERIC_CONFIG.get("prefixes", [])
        keywords = GENERIC_CONFIG.get("keywords", [])
        p_str = ",".join(prefixes)
        k_str = ",".join(keywords)
        send_to_pipe(f"POPULATE_GENERIC: {p_str}|{k_str}")
        logging.info("PIPE: Synced generic name lists to DLL")
    except Exception as e:
        logging.error(f"Failed to sync generic names to DLL: {e}")


def save_campaign_history():
    try:
        cdir = get_campaign_dir()
        hist_path = os.path.join(cdir, "event_history.json")
        with open(hist_path, "w", encoding="utf-8") as f:
            json.dump(EVENT_HISTORY, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Failed to save event history: {e}")


def is_npc_name_generic(name):
    """Centralized check for generic NPC names to ensure they get unique identities."""
    if not name:
        return True

    # Strip serial IDs (Name|12345)
    clean_name = str(name).split('|')[0].strip()

    # Check against hardcoded fallback list (GENERIC_NAMES)
    if clean_name in GENERIC_NAMES:
        return True

    # Check against loaded generic_names.json config
    prefixes = GENERIC_CONFIG.get("prefixes", [])
    keywords = GENERIC_CONFIG.get("keywords", [])

    # Exact or substring matches for prefixes (case-insensitive)
    lower_clean = clean_name.lower()
    if any(p.lower() in lower_clean for p in prefixes):
        return True

    # Keyword substring matches
    if any(k.lower() in lower_clean for k in keywords):
        return True

    # Default keywords if config failed to load
    if not keywords:
        default_keywords = [
            "Bandit", "Guard", "Citizen", "Soldier", "Warrior", "Heavy", "Captain",
            "Sentinel", "Servant", "Wanderer", "Peasant", "Settler", "Thug", "Barman", "Pacifier"
        ]
        if any(k.lower() in lower_clean for k in default_keywords):
            return True

    return False


GENERIC_NAMES = [
    "Hungry Bandit", "Dust Bandit", "Starving Vagrant", "Drifter", "Samurai",
    "Holy Sentinel", "Holy Servant", "Swamper", "Tech Hunter", "Mercenary",
    "Shop Guard", "Caravan Guard", "Slave Hunter", "Slaver", "Manhunter",
    "Escaped Slave", "Rebirth Slave", "United Cities Citizen", "Holy Nation Citizen",
    "Shek Warrior", "Hive Worker", "Hive Soldier", "Hive Prince", "Fogman",
    "Barman", "Pacifier", "Bar Thug",
    "Cannibal", "Outlaw", "Farmer", "Nomad", "Trader", "Gate Guard",
    "Unknown Entity", "Someone", "Mercenary Heavy", "Mercenary Captain",
    "Holy Nation Outlaw", "Holy Nation Peasant", "United Cities Peasant",
    "Wandering Assassin", "Trader Guard", "Hiver Ronin", "Skeleton Legion",
    "Reaver", "Grass Pirate", "Black Dog", "Crab Raider", "Skeleton Bandit"
]

KENSHI_NAME_POOL = [
    "Kaelen", "Korg", "Vayn", "Sark", "Mina", "Rook", "Drake", "Silas", "Tane", "Kuna",
    "Zarek", "Jorn", "Lyra", "Kael", "Brena", "Torin", "Sola", "Fen", "Krax", "Vora",
    "Dax", "Nyx", "Garek", "Sora", "Thane", "Kira", "Zane", "Lara", "Marek", "Vina",
    "Rel", "Kaan", "Siv", "Tork", "Meda", "Grox", "Vael", "Syra", "Keld", "Bara",
    "Dorn", "Neld", "Gora", "Skarn", "Vane", "Kura", "Zora", "Lena", "Morn", "Vela",
    "Rael", "Kona", "Sima", "Teld", "Mora", "Grak", "Veld", "Sura", "Karn", "Bena",
    "Drak", "Nala", "Gord", "Sina", "Vara", "Kela", "Zana", "Lina", "Mela", "Vorna",
    "Hark", "Skal", "Vorn", "Grek", "Myla", "Rion", "Daka", "Sith", "Tyla", "Korr",
    "Zent", "Lyr", "Brax", "Vort", "Nara", "Grel", "Syk", "Tarn", "Moko", "Vull",
    "Kess", "Tory", "Vann", "Sael", "Miro", "Lorn", "Gryf", "Dael", "Seld", "Kurv"
]


def get_used_names():
    if not os.path.exists(CHARACTERS_DIR):
        return set()
    names = set()
    for f in os.listdir(CHARACTERS_DIR):
        if not f.endswith(".cfg"):
            continue
        fpath = os.path.join(CHARACTERS_DIR, f)
        try:
            cdata = dack.load(fpath)
            name = str(cdata.get("Name", "")).strip()
            if name:
                names.add(name.lower())
        except Exception:
            # A broken file has no reliable name; skip it rather than polluting the used-name set.
            logging.warning(f"USED_NAMES: Skipping unreadable character file {f}")
    return names


def generate_unique_lore_name(gender="Neutral"):
    used = get_used_names()

    gender_key = "Neutral"
    if gender.lower() == "male":
        gender_key = "Male"
    elif gender.lower() == "female":
        gender_key = "Female"

    # 2. Get pool
    pool = NAMES_CONFIG.get(gender_key, [])
    if not pool and gender_key != "Neutral":
        pool = NAMES_CONFIG.get("Neutral", [])

    if not pool:
        pool = KENSHI_NAME_POOL

    # 3. Select unique
    available = [n for n in pool if n.lower() not in used]
    if not available:
        base = random.choice(pool if pool else KENSHI_NAME_POOL)
        for i in range(1, 1000):
            candidate = f"{base} {i}"
            if candidate.lower() not in used:
                return candidate
        return f"{base}_{random.randint(1000, 9999)}"

    return random.choice(available)


def get_current_time_prefix():
    if PLAYER_CONTEXT:
        day = PLAYER_CONTEXT.get('day', 0)
        hour = int(PLAYER_CONTEXT.get('hour', 0))
        minute = int(PLAYER_CONTEXT.get('minute', 0))
        return f"[Day {day}, {hour:02d}:{minute:02d}] "
    return ""


def generate_relation_bar(rel):
    """Generates a text-based visual representation of the NPC's relation to the player."""
    try:
        rel = int(rel)
    except:
        rel = 0

    # Scale: -100 to 100
    # Normalize -100..100 to 0..20 dashes
    pos = int((rel + 100) / 10)
    pos = max(0, min(20, pos))

    bar = list("---------------------")
    bar[pos] = "X"  # Marker
    bar_str = "".join(bar)

    # Status Label
    label = "NEUTRAL"
    if rel <= -90:
        label = "ARCH-ENEMY"
    elif rel <= -60:
        label = "HOSTILE"
    elif rel <= -25:
        label = "UNFRIENDLY"
    elif rel >= 90:
        label = "SOUL-MATE"
    elif rel >= 60:
        label = "ALLIED"
    elif rel >= 25:
        label = "FRIENDLY"

    # Add color tags for MyGUI (if supported, using # prefix)
    # Actually, let's keep it plain text for max compatibility across UI versions
    return f"RELATION: [{label}] [{bar_str}] ({rel:+} pts)"


def is_future_timestamp(line, cur_d, cur_h, cur_m):
    """Checks if a string containing [Day X, HH:MM] is ahead of the provided current time."""
    match = re.search(r"\[Day (\d+)(?:, (\d+):(\d+))?\]", line)
    if not match:
        return False
    d = int(match.group(1))
    h = int(match.group(2)) if match.group(2) else 0
    m = int(match.group(3)) if match.group(3) else 0
    if d > cur_d:
        return True
    if d < cur_d:
        return False
    if h > cur_h:
        return True
    if h < cur_h:
        return False
    return m > cur_m


# Mappings for Kenshi enums
SHORT_TERM_MEM = {
    1: "INTRUDER", 2: "AGGRESSOR", 3: "TEMPORARY_ALLY", 4: "TEMPORARY_ENEMY",
    5: "PRISONER", 6: "HAS_BEEN_LOOTED", 7: "CRIMINAL"
}
LONG_TERM_MEM = {
    1: "MY_INTRUDER", 2: "MY_LIFESAVER", 3: "FREED_ME", 4: "STOLE_FROM_ME",
    5: "MY_CAPTOR", 6: "FRIENDLY_AQUAINTANCE", 7: "DEFEATED_MY_SQUAD_ONCE",
    8: "SQUAD_LOST_TO_ME_ONCE", 14: "KILLED_MY_FRIEND", 15: "I_SCREWED_THIS_GUY"
}


def _clean_npc_name(name):
    if name is None:
        return ""
    clean = str(name).strip()
    if '|' in clean:
        clean = clean.split('|', 1)[0].strip()
    return clean


def _build_name_faction_id(name, faction=None):
    clean = _clean_npc_name(name)
    f = (faction or "").strip()
    if f and f not in ("Unknown", "None", "No Faction", ""):
        f_slug = re.sub(r'\s+', '_', re.sub(r'[^\w\s-]', '', f).strip())
        if f_slug:
            return f"{clean}_{f_slug}"
    return clean


def _is_strong_uid(value):
    """Identify stable, unique IDs vs generic/volatile ones."""
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    lower = text.lower()
    if lower.startswith("hand_"):
        return False
    if text.isdigit():
        return False
    # New DLL builds expose persistent handles as 5 numeric parts joined by hyphens,
    # e.g. "1-304443360-1-2050292992-1".
    if re.fullmatch(r"\d+(?:-\d+){4}", text):
        return True

    # Fallbacks
    return ("-" in text and len(text.split("-")) >= 3) or (text.count('-') == 4 and all(part.isdigit() for part in text.split('-')))


def _preferred_storage_id(name="", faction=None, *candidates, uid=None):
    clean_name = _clean_npc_name(name)
    derived = _build_name_faction_id(clean_name, faction) if clean_name else ""

    if _is_strong_uid(uid):
        return str(uid).strip()

    for candidate in candidates:
        if candidate is None:
            continue
        sid = str(candidate).strip()
        if not sid:
            continue
        # Current DLL builds often send storage_id=name. If we also know faction,
        # prefer the stronger derived name+faction ID instead of the weak alias.
        if clean_name and sid == clean_name and derived and derived != sid:
            continue
        return sid

    return derived


def _normalize_context_identity(context, fallback_name=""):
    if not isinstance(context, dict):
        return {}

    normalized = dict(context)
    clean_name = _clean_npc_name(normalized.get("name") or normalized.get("Name") or fallback_name)
    faction = (
        normalized.get("faction")
        or normalized.get("Faction")
        or normalized.get("origin_faction")
        or normalized.get("OriginFaction")
        or normalized.get("factionID")
        or ""
    ).strip()
    persistent_id = str(
        normalized.get("persistent_id")
        or normalized.get("PersistentID")
        or ""
    ).strip() or None
    runtime_id = str(
        normalized.get("runtime_id")
        or normalized.get("id")
        or ""
    ).strip() or None
    storage_id = _preferred_storage_id(
        clean_name,
        faction,
        normalized.get("storage_id"),
        normalized.get("ID"),
        uid=persistent_id,
    )
    if runtime_id:
        normalized["runtime_id"] = runtime_id
    if persistent_id:
        normalized["persistent_id"] = persistent_id
    if storage_id:
        normalized["storage_id"] = storage_id
    return normalized


def _normalized_faction_key(faction):
    if not faction:
        return ""
    text = str(faction).strip()
    if not text:
        return ""
    lower = text.lower()
    if lower.startswith("player's squad"):
        parts = text.split(":", 1)
        text = parts[1].strip() if len(parts) == 2 else text[len("player's squad"):].strip()
    return re.sub(r'\s+', ' ', text).strip().lower()


def _context_identity_summary(context, fallback_name=""):
    ctx = _parse_context_dict(context, fallback_name=fallback_name)
    if not ctx:
        return {}

    clean_name = _context_name(ctx, fallback_name)
    faction = _context_faction(ctx)
    runtime_id = str(ctx.get("runtime_id") or ctx.get("id") or "").strip() or None
    persistent_id = str(ctx.get("persistent_id") or "").strip() or None
    storage_id = str(ctx.get("storage_id") or ctx.get("ID") or "").strip() or None
    key = runtime_id or (persistent_id if _is_strong_uid(persistent_id) else None) or storage_id or clean_name

    try:
        dist = float(ctx.get("dist", ctx.get("player_dist", 9999.0)) or 9999.0)
    except Exception:
        dist = 9999.0

    strength = 0
    if clean_name:
        strength = 1
    if storage_id and storage_id != clean_name:
        strength = 2
    if runtime_id:
        strength = 3
    if _is_strong_uid(persistent_id):
        strength = 4

    return {
        "name": clean_name,
        "faction": faction,
        "runtime_id": runtime_id,
        "persistent_id": persistent_id,
        "storage_id": storage_id,
        "key": key,
        "dist": dist,
        "strength": strength,
        "context": ctx,
    }


def _collect_target_candidates(clean_name, context=None, nearby_data=None):
    candidates = []
    seen = set()

    def _add_candidate(source, payload):
        summary = _context_identity_summary(payload, fallback_name=clean_name)
        if not summary or not summary.get("name"):
            return
        if clean_name and summary["name"] != clean_name:
            return

        key = summary.get("key") or summary["name"]
        if key in seen:
            return
        seen.add(key)
        summary["source"] = source
        candidates.append(summary)

    if context:
        _add_candidate("context", context)

    for npc in nearby_data or []:
        _add_candidate("nearby", npc)

    if clean_name:
        for live_key in [k for k in LIVE_NAME_INDEX.get(clean_name, []) if k in LIVE_CONTEXTS]:
            _add_candidate("live", LIVE_CONTEXTS[live_key])

    return candidates


def resolve_primary_target(raw_name, context=None, nearby_data=None, mode="talk"):
    clean_name = _clean_npc_name(raw_name)
    explicit_runtime_id = str(raw_name).split('|', 1)[1].strip() if '|' in str(raw_name) else None
    context_summary = _context_identity_summary(context, fallback_name=clean_name)
    candidates = _collect_target_candidates(clean_name, context=context, nearby_data=nearby_data)

    def _finish(chosen, reason):
        if not chosen:
            return clean_name, context, explicit_runtime_id, None
        chosen_name = chosen.get("name") or clean_name
        chosen_ctx = chosen.get("context") or {}
        # Direct targeting should stay runtime-first; storage identity is for persistence.
        chosen_id = chosen.get("runtime_id") or chosen.get("storage_id")
        runtime_ref = f"{chosen_name}|{chosen.get('runtime_id')}" if chosen.get("runtime_id") else chosen_name
        logging.info(
            f"TARGET: Resolved '{clean_name or raw_name}' -> {chosen_name} "
            f"(key={chosen.get('key')}, source={chosen.get('source', 'fallback')}, reason={reason})"
        )
        return chosen_name, json.dumps(chosen_ctx), chosen_id, runtime_ref

    if explicit_runtime_id:
        for candidate in candidates:
            if explicit_runtime_id in (
                str(candidate.get("runtime_id") or ""),
                str(candidate.get("storage_id") or ""),
                str(candidate.get("key") or ""),
            ):
                return _finish(candidate, "explicit_runtime_id")

    if len(candidates) == 1:
        return _finish(candidates[0], "unique_candidate")

    if context_summary and context_summary.get("strength", 0) >= 2:
        for candidate in candidates:
            if candidate.get("key") == context_summary.get("key"):
                return _finish(candidate, "strong_context")

    if LAST_DIRECT_CHAT_KEY:
        recent_matches = [
            candidate for candidate in candidates
            if LAST_DIRECT_CHAT_KEY in (
                str(candidate.get("key") or ""),
                str(candidate.get("storage_id") or ""),
                str(candidate.get("runtime_id") or ""),
            )
        ]
        if len(recent_matches) == 1:
            return _finish(recent_matches[0], "recent_direct_chat")

    player_faction = _normalized_faction_key(PLAYER_CONTEXT.get("faction"))
    if player_faction and mode in ("talk", "yell") and (not context_summary or context_summary.get("strength", 0) < 2):
        faction_matches = [
            candidate for candidate in candidates
            if _normalized_faction_key(candidate.get("faction")) == player_faction
        ]
        if len(faction_matches) == 1:
            return _finish(faction_matches[0], "player_faction")

    if len(candidates) > 1 and (not context_summary or context_summary.get("strength", 0) < 2):
        by_distance = sorted(candidates, key=lambda item: (item.get("dist", 9999.0), item.get("source") != "nearby"))
        if len(by_distance) == 1 or by_distance[0].get("dist", 9999.0) + 1.0 < by_distance[1].get("dist", 9999.0):
            return _finish(by_distance[0], "nearest_candidate")

    if context_summary:
        return _finish(context_summary, "context_fallback")

    if candidates:
        logging.warning(
            f"TARGET: Ambiguous target '{clean_name}'. "
            f"Candidates={[c.get('key') for c in candidates]}. Falling back to first candidate."
        )
        return _finish(candidates[0], "ambiguous_first")

    return clean_name, context, explicit_runtime_id, clean_name


def _parse_context_dict(context, fallback_name=""):
    if not context:
        return {}
    if isinstance(context, dict):
        return _normalize_context_identity(context, fallback_name=fallback_name)
    if isinstance(context, str) and context.strip().startswith('{'):
        try:
            parsed = json.loads(context)
            if isinstance(parsed, dict):
                return _normalize_context_identity(parsed, fallback_name=fallback_name)
        except Exception:
            return {}
    return {}


def _context_name(context, fallback_name=""):
    if not isinstance(context, dict):
        context = {}
    return _clean_npc_name(context.get("name") or context.get("Name") or fallback_name)


def _context_faction(context):
    if not isinstance(context, dict):
        context = {}
    return (
        context.get("faction")
        or context.get("Faction")
        or context.get("origin_faction")
        or context.get("OriginFaction")
        or context.get("factionID")
        or ""
    ).strip()


def _register_live_name(key, name):
    if not key or not name:
        return
    bucket = LIVE_NAME_INDEX.setdefault(name, [])
    if key not in bucket:
        bucket.append(key)


def _unregister_live_aliases(key, ctx=None):
    target = ctx or LIVE_CONTEXTS.get(key) or {}
    for alias in target.get("_aliases", []):
        bucket = LIVE_NAME_INDEX.get(alias)
        if not bucket:
            continue
        LIVE_NAME_INDEX[alias] = [candidate for candidate in bucket if candidate != key]
        if not LIVE_NAME_INDEX[alias]:
            del LIVE_NAME_INDEX[alias]


def resolve_live_context(name="", context=None, explicit_id=None):
    ctx_dict = _parse_context_dict(context, fallback_name=name)
    clean_name = _context_name(ctx_dict, name)
    faction = _context_faction(ctx_dict)

    candidates = []
    for candidate in (
        ctx_dict.get("runtime_id"),
        ctx_dict.get("id"),
        ctx_dict.get("persistent_id") if _is_strong_uid(ctx_dict.get("persistent_id")) else None,
        ctx_dict.get("storage_id"),
        ctx_dict.get("ID"),
        explicit_id,
        _build_name_faction_id(clean_name, faction) if clean_name else None,
        clean_name,
    ):
        if candidate:
            candidate = str(candidate)
            if candidate not in candidates:
                candidates.append(candidate)

    for candidate in candidates:
        if candidate in LIVE_CONTEXTS:
            return candidate, LIVE_CONTEXTS[candidate]

    if clean_name:
        live_keys = [k for k in LIVE_NAME_INDEX.get(clean_name, []) if k in LIVE_CONTEXTS]
        unique_keys = list(dict.fromkeys(live_keys))
        if len(unique_keys) == 1:
            unique_key = unique_keys[0]
            return unique_key, LIVE_CONTEXTS[unique_key]
        if len(unique_keys) > 1:
            logging.debug(f"LIVE_CONTEXTS: Ambiguous name lookup for '{clean_name}' ({unique_keys})")
            return None, None

    return None, None


def store_live_context(context, name="", explicit_id=None):
    global LAST_NPC_KEY, LAST_NPC_NAME

    ctx_dict = _parse_context_dict(context, fallback_name=name)
    if not isinstance(ctx_dict, dict):
        return None, {}

    clean_name = _context_name(ctx_dict, name)
    faction = _context_faction(ctx_dict)
    derived_storage_id = _build_name_faction_id(clean_name, faction) if clean_name else ""
    runtime_id = str(ctx_dict.get("runtime_id") or ctx_dict.get("id") or "").strip() or None
    persistent_id = str(ctx_dict.get("persistent_id") or "").strip() or None
    storage_id = _preferred_storage_id(
        clean_name,
        faction,
        ctx_dict.get("storage_id"),
        ctx_dict.get("ID"),
        explicit_id if explicit_id and not re.fullmatch(r"-?\d+", str(explicit_id)) else None,
        uid=persistent_id,
    )
    key = str(runtime_id or explicit_id or clean_name or "")
    if not key:
        return None, {}

    existing_key, existing = resolve_live_context(name=clean_name, context=ctx_dict, explicit_id=explicit_id)
    merged = dict(existing or {})
    merged.update(ctx_dict)

    if clean_name:
        merged["name"] = clean_name
    if runtime_id:
        merged["runtime_id"] = runtime_id
        merged["id"] = runtime_id
    elif explicit_id and not merged.get("id"):
        merged["id"] = explicit_id
    if _is_strong_uid(persistent_id):
        merged["persistent_id"] = persistent_id
    if storage_id:
        merged["storage_id"] = storage_id
    elif derived_storage_id:
        merged["storage_id"] = derived_storage_id

    merged["_aliases"] = [clean_name] if clean_name else []

    if existing_key and existing_key != key:
        _unregister_live_aliases(existing_key, existing)
        LIVE_CONTEXTS.pop(existing_key, None)

    LIVE_CONTEXTS.pop(key, None)
    LIVE_CONTEXTS[key] = merged
    _register_live_name(key, clean_name)
    # Evict oldest entry when cache exceeds cap (prevents unbounded growth in long sessions)
    if len(LIVE_CONTEXTS) > 300:
        oldest_key = next(iter(LIVE_CONTEXTS))
        _unregister_live_aliases(oldest_key, LIVE_CONTEXTS.pop(oldest_key))

    LAST_NPC_KEY = key
    LAST_NPC_NAME = clean_name or key
    return key, merged


def clear_live_context_cache():
    global LAST_NPC_KEY, LAST_NPC_NAME, LAST_DIRECT_CHAT_KEY, LAST_DIRECT_CHAT_AT
    global ACTIVE_DIRECT_CHAT_COUNT, CHAT_PRIORITY_UNTIL
    LIVE_CONTEXTS.clear()
    LIVE_NAME_INDEX.clear()
    LAST_NPC_KEY = None
    LAST_NPC_NAME = None
    LAST_DIRECT_CHAT_KEY = None
    LAST_DIRECT_CHAT_AT = 0.0
    with AMBIENT_LOCK:
        AMBIENT_SPEAKER_LAST_AT.clear()
    with PROGRESS_LOCK:
        PROFILES_IN_PROGRESS.clear()
    with PRIORITY_LOCK:
        ACTIVE_DIRECT_CHAT_COUNT = 0
        CHAT_PRIORITY_UNTIL = 0.0
        DEFERRED_PROFILE_QUEUE.clear()


def _ambient_identity_key(name=None, context=None, explicit_id=None):
    clean_name = _clean_npc_name(name)
    key, _ = resolve_live_context(name=clean_name, context=context, explicit_id=explicit_id)
    if key:
        return key
    if explicit_id and clean_name:
        return f"{clean_name}|{explicit_id}"
    return clean_name


def mark_recent_direct_chat(name, context=None, explicit_id=None):
    global LAST_DIRECT_CHAT_KEY, LAST_DIRECT_CHAT_AT
    key = _ambient_identity_key(name=name, context=context, explicit_id=explicit_id)
    if not key:
        return
    with AMBIENT_LOCK:
        LAST_DIRECT_CHAT_KEY = key
        LAST_DIRECT_CHAT_AT = time.time()


def ambient_candidate_allowed(name=None, context=None, explicit_id=None):
    key = _ambient_identity_key(name=name, context=context, explicit_id=explicit_id)
    if not key:
        return False

    now = time.time()
    with AMBIENT_LOCK:
        if LAST_DIRECT_CHAT_KEY == key and (now - LAST_DIRECT_CHAT_AT) < AMBIENT_DIRECT_CHAT_COOLDOWN:
            return False

        last_spoke = AMBIENT_SPEAKER_LAST_AT.get(key, 0.0)
        if (now - last_spoke) < AMBIENT_SPEAKER_COOLDOWN:
            return False

    return True


def mark_ambient_speakers(names):
    now = time.time()
    with AMBIENT_LOCK:
        for speaker in names:
            if isinstance(speaker, dict):
                key = _ambient_identity_key(
                    name=speaker.get("name"),
                    context=speaker,
                    explicit_id=(
                        speaker.get("persistent_id")
                        or speaker.get("runtime_id")
                        or speaker.get("storage_id")
                        or speaker.get("id")
                    ),
                )
            elif isinstance(speaker, (tuple, list)):
                name = speaker[0] if len(speaker) > 0 else None
                explicit_id = speaker[1] if len(speaker) > 1 else None
                context = speaker[2] if len(speaker) > 2 else None
                key = _ambient_identity_key(name=name, context=context, explicit_id=explicit_id)
            else:
                key = _ambient_identity_key(name=speaker)

            if key:
                AMBIENT_SPEAKER_LAST_AT[key] = now


def begin_direct_chat():
    global ACTIVE_DIRECT_CHAT_COUNT, CHAT_PRIORITY_UNTIL
    with PRIORITY_LOCK:
        ACTIVE_DIRECT_CHAT_COUNT += 1
        CHAT_PRIORITY_UNTIL = time.time() + DIRECT_CHAT_GRACE_SECONDS


def end_direct_chat():
    global ACTIVE_DIRECT_CHAT_COUNT, CHAT_PRIORITY_UNTIL
    with PRIORITY_LOCK:
        if ACTIVE_DIRECT_CHAT_COUNT > 0:
            ACTIVE_DIRECT_CHAT_COUNT -= 1
        CHAT_PRIORITY_UNTIL = time.time() + DIRECT_CHAT_GRACE_SECONDS


def direct_chat_active():
    with PRIORITY_LOCK:
        return ACTIVE_DIRECT_CHAT_COUNT > 0 or time.time() < CHAT_PRIORITY_UNTIL


def defer_profile_batch(npc_list):
    if not npc_list:
        return 0
    with PRIORITY_LOCK:
        for npc in npc_list:
            sid = npc.get("storage_id")
            if sid:
                DEFERRED_PROFILE_QUEUE[sid] = dict(npc)
        return len(DEFERRED_PROFILE_QUEUE)


def drain_deferred_profile_queue():
    with PRIORITY_LOCK:
        if not DEFERRED_PROFILE_QUEUE:
            return []
        queued = list(DEFERRED_PROFILE_QUEUE.values())
        DEFERRED_PROFILE_QUEUE.clear()
        return queued


def _launch_batch_profile_generation(batch):
    if not batch:
        return 0

    def _bg_generate(items):
        try:
            generate_batch_profiles(items)
        finally:
            with PROGRESS_LOCK:
                for ctx in items:
                    sid = ctx.get("storage_id")
                    if sid in PROFILES_IN_PROGRESS:
                        PROFILES_IN_PROGRESS.remove(sid)

    threading.Thread(target=_bg_generate, args=(batch,), daemon=True).start()
    return len(batch)


def flush_deferred_profile_batches():
    if direct_chat_active():
        return 0
    return _launch_batch_profile_generation(drain_deferred_profile_queue())


class _DirectChatLease:
    """Small route-scope guard so direct chat priority is always released on return/exception."""

    def __init__(self):
        self.active = False

    def begin(self):
        if not self.active:
            begin_direct_chat()
            self.active = True

    def release(self):
        if self.active:
            end_direct_chat()
            self.active = False

    def __del__(self):
        try:
            self.release()
        except Exception:
            pass


def build_detailed_context_string(npc_name, char_data=None, live_ctx=None):
    # Try to get live context for this specific NPC
    ctx = live_ctx
    if ctx is None:
        _, ctx = resolve_live_context(name=npc_name, context=char_data, explicit_id=(char_data or {}).get("ID") if char_data else None)

    if not ctx:
        if not char_data:
            return ""
        # If no live context, fallback to persistent char_data
        ctx = char_data

    lines = [f"CURRENT CONDITION of {npc_name}:"]

    # --- Character State (imprisoned / enslaved / escaped) ---
    char_state = ctx.get("character_state", "normal")
    is_incapacitated = ctx.get("is_incapacitated", False)
    state_labels = {
        "imprisoned": f"CRITICAL: {npc_name} is currently IMPRISONED. They are locked up and cannot move freely. They should speak with desperation, resignation, or defiance.",
        "enslaved": f"CRITICAL: {npc_name} is ENSLAVED and wearing shackles. They are bound to a master. They should speak with fear, exhaustion, or suppressed rage.",
        "escaped-slave": f"CRITICAL: {npc_name} is an ESCAPED SLAVE — no longer chained but hunted. They should be paranoid, guarded, and desperate.",
        "unconscious": f"CRITICAL: {npc_name} is UNCONSCIOUS and cannot speak.",
        "dead": f"CRITICAL: {npc_name} is DEAD.",
    }
    if char_state in state_labels:
        lines.append(state_labels[char_state])

    # Identity
    race = ctx.get("race") or ctx.get("Race", "Unknown")
    gender = ctx.get("gender") or ctx.get("Sex", "Unknown")
    faction = ctx.get("faction") or ctx.get("Faction", "Unknown")
    job = ctx.get("job") or ctx.get("Job", "None")
    money = ctx.get("money") or 0
    relation = ctx.get("relation")

    lines.append(f"- RACE: {race}")
    lines.append(f"- SEX: {gender}")
    lines.append(f"- FACTION: {faction}")

    # Shopkeeper / Trader Status
    is_trader = ctx.get("is_trader", False)
    in_shop = ctx.get("in_shop", False)
    building_name = ctx.get("building_name", "Unknown")

    if is_trader or in_shop or "shopkeeper" in job.lower():
        shop_note = f"ROLE: {npc_name} is a SHOPKEEPER/TRADER."
        if in_shop:
            shop_note += f" They are currently IN THEIR SHOP ({building_name})."
        shop_note += " They are authorized to sell items and cats from their inventory in exchange for the player's cats or items."
        _stock_items = SHOP_STOCK.get(npc_name, [])
        if _stock_items:
            shop_note += f"\nSHOP ITEM RULE: Use ONLY the exact item names from your SHOP STOCK list below in [ACTION: GIVE_ITEM: ...]. Do NOT invent or abbreviate item names."
        else:
            shop_note += f"\nSHOP ITEM RULE: Your shop stock is not fully listed above. When the player requests an item you sell, use [ACTION: GIVE_ITEM: <item name>] with the EXACT name the player used (e.g., if they say 'skeleton leg', use exactly 'skeleton leg'). Do NOT invent alternative names. The game engine will match it to the correct shop item."
        lines.append(shop_note)
        if _stock_items:
            lines.append("SHOP STOCK (use these exact names in [ACTION: GIVE_ITEM: ...]):")
            for _item in _stock_items:
                lines.append(f"  - {_item}")

    # Leader Status
    if ctx.get("is_leader", False):
        lines.append(f"ROLE: {npc_name} is the LEADER of their faction. They speak with authority and make final decisions for their group.")

    lines.append(f"- CURRENT GOAL/JOB: {job}")
    if relation is not None:
        lines.append(f"- FACTION RELATION TO PLAYER: {relation} (Stance: {'ALLIED' if relation >= 50 else 'FRIENDLY' if relation > 0 else 'NEUTRAL' if relation == 0 else 'HOSTILE' if relation <= -30 else 'UNFRIENDLY'})")
    lines.append(f"- MONEY: {money} cats")

    # Group Leader Awareness
    player_faction = PLAYER_CONTEXT.get('faction', 'Nameless')
    lines.extend(build_loyalty_note(npc_name, faction, player_faction, ctx.get("factionID")))
    # Medical
    med = ctx.get("medical", {})
    if med:
        blood = med.get("blood", 100)
        hunger = med.get("hunger", 300)
        limbs = med.get("limbs", {})

        status_parts = []

        # Hunger Logic
        if hunger < 100:
            status_parts.append("STARVING")
        elif hunger < 250:
            status_parts.append("HUNGRY")
        else:
            status_parts.append("WELL FED")

        # Health Logic
        max_blood = med.get("max_blood", 100)
        blood_pct = blood / max_blood if max_blood > 0 else 1.0
        blood_rate = med.get("blood_rate", 0.0)

        if blood_rate > 0.01:
            status_parts.append("BLEEDING")
        elif blood_pct < 0.5:
            status_parts.append("WEAK FROM BLOODLOSS")
        elif blood_pct < 0.85:
            status_parts.append("INJURED")

        if med.get("is_unconscious"):
            status_parts.append("UNCONSCIOUS")

        lines.append(f"- CONDITION: {', '.join(status_parts) if status_parts else 'Healthy'}")

        # Limb Logic
        injuries = []
        # Filter out _max keys for iteration
        base_limbs = [l for l in limbs.keys() if not l.endswith("_max")]
        for limb in base_limbs:
            hp = limbs.get(limb, 100)
            hp_max = limbs.get(f"{limb}_max", 100)
            hp_pct = hp / hp_max if hp_max > 0 else 1.0

            if hp <= -hp_max:
                injuries.append(f"{limb.upper()} GONE/SEVERED")
            elif hp < 0:
                injuries.append(f"{limb.upper()} IS CRIPPLED")
            elif hp_pct < 0.5:
                injuries.append(f"{limb.upper()} IS INJURED")

        if injuries:
            lines.append(f"- INJURIES: {', '.join(injuries)}")
        else:
            lines.append("- INJURIES: None")

    # Environment
    env = ctx.get("environment", {})
    if env:
        loc = []
        if env.get("indoors"):
            loc.append("Indoors")
        if env.get("in_town"):
            loc.append(f"In town ({env.get('town_name', 'Unknown')})")
        if loc:
            lines.append(f"- LOCATION: {', '.join(loc)}")

    # Stats & Skills (Visible Power)
    stats = ctx.get("stats", {})
    if stats:
        lines.append(f"VISIBLE POWER of {npc_name}:")
        core = [f"{k[:3].upper()}: {int(float(stats.get(k, 0)))}" for k in ["strength", "dexterity", "toughness", "perception"]]
        lines.append(f"- ATTRIBUTES: {' | '.join(core)}")

        notable = []
        combat_skills = ["melee_attack", "melee_defence", "dodge", "katanas", "sabres", "hackers", "heavy_weapons", "blunt", "polearms", "martial_arts", "crossbows", "turrets", "stealth", "athletics"]
        for s in combat_skills:
            val = int(float(stats.get(s, 0)))
            if val > 15:  # Only show competent skills
                notable.append(f"{s.replace('_', ' ').capitalize()}: {val}")
        if notable:
            lines.append(f"- NOTABLE SKILLS: {', '.join(notable)}")

    # Memories
    mem = ctx.get("memories", {})
    st = [SHORT_TERM_MEM.get(m, str(m)) for m in mem.get("short_term", [])]
    lt = [LONG_TERM_MEM.get(m, str(m)) for m in mem.get("long_term", [])]

    if st or lt:
        lines.append(f"PERCEPTION OF PLAYER:")
        if st:
            lines.append(f"- SHORT TERM: {', '.join(st)}")
        if lt:
            lines.append(f"- HISTORY TAGS: {', '.join(lt)}")

    # Inventory & Equipment (Categorized)
    inv = ctx.get("inventory", [])
    if inv:
        worn = [i for i in inv if i.get("equipped")]
        held = [i for i in inv if not i.get("equipped")]

        if worn:
            lines.append(f"EQUIPMENT WORN by {npc_name}:")
            for item in worn:
                lines.append(f"- {item['name']} (x{item.get('count', 1)}) [{item['slot'].upper()}]")

        if held:
            lines.append(f"INVENTORY HELD by {npc_name}:")
            for item in held[:10]:
                lines.append(f"- {item['name']} (x{item.get('count', 1)})")
            if len(held) > 10:
                lines.append(f"- ... (and {len(held) - 10} other items)")
    else:
        lines.append(f"INVENTORY: Empty")

    # Nearby Awareness (Sensory Perception) — capped to 8 closest
    nearby = ctx.get("nearby", [])[:8]
    if nearby:
        lines.append(f"PEOPLE NEARBY (Visual Awareness):")
        for p in nearby:
            dist = float(p.get("dist", 0))
            dist_str = "Immediate proximity" if dist < 2.5 else f"{int(dist)}m away"
            p_name = p.get("name", "Someone")
            p_race = p.get("race", "Unknown")
            p_gender = p.get("gender", "Unknown")
            p_fact = p.get("faction", "Unknown")
            p_fact_display = p_fact
            if p_fact == "Nameless" or p_fact == PLAYER_CONTEXT.get('faction', 'Nameless'):
                p_fact_display = f"Player's Squad: {p_fact}"

            p_health = p.get("health", "Healthy")
            p_equip = p.get("equipment", "")

            p_desc = f"- {p_name} ({p_gender} {p_race}, {p_fact_display}) | Health: {p_health} | {dist_str}"
            if p_equip:
                p_desc += f" | Visible Gear: {p_equip}"
            lines.append(p_desc)

    return "\n".join(lines)


# --- INITIALIZATION SEQUENCE ---
load_configs()


def _load_event_history_from_log():
    """Re-populate EVENT_HISTORY from the on-disk log so synthesis works after a server restart."""
    # Use get_campaign_dir() to ensure we look in the active campaign log
    log_path = os.path.join(get_campaign_dir(), "logs", "global_events.log")
    if not os.path.exists(log_path):
        # Fallback to legacy global log location if campaign one isn't found yet
        log_path = os.path.join(KENSHI_SERVER_DIR, "logs", "global_events.log")
        if not os.path.exists(log_path):
            return
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                # Lines are prefixed with timestamp, strip it: "[Day] [TYPE] ..."
                bracket = line.find('][')
                if bracket != -1:
                    line = line[bracket + 1:]  # drop the timestamp prefix
                if line and line not in EVENT_HISTORY:
                    EVENT_HISTORY.append(line)
        logging.info(f"Loaded {len(EVENT_HISTORY)} events from global_events.log")
    except Exception as e:
        logging.error(f"Failed to load event history: {e}")


def init_server_state():
    global ACTIVE_CAMPAIGN, CURRENT_MODEL_KEY
    try:
        settings = load_settings()
        ACTIVE_CAMPAIGN = settings.get("current_campaign", "Default")
        CURRENT_MODEL_KEY = settings.get("current_model", "wizardlm-2")
        logging.info(f"INIT: Active Campaign: {ACTIVE_CAMPAIGN}, Model: {CURRENT_MODEL_KEY}")

        # Rewrite the settings to the INI to ensure any missing default keys are populated
        persist_current_settings()

        migrate_to_campaigns()
        load_campaign_config()
        # Load event history AFTER campaign is determined
        _load_event_history_from_log()
    except Exception as e:
        logging.error(f"INIT: Critical state init failure: {e}")


init_server_state()


def load_prompt_component(filename, default_text=""):
    def _try_cached(path, source_label):
        if not os.path.exists(path):
            return None
        try:
            mtime = os.path.getmtime(path)
            cached = _COMPONENT_CACHE.get(path)
            if cached and cached[0] == mtime:
                return cached[1]
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                _COMPONENT_CACHE[path] = (mtime, content)
                logging.info(f"PROMPT: Loaded {filename} from {source_label}")
                return content
        except Exception as e:
            logging.error(f"Error reading {filename} from {source_label}: {e}")
        return None

    # Try active campaign first, then templates (read-only)
    result = _try_cached(os.path.join(get_campaign_dir(), filename), f"campaign:{ACTIVE_CAMPAIGN}")
    if result is not None:
        return result
    result = _try_cached(os.path.join(TEMPLATES_DIR, filename), "templates (read-only)")
    if result is not None:
        return result
    return default_text


def format_player_status(player_ctx):
    """Summarizes player vitals and faction into a readable block."""
    if not player_ctx:
        return "No status data."
    res = "PLAYER STATUS:\n"
    res += f"- Race: {player_ctx.get('race', 'Unknown')}\n"
    res += f"- Gender: {player_ctx.get('gender', 'male')}\n"
    med = player_ctx.get("medical", {})
    if med:
        hunger = med.get("hunger", 300)
        blood = med.get("blood", 100)
        max_blood = med.get("max_blood", 100)
        blood_pct = blood / max_blood if max_blood > 0 else 1.0
        blood_rate = med.get("blood_rate", 0.0)
        status = []
        if hunger < 80:
            status.append("STARVING")
        elif hunger < 200:
            status.append("VERY HUNGRY")
        elif hunger < 250:
            status.append("HUNGRY")

        if blood_rate > 0.01:
            status.append("BLEEDING")
        elif blood_pct < 0.5:
            status.append("CRITICAL BLOODLOSS")
        elif blood_pct < 0.85:
            status.append("INJURED")

        res += f"- Condition: {', '.join(status) if status else 'Healthy/Fed'}\n"
    res += f"- Money: {player_ctx.get('money', 0)} cats\n"
    res += f"- Faction: {player_ctx.get('faction', 'Nameless')}\n"
    return res


def format_player_inventory(player_ctx):
    """Categorizes player inventory into Visible vs Concealed for the LLM."""
    if not player_ctx:
        return "No inventory data."
    inv = player_ctx.get("inventory", [])
    if not inv:
        return "Inventory: Empty or not visible."

    visible = []
    bag = []
    for item in inv:
        name = item.get("name", "Unknown Item")
        count = item.get("count", 1)
        equipped = item.get("equipped", False)
        slot = item.get("slot", "none")
        display = f"{name} (x{count})"
        if equipped:
            visible.append(f"{display} [{slot.upper()}]")
        else:
            bag.append(display)

    res = "PLAYER EQUIPMENT & INVENTORY:\n"
    res += "VISIBLE (Worn/Held):\n" + ("\n".join([f"- {v}" for v in visible]) if visible else "- Nothing visible.") + "\n"
    res += "CONCEALED (In Bag/Pack):\n" + ("\n".join([f"- {b}" for b in bag[:5]]) if bag else "- Bag appears empty.")
    if len(bag) > 5:
        res += f"\n- ... and {len(bag) - 5} more items."
    return res


def fetch_dynamic_lore(npc_data=None, env_override=None):
    """Filters the in-memory LORE_DATABASE by NPC tags, groups by type, and returns
    labeled prompt sections with per-type character budgets."""
    if not LORE_DATABASE:
        # Do NOT fall back to world_lore.txt — it is not loaded and risks exceeding context.
        return "The world is a brutal, post-apocalyptic sword-punk wasteland with no central government."

    search_terms = ["Global"]

    # 1. Build search terms from NPC context
    if npc_data:
        faction = npc_data.get("Faction", "")
        if faction and faction != "Unknown":
            search_terms.append(faction)
        search_terms.extend(p for p in npc_data.get("SourcePlatoons", []) if p)
        # Race tag enables race-specific chunks (e.g. lore_race_skeleton, lore_race_shek)
        race = npc_data.get("Race", "")
        if race and race != "Unknown":
            search_terms.append(race)
            _rl = race.lower()
            _fl = (faction or "").lower()
            _ofl = (npc_data.get("OriginFaction", "") or "").lower()
            _hive_ctx = "hive" in _fl or "hive" in _ofl
            if "fogman" in _rl or "deadhive" in _rl:
                search_terms.append("Fogman")
            elif "hive" in _rl:
                search_terms.append("Hiver")
                if "prince" in _rl:
                    search_terms.append("Hive Prince")
                if "soldier" in _rl or ("drone" in _rl and "worker" not in _rl):
                    search_terms.append("Soldier Drone")
                if "worker" in _rl:
                    search_terms.append("Hive Worker Drone")
            elif "drone" in _rl and _hive_ctx:
                # e.g. vanilla "Worker Drone" whose faction confirms Hiver identity
                search_terms.append("Hiver")
                if "worker" in _rl:
                    search_terms.append("Hive Worker Drone")
                elif "soldier" in _rl:
                    search_terms.append("Soldier Drone")
            elif "skeleton" in _rl or "mechanical" in _rl or ("drone" in _rl and not _hive_ctx):
                search_terms.append("Skeleton")

        # Religion tag injects theology for the NPC's actual faith regardless of faction
        # e.g. a Narkoite wanderer in a secular faction still gets Okran/Narko lore
        religion = npc_data.get("Traits", {}).get("Religion", "")
        if religion and religion not in ("N/A", "Unknown", "Hive-Bound"):
            search_terms.append(religion)

    # 2. Add location tags

    env = env_override if env_override is not None else (PLAYER_CONTEXT.get("environment", {}) if PLAYER_CONTEXT else {})

    if isinstance(env, dict):
        town_name = env.get("town_name")
        if town_name:
            search_terms.append(town_name)

        biome = env.get("biome")
        if biome:
            search_terms.append(biome)

    # 3. Match chunks and bucket by type
    by_type = {t: [] for t in _LORE_TYPE_ORDER}
    for chunk in LORE_DATABASE:
        if any(term in chunk.get("tags", []) for term in search_terms):
            chunk_type = chunk.get("type", "faction")
            if chunk_type in by_type:
                by_type[chunk_type].append(chunk.get("content", ""))

    # 4. Build output: labeled sections, each capped at its own budget
    sections = []
    for lore_type in _LORE_TYPE_ORDER:
        chunks = by_type[lore_type]
        if not chunks:
            continue
        budget = _LORE_TYPE_BUDGETS[lore_type]
        selected, total = [], 0
        for content in chunks:
            if total > 0 and total + len(content) > budget:
                break
            selected.append(content)
            total += len(content)
        if selected:
            header = _LORE_TYPE_HEADERS[lore_type]
            sections.append(f"[{header}]\n" + "\n".join(selected))

    return "\n\n".join(sections)


def build_events_block():
    """Build the world events/rumors block separately from the stable system prompt.
    Called per-request so NPCs always hear the latest news, but kept outside
    build_system_prompt() so it doesn't break KV cache prefix reuse."""
    settings = load_settings()
    ge_count = settings.get("global_events_count", 7)
    events_list = []

    # 1. Load Synthesized Rumors (High-level) — cached by file mtime, reloads only when synthesis writes a new rumor
    global _RUMORS_CACHE, _RUMORS_CACHE_MTIME
    world_events_path = os.path.join(get_campaign_dir(), "world_events.txt")
    if os.path.exists(world_events_path):
        try:
            mtime = os.path.getmtime(world_events_path)
            if mtime != _RUMORS_CACHE_MTIME:
                with open(world_events_path, "r", encoding="utf-8") as f:
                    _RUMORS_CACHE = [l.strip() for l in f.readlines() if l.strip().startswith("- [")]
                _RUMORS_CACHE_MTIME = mtime
            events_list.extend(_RUMORS_CACHE[-max(1, ge_count // 2):])
        except Exception as e:
            logging.warning(f"build_events_block: failed to read world_events.txt ({e})")

    # 2. Load Raw Event History (Recent logs)
    if EVENT_HISTORY:
        raw_recent = EVENT_HISTORY[-max(1, ge_count - len(events_list)):]
        for e in raw_recent:
            events_list.append(f"- {e}")

    if not events_list:
        return ""
    return "WORLD STATUS & RUMORS (Hearsay):\n" + "\n".join(events_list[-ge_count:])


def build_system_prompt(player_name="Drifter", npc_data=None):
    player_bio = load_prompt_component("character_bio.txt", "A mysterious drifter.")
    player_faction_desc = load_prompt_component("player_faction_description.txt", "")
    npc_base = load_prompt_component("npc_base.txt", "You are an NPC in the world of Kenshi. Stay in character.")
    world_lore = fetch_dynamic_lore(npc_data)
    rules = load_prompt_component("response_rules.txt", "Respond naturally to the player.")
    action_tags = load_prompt_component("prompt_action_tags.txt", "")

    settings = load_settings()

    # Get player faction name (default to Nameless if missing)
    player_faction = PLAYER_CONTEXT.get("faction", "Nameless") if PLAYER_CONTEXT else "Nameless"

    # Only include faction description if it's not empty
    faction_block = ""
    if player_faction_desc.strip():
        faction_block = f"PLAYER FACTION ({player_faction}):\n{player_faction_desc}\n"

    # Location Tag
    location_tag = "The Wasteland"
    if PLAYER_CONTEXT:
        env = PLAYER_CONTEXT.get("environment", {})
        if isinstance(env, dict):
            town = env.get("town_name", "")
            biome = env.get("biome", "")
            if town and biome:
                location_tag = f"{town} (within {biome})"
            elif town:
                location_tag = town
            elif biome:
                location_tag = biome

    # Language instruction — ensures all providers respect the UI language setting,
    # not just player2 which happens to auto-detect from context.
    language = settings.get("language", "English")
    language_instruction = ""
    if language and language.lower() != "english":
        language_instruction = f"\nLANGUAGE: You MUST respond ONLY in {language}. Do not switch to English under any circumstances.\n"

    # Get player identity details from context
    player_race = PLAYER_CONTEXT.get("race", "Unknown") if PLAYER_CONTEXT else "Unknown"
    player_gender = PLAYER_CONTEXT.get("gender", "male") if PLAYER_CONTEXT else "male"

    prompt = f"""{npc_base}

CURRENT LOCATION: {location_tag}

WORLD LORE:
{world_lore}

PLAYER CHARACTER ({player_name}):
RACE: {player_race}
GENDER: {player_gender}
{player_bio}

{faction_block}

RESPONSE FORMAT RULES:
{rules}

{action_tags}
{language_instruction}"""
    return prompt.strip()


# --- WORLD REGISTRY (Save-Based Persistence) ---
WORLD_INDEX = {}


def update_world_index():
    global WORLD_INDEX
    try:
        WORLD_INDEX = build_world_index()
        logging.info(f"World Index Updated: {len(WORLD_INDEX)} names indexed from latest save.")
    except Exception as e:
        logging.error(f"Failed to update world index: {e}")


# Initial scan
update_world_index()

# Requirement: "Character Initialization Attachment"
# Fulfill by ensuring registry files exist for all known characters


def populate_initial_registry():
    registry_dir = os.path.join(get_campaign_dir(), "sentient_sands_registry")
    if not os.path.exists(registry_dir):
        os.makedirs(registry_dir)

    for name, platoons in WORLD_INDEX.items():
        clean_name = re.sub(r'[^\w\s-]', '', name).strip().replace(' ', '_')
        if not clean_name:
            continue
        reg_file = os.path.join(registry_dir, f"{clean_name}_init.txt")
        if not os.path.exists(reg_file):
            with open(reg_file, "w", encoding="utf-8") as f:
                f.write(f"Registry: {name} initialized. Location: {platoons[0]}\n")


populate_initial_registry()

# Characters directory is managed by load_campaign_config()
# Do not re-assign here.


def call_llm(messages, max_tokens=2048, temperature=0.8):
    global PLAYER2_SESSION_KEY
    model_entry = MODELS_CONFIG.get(CURRENT_MODEL_KEY)
    if not model_entry:
        logging.error(f"Model Error: {CURRENT_MODEL_KEY} not configured.")
        return None

    provider_name = model_entry.get("provider")
    provider_config = PROVIDERS_CONFIG.get(provider_name)
    if not provider_config:
        logging.error(f"Provider Error: {provider_name} not configured.")
        return None

    api_key = provider_config.get("api_key")
    if provider_name == "player2" and PLAYER2_SESSION_KEY:
        api_key = PLAYER2_SESSION_KEY

    base_url = (provider_config.get("base_url") or "").rstrip("/")
    target_url = f"{base_url}/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "Sentient Sands Mod",
        "HTTP-Referer": "https://github.com/harvicusdev-glitch/SentientSands"
    }

    # player2 specific header
    if provider_name == "player2":
        headers["player2-game-key"] = "019c93fc-7a93-7ac4-8c6e-df0fd09bec01"

    payload = {
        "model": model_entry["model"],
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": 0.9,
        "repetition_penalty": 1.1,
    }

    last_error = None
    for attempt in range(3):
        try:
            debug_logger.debug(f"LLM REQUEST [{provider_name}] to {target_url} (Payload omitted for security)")
            start_time = time.time()
            response = requests.post(target_url, headers=headers, json=payload, timeout=120)
            elapsed = time.time() - start_time

            if response.status_code == 200:
                data = response.json()
                choices = data.get('choices', [])
                if not choices:
                    logging.warning(f"API Success but empty choices: {data}")
                    return None

                msg_obj = choices[0].get('message', {})
                content = msg_obj.get('content')

                # Check for alternative fields used by some providers (Thinking/Reasoning/Legacy)
                if content is None:
                    # Try reasoning_content (DeepSeek/Thinking style)
                    content = msg_obj.get('reasoning_content')

                if content is None:
                    # Try legacy 'text' field just in case
                    content = choices[0].get('text')

                logging.info(f"API Success in {elapsed:.1f}s (Attempt {attempt + 1})")

                if content is None:
                    logging.warning(f"API Success but no content found in message. Message body: {msg_obj}")
                    debug_logger.warning(f"EMPTY RESPONSE DETAIL: {data}")
                    # If we got a 200 but no text, return a placeholder instead of None to prevent crashes
                    return "... (Empty Response)"

                debug_logger.debug(f"RAW LLM response received (Length: {len(content) if content else 0})")

                # Robust Reasoning Block Removal
                if "</thought>" in content:
                    content = content.split("</thought>")[-1]

                # Strip XML-like thought tags if they remain
                content = re.sub(r'<thought>.*?</thought>', '', content, flags=re.DOTALL | re.IGNORECASE)
                content = re.sub(r'<thought>.*', '', content, flags=re.DOTALL | re.IGNORECASE)

                # Strip internal reasoning prefixes
                if "\n\n" in content and ("thought" in CURRENT_MODEL_KEY.lower() or content.strip().lower().startswith("thought:")):
                    parts = content.split("\n\n")
                    # Only strip if the first part looks like a thought
                    if "thought" in parts[0].lower() or "reasoning" in parts[0].lower():
                        content = "\n\n".join(parts[1:])

                if not content.strip():
                    return "..."
                return sanitize_llm_text(content.strip())
            elif response.status_code == 401 and provider_name == "player2":
                last_error = f"API ERROR 401: Unauthorized - attempting local token refresh"
                logging.warning(f"Player2 token expired/invalid (401). Attempting re-auth...")
                try:
                    auth_url = f"http://localhost:4315/v1/login/web/019c93fc-7a93-7ac4-8c6e-df0fd09bec01"
                    auth_resp = requests.post(auth_url, timeout=5)
                    if auth_resp.status_code == 200:
                        new_key = auth_resp.json().get("p2Key")
                        if new_key:
                            PLAYER2_SESSION_KEY = new_key
                            headers["Authorization"] = f"Bearer {PLAYER2_SESSION_KEY}"
                            logging.info("Successfully refreshed Player2 token locally.")
                except Exception as e:
                    logging.error(f"Failed to refresh Player2 token: {e}")

                logging.error(f"Attempt {attempt + 1} failed after {elapsed:.1f}s: {last_error}")
                if attempt < 2:
                    time.sleep(1)
            else:
                last_error = f"API ERROR {response.status_code}: {response.text[:200]}"
                logging.error(f"Attempt {attempt + 1} failed after {elapsed:.1f}s: {last_error}")
                if attempt < 2:
                    time.sleep(1)

        except Exception as e:
            last_error = str(e)
            logging.error(f"Attempt {attempt + 1} Exception: {e}")
            debug_logger.error(f"LLM EXCEPTION STACK (Attempt {attempt + 1}):\n{traceback.format_exc()}")
            if attempt < 2:
                time.sleep(1)

    return None


# Load Canon Characters
CANON_CHARACTERS_PATH = os.path.join(SCRIPT_DIR, "..", "config", "canon_characters.json")
CANON_CHARACTERS = {}


def load_canon_characters():
    global CANON_CHARACTERS
    if os.path.exists(CANON_CHARACTERS_PATH):
        try:
            with open(CANON_CHARACTERS_PATH, "r") as f:
                data = json.load(f)
                for char in data:
                    CANON_CHARACTERS[char["Name"].lower()] = char
            logging.info(f"Loaded {len(CANON_CHARACTERS)} canon characters.")
        except Exception as e:
            logging.error(f"Failed to load canon_characters.json: {e}")


load_canon_characters()


def generate_character_profile(name, context: Union[str, dict] = ""):
    lower_name = name.lower()
    if "your squad" in lower_name or "squad" == lower_name:
        player_faction = PLAYER_CONTEXT.get('faction', 'Nameless')
        return {
            "Personality": "A collective of your loyal companions, each with their own views but united in purpose. They are loyal to you and the squad's goals.",
            "Backstory": f"You have traveled together as members of the {player_faction} through the harsh lands of Kenshi, surviving against all odds.",
            "SpeechQuirks": "Speaks as a representative of the group, sometimes mentioning others in the squad.",
            "Race": "Mixed",
            "Faction": player_faction,
            "Sex": "Mixed"
        }

    if lower_name in CANON_CHARACTERS:
        logging.info(f"Found canon match for {name}")
        return CANON_CHARACTERS[lower_name]

    # Extract race/faction from request-local context or the live cache.
    _, live_ctx = resolve_live_context(name=name, context=context)
    live_ctx = live_ctx or {}

    race = "Unknown"
    gender = "Unknown"
    faction = "Unknown"
    origin_faction = "Unknown"
    job = "None"

    # Try context first
    ctx_data = {}
    if isinstance(context, dict):
        ctx_data = context
    elif isinstance(context, str) and context.strip().startswith('{'):
        try:
            ctx_data = json.loads(context)
        except:
            pass

    if ctx_data:
        race = ctx_data.get('race', race)
        gender = ctx_data.get('gender', gender)
        faction = ctx_data.get('faction', faction)
        if faction == "Unknown":
            faction = ctx_data.get('factionID', "Unknown")
        origin_faction = ctx_data.get('origin_faction', "Unknown")
        job = ctx_data.get('job', "None")

    # Fallback to LIVE_CONTEXTS if still unknown
    if race == "Unknown":
        race = live_ctx.get('race', 'Unknown')
    if gender == "Unknown":
        gender = live_ctx.get('gender', 'Unknown')
    if faction == "Unknown":
        faction = live_ctx.get('faction', 'Unknown')
        if faction == "Unknown":
            faction = live_ctx.get('factionID', "Unknown")

    if origin_faction == "Unknown":
        origin_faction = live_ctx.get('origin_faction', 'Unknown')
    if job == "None":
        job = live_ctx.get('job', 'None')

    # RELAXED CONSTRAINTS: Only skip if we truly have nothing or the name is generic.
    # Modded factions often fail to report pretty names through standard hooks.
    if name in ("Unknown", "Someone", "Unknown Entity"):
        logging.info(f"Skipping profile: Name is {name}.")
        return None

    logging.info(f"Generating rich profile for {name} ({gender} {race}, Base Faction: {origin_faction}, Job: {job})...")

    template = load_prompt_component("prompt_profile_generation.txt", """You are an expert on Kenshi lore.
Task: Generate a character profile for the NPC named "{name}".
SEX: {gender}
RACE: {race}
ORIGIN FACTION: {origin_faction}
CURRENT FACTION: {faction}
JOB: {job}
DATA: {context}

CRITICAL RULES:
1. CANON FIRST: If "{name}" is a known Kenshi character (e.g. Beep, Holy Lord Phoenix, Cat-Lon), use exact canon lore.
2. NON-CANON: If generic (e.g. "Dust Bandit", "Shop Guard"), create a grounded profile fitting the setting.
3. PERSONALITY: The character MUST speak and behave according to their sex ({gender}) and race ({race}). 
4. OUTPUT: JSON only with keys: "Personality", "Backstory", "SpeechQuirks".
""")
    f_info = get_faction_info(faction)
    o_info = get_faction_info(origin_faction)

    prompt = template.format(name=name, gender=gender, race=race, faction=f_info, origin_faction=o_info, job=job, context=context)

    # Apply language instruction for profile generation
    settings = load_settings()
    language = settings.get("language", "English")
    if language and language.lower() != "english":
        prompt += f"\nLANGUAGE: The JSON values ('Personality', 'Backstory', 'SpeechQuirks') MUST be written entirely in {language}. Do not use English.\n"

    messages = [{"role": "user", "content": prompt}]
    response_text = call_llm(messages, max_tokens=1200, temperature=0.7)

    if response_text:
        try:
            result = robust_json_parse(response_text)
            if result:
                # Add race/faction to result for get_character_data
                result["Race"] = race
                result["Faction"] = faction
                result["OriginFaction"] = origin_faction
                result["Job"] = job
                result["Sex"] = gender
                result["Traits"] = generate_npc_traits(faction, race, origin_faction)
                return result
        except Exception as e:
            logging.error(f"Failed to parse generated profile: {e}")

    return {
        "Personality": "A weary wanderer.",
        "Backstory": "Trying to survive in the harsh desert.",
        "SpeechQuirks": "None.",
        "Race": race,
        "Faction": faction,
        "OriginFaction": origin_faction,
        "Job": job,
        "Sex": gender,
        "Traits": generate_npc_traits(faction, race, origin_faction)
    }


def generate_batch_profiles(npc_list):
    """Lump multiple NPC profile generations into a single LLM call."""
    if not npc_list:
        return

    # Filter out any NPCs that don't have all three required fields.
    # These will be deferred until we have full context from the game.
    complete = []
    for npc in npc_list:
        name = npc.get('name', 'Unknown')
        race = npc.get('race', 'Unknown')
        gender = npc.get('gender', 'Unknown')
        faction = npc.get('faction', 'Unknown')
        missing = [k for k, v in {"race": race, "gender": gender, "faction": faction}.items() if v in ("Unknown", None, "")]
        if missing:
            logging.info(f"BATCH: Skipping {name} \u2014 missing {', '.join(missing)}, will generate on next full context.")
        else:
            complete.append(npc)

    if not complete:
        logging.info("BATCH: No complete NPC data available, deferring all profiles.")
        return

    logging.info(f"BATCH: Generating {len(complete)} profiles ({len(npc_list) - len(complete)} deferred)...")

    template = load_prompt_component("prompt_batch_profile_generation.txt", """You are an expert on Kenshi lore.
Task: Generate character profiles for several NPCs at once.

NPCS TO GENERATE:
{desc_str}

CRITICAL RULES:
1. CANON FIRST: If a name is a known Kenshi character (e.g. Beep, Holy Lord Phoenix), use exact canon lore.
2. NON-CANON: Generate grounded, cynical, or weary profiles fitting the harsh Kenshi setting.
3. OUTPUT: Return a JSON object where each key is the NPC's Name, and the value is an object with: "Personality", "Backstory", "SpeechQuirks".
""")

    settings = load_settings()
    language = settings.get("language", "English")

    # Split into chunks of 10 so no single LLM call exceeds ~1500 tokens of output.
    # Each profile takes ~75-100 tokens; 20+ NPCs (large bars) would truncate mid-JSON otherwise.
    _BATCH_CHUNK_SIZE = 3
    all_results = {}
    for _chunk_i in range(0, len(complete), _BATCH_CHUNK_SIZE):
        _chunk = complete[_chunk_i:_chunk_i + _BATCH_CHUNK_SIZE]
        _chunk_descs = "\n".join(
            f"- Name: {n.get('name', 'Unknown')}, Sex: {n.get('gender', 'Unknown')}, "
            f"Race: {n.get('race', 'Unknown')}, Faction: {get_faction_info(n.get('faction', 'Unknown'))}"
            for n in _chunk
        )
        _chunk_prompt = template.format(desc_str=_chunk_descs)
        if language and language.lower() != "english":
            _chunk_prompt += f"\nLANGUAGE: All generated profile values ('Personality', 'Backstory', 'SpeechQuirks') MUST be written entirely in {language}. Do not use English for the values.\n"
        _chunk_messages = [{"role": "user", "content": _chunk_prompt}]
        _chunk_num = _chunk_i // _BATCH_CHUNK_SIZE + 1
        _total_chunks = (len(complete) + _BATCH_CHUNK_SIZE - 1) // _BATCH_CHUNK_SIZE
        logging.info(f"BATCH: Chunk {_chunk_num}/{_total_chunks} ({len(_chunk)} NPCs)...")
        _chunk_max = min(4000, max(1500, len(_chunk) * 800))
        _chunk_text = call_llm(_chunk_messages, max_tokens=_chunk_max, temperature=0.7)
        if _chunk_text:
            try:
                _chunk_results = robust_json_parse(_chunk_text)
                if _chunk_results:
                    # Detect single-NPC unwrapped response: LLM returned {Personality:..., Backstory:..., SpeechQuirks:...}
                    # instead of {NPC_Name: {Personality:..., ...}}. Re-wrap with the NPC's clean name.
                    if (len(_chunk) == 1
                            and "Personality" in _chunk_results
                            and "Backstory" in _chunk_results
                            and isinstance(_chunk_results.get("Personality"), str)):
                        _only_ctx = _parse_context_dict(_chunk[0], fallback_name=_chunk[0].get("name", "Unknown"))
                        _only_name = (_only_ctx.get("name") or _chunk[0].get("name", "Unknown")).split("|")[0]
                        logging.info(f"BATCH: Re-wrapping unwrapped single-NPC response for '{_only_name}'")
                        _chunk_results = {_only_name: _chunk_results}
                    all_results.update(_chunk_results)
            except Exception as _e:
                logging.error(f"BATCH: Failed to parse chunk {_chunk_num}: {_e}")

    if all_results:
        try:
            batch_results = all_results
            for npc in npc_list:
                npc_ctx = _parse_context_dict(npc, fallback_name=npc.get('name', 'Unknown'))
                raw_name = str(npc_ctx.get('name', npc.get('name', 'Unknown'))).strip()
                clean_name = raw_name.split('|')[0].strip() if '|' in raw_name else raw_name
                gender = npc_ctx.get('gender', npc.get('gender', 'Neutral'))

                # Try to find profile by exact clean name, raw name, or case-insensitive match
                profile = batch_results.get(clean_name) or batch_results.get(raw_name)

                if not profile:
                    # Case-insensitive and pipe-resilient fallback
                    clean_low = clean_name.lower()
                    raw_low = raw_name.lower()
                    for k, v in batch_results.items():
                        k_low = k.lower()
                        # Strip ID from LLM key if it included it
                        k_clean_low = k_low.split('|')[0].strip() if '|' in k_low else k_low.strip()

                        if k_low == clean_low or k_low == raw_low or k_clean_low == clean_low:
                            profile = v
                            break

                if not profile:
                    logging.warning(
                        f"BATCH: No match for clean='{clean_name}' raw='{raw_name}' "
                        f"LLM keys={list(batch_results.keys())}"
                    )

                if profile:
                    _batch_faction = npc_ctx.get('faction') or npc_ctx.get('Faction') or 'Unknown'
                    storage_id = npc_ctx.get("storage_id") or make_storage_id(clean_name, _batch_faction, context=npc_ctx)
                    _batch_race = npc_ctx.get('race', 'Unknown')
                    _batch_origin = npc_ctx.get('origin_faction', 'Unknown')
                    data = {
                        "ID": storage_id,
                        "Name": clean_name,
                        "OriginalName": clean_name,
                        "Race": _batch_race,
                        "Sex": gender or 'Unknown',
                        "Faction": _batch_faction,
                        "OriginFaction": _batch_origin,
                        "Job": npc_ctx.get('job', npc.get('job', 'None')),
                        "Personality": profile.get("Personality", "A weary traveler."),
                        "Backstory": profile.get("Backstory", "Trying to survive in the harsh desert."),
                        "SpeechQuirks": profile.get("SpeechQuirks", "None."),
                        "Traits": generate_npc_traits(_batch_faction, _batch_race, _batch_origin),
                        "ConversationHistory": [],
                        "Relation": 0
                    }
                    existing = load_existing_profile(storage_id)
                    if existing:
                        data["ConversationHistory"] = list(existing.get("ConversationHistory", []))
                        data["Relation"] = existing.get("Relation", 0)
                        if existing.get("SourcePlatoons"):
                            data["SourcePlatoons"] = existing["SourcePlatoons"]
                    save_character_data(storage_id, data)
                    logging.info(f"BATCH: Saved profile for {clean_name} (ID: {storage_id})")
        except Exception as e:
            logging.error(f"BATCH: Failed to parse batch profiles: {e}")


def queue_batch_profile_generation(npc_list):
    """Queue profile generation in the background and mark IDs as in-progress up front."""
    if not npc_list:
        return 0

    queued = []
    with PROGRESS_LOCK:
        for npc in npc_list:
            if not isinstance(npc, dict):
                continue

            ctx = _parse_context_dict(npc, fallback_name=npc.get("name", "Unknown"))
            raw_name = ctx.get("name", npc.get("name", "Unknown"))
            clean_name = raw_name.split('|')[0] if '|' in raw_name else raw_name
            faction = ctx.get("faction") or ctx.get("Faction") or npc.get("faction") or npc.get("Faction") or ""
            storage_id = ctx.get("storage_id") or make_storage_id(clean_name, faction, context=ctx)

            if storage_id in PROFILES_IN_PROGRESS:
                continue

            PROFILES_IN_PROGRESS.add(storage_id)
            ctx["storage_id"] = storage_id
            queued.append(ctx)

    if not queued:
        return 0
    if direct_chat_active():
        defer_profile_batch(queued)
        logging.info(f"BATCH: Deferred {len(queued)} profiles while direct chat is active.")
        return len(queued)

    return _launch_batch_profile_generation(queued)


def get_character_data(name, context: Union[str, dict] = "", char_id=None, skip_generate=False):
    # CRITICAL: If the name contains a pipe (serial ID), split it to get the clean name.
    # This prevents "Name|ID" from creating unique "NameID" junk profiles.
    if '|' in name:
        name_parts = name.split('|')
        name = name_parts[0]
        if not char_id and len(name_parts) > 1:
            char_id = name_parts[1]

    # Resolve request-local context and then fall back to the live cache.
    ctx_data = _parse_context_dict(context, fallback_name=name)
    live_explicit_id = (
        ctx_data.get("runtime_id")
        or ctx_data.get("id")
        or char_id
    )
    _, live_ctx = resolve_live_context(name=name, context=ctx_data, explicit_id=live_explicit_id)
    live_ctx = live_ctx or {}

    name = str(name).strip()
    _faction = (ctx_data.get("faction") or live_ctx.get("faction") or "").strip()
    persistent_id = str(ctx_data.get("persistent_id") or live_ctx.get("persistent_id") or "").strip() or None
    if not persistent_id and _is_strong_uid(char_id):
        persistent_id = str(char_id).strip()

    base_sid = make_storage_id(name, _faction)

    # Prevent hive-mind generics when the in-game Renamer is disabled
    # Attach their reload-safe persistent ID to force distinct profiles that survive saves
    if is_npc_name_generic(name):
        _safe_id = persistent_id or str(ctx_data.get("runtime_id") or live_ctx.get("runtime_id") or char_id or "").strip()
        storage_id = f"{base_sid}_{_safe_id}" if _safe_id else base_sid
    else:
        storage_id = persistent_id if _is_strong_uid(persistent_id) else base_sid

    path = _character_path(storage_id)

    if _is_strong_uid(storage_id) and not os.path.exists(path):
        legacy_candidates = []
        legacy_sid = make_storage_id(name, _faction)
        if legacy_sid and legacy_sid != storage_id:
            legacy_candidates.append(legacy_sid)
        if name and name not in legacy_candidates and name != storage_id:
            legacy_candidates.append(name)

        for legacy_sid in legacy_candidates:
            legacy_path = _legacy_character_path(legacy_sid)
            if not os.path.exists(legacy_path):
                continue
            try:
                with open(legacy_path, "r", encoding="utf-8") as handle:
                    legacy_data = json.load(handle)
                legacy_data["ID"] = storage_id

                # Write to the new format
                save_character_data(storage_id, legacy_data)
                # Archive legacy JSON
                os.rename(legacy_path, legacy_path + ".bak")

                old_safe = _safe_char_filename(legacy_sid)
                new_safe = _safe_char_filename(storage_id)
                with CACHE_LOCK:
                    _e1 = CHARACTER_CACHE.pop(legacy_sid, None)
                    _e2 = CHARACTER_CACHE.pop(old_safe, None)
                    _e3 = CHARACTER_CACHE.pop(name, None)
                    old_entry = _e1 or _e2 or _e3
                    if old_entry:
                        old_entry["ID"] = storage_id
                        CHARACTER_CACHE[storage_id] = old_entry
                logging.info(f"MIGRATE: legacy {old_safe}.json -> {new_safe}.cfg")
                break
            except Exception as exc:
                logging.warning(f"MIGRATE: legacy-to-persistent migration failed for {legacy_sid}: {exc}")

    # MIGRATION: If the faction-qualified file doesn't exist yet, check for a legacy
    # name-only file. If its internal Faction field matches, rename it to the new format
    # so NPCs don't lose their conversation history after this update.
    if not os.path.exists(path) and storage_id != name:
        legacy_path = _legacy_character_path(name)
        if os.path.exists(legacy_path):
            try:
                with open(legacy_path, "r", encoding="utf-8") as _lf:
                    legacy_data = json.load(_lf)
                legacy_faction = (legacy_data.get("Faction") or legacy_data.get("faction") or "").strip()
                # Only migrate if the file's own faction matches (avoids migrating a
                # collision-corrupted file to the wrong NPC)
                if make_storage_id(name, legacy_faction) == storage_id:
                    legacy_data["ID"] = storage_id  # Update stale ID field before rename

                    save_character_data(storage_id, legacy_data)
                    os.rename(legacy_path, legacy_path + ".bak")

                    _legacy_safe = _safe_char_filename(name)
                    _new_safe = _safe_char_filename(storage_id)
                    with CACHE_LOCK:
                        # Pop each alias independently — or-chain would skip later keys on first hit
                        _e1 = CHARACTER_CACHE.pop(name, None)
                        _e2 = CHARACTER_CACHE.pop(_legacy_safe, None)
                        old_entry = _e1 or _e2
                        if old_entry:
                            old_entry["ID"] = storage_id
                            CHARACTER_CACHE[storage_id] = old_entry
                    logging.info(f"MIGRATE: {_legacy_safe}.json → {_new_safe}.cfg")
            except Exception as _me:
                logging.warning(f"MIGRATE: Could not migrate {name}: {_me}")

    # MIGRATION 2: Space→underscore in name part. If the NPC name has spaces, the old
    # make_storage_id produced "Paladin Elam_Drifters" (space in name). The new version
    # produces "Paladin_Elam_Drifters" (underscore). Rename the old file so history is
    # preserved. Only runs when the faction-qualified file doesn't exist yet.
    if not os.path.exists(path) and ' ' in name and _faction:
        _f_slug = re.sub(r'\s+', '_', re.sub(r'[^\w\s-]', '', _faction).strip())
        if _f_slug:
            old_space_sid = f"{name}_{_f_slug}"  # old form: spaces preserved in name
            if old_space_sid != storage_id:
                old_space_path = _legacy_character_path(old_space_sid)
                if os.path.exists(old_space_path):
                    try:
                        with open(old_space_path, "r", encoding="utf-8") as _sf:
                            space_data = json.load(_sf)
                        space_data["ID"] = storage_id

                        save_character_data(storage_id, space_data)
                        os.rename(old_space_path, old_space_path + ".bak")

                        old_space_safe = _safe_char_filename(old_space_sid)
                        _new_safe = _safe_char_filename(storage_id)
                        with CACHE_LOCK:
                            # Pop each alias independently — or-chain would skip later keys on first hit
                            _e1 = CHARACTER_CACHE.pop(old_space_sid, None)
                            _e2 = CHARACTER_CACHE.pop(old_space_safe, None)
                            _e3 = CHARACTER_CACHE.pop(name, None)
                            old_entry = _e1 or _e2 or _e3
                            if old_entry:
                                old_entry["ID"] = storage_id
                                CHARACTER_CACHE[storage_id] = old_entry
                        logging.info(f"MIGRATE: space-name {old_space_safe}.json → {_new_safe}.cfg")
                    except Exception as _me:
                        logging.warning(f"MIGRATE: space-name migration failed for {name}: {_me}")

    transient_existing = None
    data = load_existing_profile(storage_id)

    # MIGRATION 3: We loaded legacy data from .json in load_existing_profile,
    # let's instantly save it to format it to CFG and TXT and rename the old file to .bak
    if data and os.path.exists(_legacy_character_path(storage_id)) and not os.path.exists(_character_path(storage_id)):
        lg_p = _legacy_character_path(storage_id)
        save_character_data(storage_id, data)
        try:
            os.rename(lg_p, lg_p + ".bak")
        except:
            pass

    if profile_needs_upgrade(data):
        transient_existing = data
        if skip_generate:
            return data
        data = None

    # --- NEW CONTEXT BLOAT TRUNCATION ---
    # Instantly trims bloated legacy files the second they are loaded
    if data and "ConversationHistory" in data and len(data["ConversationHistory"]) > 45:
        data["ConversationHistory"] = data["ConversationHistory"][-45:]

    # Warn if a new incoming serial ID doesn't match what's stored — surfaces drift
    if data and char_id and data.get("ID"):
        incoming_id = str(char_id).strip()
        stored_id = str(data["ID"]).strip()
        if incoming_id and stored_id != incoming_id and not re.fullmatch(r"-?\d+", incoming_id):
            logging.warning(f"ID mismatch for '{name}': stored={stored_id}, incoming={incoming_id}")

    # Schema Migration for legacy files
    if data:
        if "ConversationHistory" not in data:
            data["ConversationHistory"] = []
        if "Relation" not in data:
            data["Relation"] = 0
        if "Race" not in data:
            data["Race"] = "Unknown"
        if "Sex" not in data:
            data["Sex"] = "Unknown"
        if "Faction" not in data:
            data["Faction"] = "Unknown"
        if "OriginFaction" not in data:
            data["OriginFaction"] = "Unknown"
        if "Job" not in data:
            data["Job"] = "None"
        if "Traits" not in data:
            data["Traits"] = generate_npc_traits(
                data.get("Faction", "Unknown"),
                data.get("Race", "Unknown"),
                data.get("OriginFaction", "Unknown")
            )

    # If we have context, try to update race/faction if they are unknown or missing
    if ctx_data:
        try:
            if data:
                current_race = ctx_data.get("race", "Unknown")
                current_sex = ctx_data.get("gender", "Unknown")
                current_faction = ctx_data.get("faction", "Unknown")
                needs_save = False

                if data.get("Race") == "Unknown" and current_race != "Unknown":
                    logging.info(f"Updating Race for {name}: {current_race}")
                    data["Race"] = current_race
                    needs_save = True

                if data.get("Sex") in ("Unknown", None) and current_sex not in ("Unknown", None):
                    logging.info(f"Updating Sex for {name}: {current_sex}")
                    data["Sex"] = current_sex
                    needs_save = True

                if data.get("Faction") == "Unknown" and current_faction != "Unknown":
                    logging.info(f"Updating Faction for {name}: {current_faction}")
                    data["Faction"] = current_faction
                    needs_save = True

                current_origin = ctx_data.get("origin_faction", "Unknown")
                if data.get("OriginFaction") == "Unknown" and current_origin != "Unknown":
                    logging.info(f"Updating OriginFaction for {name}: {current_origin}")
                    data["OriginFaction"] = current_origin
                    needs_save = True

                current_job = ctx_data.get("job", "None")
                if data.get("Job") in ("None", "Unknown") and current_job not in ("None", "Unknown"):
                    logging.info(f"Updating Job for {name}: {current_job}")
                    data["Job"] = current_job
                    needs_save = True

                # Force-save immediately when we correct previously-unknown metadata
                # (bypasses should_save_profile which would skip generic-content profiles)
                if needs_save:
                    save_character_data(storage_id, data)
        except Exception as e:
            logging.error(f"Error updating character metadata from context: {e}")

    if not data:
        # If we are only pre-checking for batching or similar, do not generate now
        if skip_generate:
            logging.debug(f"TRANS-PATH-1: {name} (skip_generate=True)")
            return {
                "ID": storage_id,
                "Name": name,
                "Race": ctx_data.get("race", "Unknown"),
                "Sex": ctx_data.get("gender", "Unknown"),
                "Faction": ctx_data.get("faction", "Unknown"),
                "OriginFaction": ctx_data.get("origin_faction", "Unknown"),
                "Job": ctx_data.get("job", "None"),
                "Personality": "A quiet traveler.",
                "Backstory": f"A {ctx_data.get('race', 'person')} from {ctx_data.get('faction', 'the borderlands')}.",
                "SpeechQuirks": "None.",
                "ConversationHistory": [],
                "Relation": 0,
                "_transient": True
            }

        # Generation Lock: Prevent parallel single gens for the same NPC
        with PROGRESS_LOCK:
            if storage_id in PROFILES_IN_PROGRESS:
                logging.debug(f"TRANS-PATH-2: {name} (Already in progress: {storage_id})")
                if transient_existing:
                    return transient_existing
                return {
                    "ID": storage_id,
                    "Name": name,
                    "Race": "Unknown",
                    "Sex": "Unknown",
                    "Faction": "Unknown",
                    "OriginFaction": "Unknown",
                    "Job": "None",
                    "Personality": "A quiet traveler.",
                    "Backstory": "Unknown.",
                    "SpeechQuirks": "None.",
                    "ConversationHistory": [],
                    "Relation": 0,
                    "_transient": True
                }
            PROFILES_IN_PROGRESS.add(storage_id)

        try:
            # Generate real profile only if we have full context.
            profile = generate_character_profile(name, context)
            if profile is None:
                logging.debug(f"TRANS-PATH-3: {name} (Generator returned None)")
                if transient_existing:
                    return transient_existing
                # Transient placeholder: NOT saved. Next call with full data will generate properly.
                return {
                    "ID": storage_id,
                    "Name": name,
                    "Race": "Unknown",
                    "Sex": "Unknown",
                    "Faction": "Unknown",
                    "OriginFaction": "Unknown",
                    "Job": "None",
                    "Personality": "A quiet traveler who keeps to themselves.",
                    "Backstory": "Their past is unclear.",
                    "SpeechQuirks": "Speaks sparingly.",
                    "ConversationHistory": [],
                    "Relation": 0,
                    "_transient": True
                }
            data = {
                "ID": storage_id,
                "Name": name,
                "Race": profile.get("Race", "Unknown"),
                "Sex": profile.get("Sex", "Unknown"),
                "Faction": profile.get("Faction", "Unknown"),
                "OriginFaction": profile.get("OriginFaction", "Unknown"),
                "Job": profile.get("Job", "None"),
                "Personality": profile.get("Personality", "Unknown"),
                "Backstory": profile.get("Backstory", "Unknown"),
                "SpeechQuirks": profile.get("SpeechQuirks", ""),
                "ConversationHistory": [],
                "Relation": 0
            }
            if transient_existing:
                data["ConversationHistory"] = list(transient_existing.get("ConversationHistory", []))
                data["Relation"] = transient_existing.get("Relation", 0)
        finally:
            with PROGRESS_LOCK:
                if storage_id in PROFILES_IN_PROGRESS:
                    PROFILES_IN_PROGRESS.remove(storage_id)

    # Enrich with world-index data (Persistence check)
    if name in WORLD_INDEX:
        data = {**data}  # shallow copy — avoids mutating the CHARACTER_CACHE reference
        if "ConversationHistory" in data:
            data["ConversationHistory"] = list(data["ConversationHistory"])
        data["SourcePlatoons"] = WORLD_INDEX[name]

    intrinsic_id = data.get("ID", storage_id)
    if should_save_profile(name, intrinsic_id, data):
        save_character_data(intrinsic_id, data)
    return data


def should_save_profile(name, storage_id, data):
    """Checks if we should save this profile, preventing generic clutter."""
    if not name or name in ("Unknown", "Someone"):
        return False

    personality = data.get("Personality", "").lower()
    is_generic_content = any(x in personality for x in ("unknown", "generic npc", "weary wanderer", "weary traveler"))
    has_history = len(data.get("ConversationHistory", [])) > 0

    # Rule 1: Generic with no history? Don't save.
    if is_generic_content and not has_history:
        return False

    return True


def load_existing_profile(storage_id, name=None) -> dict[str, Any]:
    """Load a profile from cache/disk without triggering generation."""
    with CACHE_LOCK:
        cached = CHARACTER_CACHE.get(storage_id)
        if cached:
            # Refresh insertion order (LRU)
            CHARACTER_CACHE.pop(storage_id, None)
            CHARACTER_CACHE[storage_id] = cached
            return dict(cached)

    cfg_path = _character_path(storage_id, name=name)
    legacy_path = _legacy_character_path(storage_id, name=name)
    history_path = _character_history_path(storage_id, name=name)

    # Try name-based paths first, then fall back to plain ID paths if missing
    if not os.path.exists(cfg_path) and not os.path.exists(legacy_path):
        old_cfg_path = _character_path(storage_id)
        old_legacy_path = _legacy_character_path(storage_id)
        if os.path.exists(old_cfg_path):
            cfg_path = old_cfg_path
            history_path = _character_history_path(storage_id)
        elif os.path.exists(old_legacy_path):
            legacy_path = old_legacy_path
        elif name is None and os.path.exists(CHARACTERS_DIR):
            # When callers only know the stable storage ID, locate the readable
            # Name__hash filename by its deterministic hash suffix.
            suffix = hashlib.blake2s(str(storage_id).encode("utf-8"), digest_size=6).hexdigest()
            cfg_matches = [fn for fn in os.listdir(CHARACTERS_DIR) if fn.endswith(f"__{suffix}.cfg")]
            json_matches = [fn for fn in os.listdir(CHARACTERS_DIR) if fn.endswith(f"__{suffix}.json")]

            if len(cfg_matches) == 1:
                cfg_path = os.path.join(CHARACTERS_DIR, cfg_matches[0])
                # Best effort to guess history path from config path stem
                hist_stem = cfg_matches[0].replace('.cfg', '')
                hist_dir = os.path.join(CHARACTERS_DIR, "history")
                history_path = os.path.join(hist_dir, f"{hist_stem}_History.txt")
            elif len(json_matches) == 1:
                legacy_path = os.path.join(CHARACTERS_DIR, json_matches[0])
            elif cfg_matches or json_matches:
                logging.warning(
                    f"load_existing_profile: ambiguous hash suffix for {storage_id} - skipping"
                )
                return {}

        if name and not os.path.exists(cfg_path) and not os.path.exists(legacy_path) and os.path.exists(CHARACTERS_DIR):
            # NEW FALLBACK: If recruiting shifted their faction (e.g. Nameless), the exact storage_id match drops.
            # We explicitly scan for their unmodified generated Name__ prefix to recover their original file.
            prefix = _clean_npc_name(name) + "__"
            fuzzy_cfg = [fn for fn in os.listdir(CHARACTERS_DIR) if fn.startswith(prefix) and fn.endswith(".cfg")]
            if len(fuzzy_cfg) == 1:
                cfg_path = os.path.join(CHARACTERS_DIR, fuzzy_cfg[0])
                hist_stem = fuzzy_cfg[0].replace('.cfg', '')
                history_path = os.path.join(CHARACTERS_DIR, "history", f"{hist_stem}_History.txt")
                logging.info(f"IDENTITY: Recovered recruited character {name} via file string fuzzy match ({fuzzy_cfg[0]})")
            elif len(fuzzy_cfg) > 1:
                logging.warning(f"IDENTITY: Ambiguous fallback file match for {name}: {fuzzy_cfg}. Continuing with new profile generation.")

    data = None
    if os.path.exists(cfg_path):
        try:
            data = dack.load(cfg_path)
            if "Relation" in data:
                try:
                    data["Relation"] = str(int(data["Relation"]))
                except:
                    pass
            if "Traits" in data and isinstance(data["Traits"], str):
                import ast
                try:
                    data["Traits"] = ast.literal_eval(data["Traits"])
                except:
                    data["Traits"] = ""
        except Exception as e:
            logging.error(f"Error loading CFG {cfg_path}: {e}")
            return {}
    elif os.path.exists(legacy_path):
        try:
            with open(legacy_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return {}

    if not data:
        return {}

    if "ID" not in data:
        data["ID"] = storage_id
    elif data.get("ID") != storage_id:
        logging.debug(f"IDENTITY: Retaining intrinsic ID {data['ID']} over requested {storage_id}")

    # Load history
    if "ConversationHistory" not in data:
        if os.path.exists(history_path):
            try:
                with open(history_path, "r", encoding="utf-8") as f:
                    lines = [ln.strip() for ln in f.read().split('\n') if ln.strip()]
                    data["ConversationHistory"] = str(lines)
            except Exception:
                data["ConversationHistory"] = ""
        else:
            data["ConversationHistory"] = ""

    return data


def profile_needs_upgrade(data):
    """Return True when a saved profile is only a transient placeholder."""
    return bool(data and data.get("_transient"))


def save_character_data(storage_id, data):
    cfg_path = _character_path(storage_id, name=data.get("Name") if data else None)
    history_path = _character_history_path(storage_id, name=data.get("Name") if data else None)

    # Global safety truncation
    if data and "ConversationHistory" in data and len(data["ConversationHistory"]) > 45:
        data["ConversationHistory"] = data["ConversationHistory"][-45:]

    try:
        # Separate ConversationHistory from static config
        history_list = data.pop("ConversationHistory", [])

        # Save static config as CFG
        dack.save(data, cfg_path)

        # Restore ConversationHistory to the python object so server logic still has it
        data["ConversationHistory"] = history_list

        # Save history list as flat TXT
        with open(history_path, "w", encoding="utf-8") as f:
            f.write("\n".join(history_list))

        # Only update cache after a successful disk write so RAM and disk stay in sync
        with CACHE_LOCK:
            CHARACTER_CACHE.pop(storage_id, None)  # Refresh insertion order
            CHARACTER_CACHE[storage_id] = data
            if len(CHARACTER_CACHE) > 200:
                oldest = next(iter(CHARACTER_CACHE))
                CHARACTER_CACHE.pop(oldest, None)

        # Cleanup any stale duplicate files with out-of-date names
        _cleanup_stale_same_hash_files(storage_id, cfg_path, ext=".cfg")
        _cleanup_stale_same_hash_files(storage_id, history_path, ext="_History.txt")  # Handles history files too

    except Exception as e:
        logging.error(f"Error saving character {storage_id}: {e}")


def extract_id_from_context(context_json):
    if not context_json:
        return None
    try:
        context_json = _parse_context_dict(context_json)
        if isinstance(context_json, dict):
            # Prefer normalized persistent identity when available.
            persistent_id = context_json.get('persistent_id')
            if _is_strong_uid(persistent_id):
                return persistent_id
            return (
                context_json.get('runtime_id')
                or context_json.get('id')
                or context_json.get('ID')
                or context_json.get('storage_id')
            )
    except:
        pass
    return None


def make_storage_id(name, faction=None, context={}, runtime_id=""):
    """Build a collision-safe storage ID.
    With the transition to strict UUID tracking, this pipeline exclusively passes the native
    Kenshi Object UUID block up to the caller cleanly, dropping the legacy string suffixes.
    """
    uid = context.get('storage_id', context.get('persistent_id', "")) if isinstance(context, dict) else ""
    if _is_strong_uid(uid):
        return uid
    if _is_strong_uid(runtime_id):
        return runtime_id

    # Legacy fallback for backward compatibility (during mid-migration only)
    clean = str(name).strip()
    if '|' in clean:
        clean = clean.split('|')[0].strip()
    f = (faction or "").strip()
    if f and f not in ("Unknown", "None", "No Faction", ""):
        f_slug = re.sub(r'\s+', '_', re.sub(r'[^\w\s-]', '', f).strip())
        if f_slug:
            n_slug = re.sub(r'\s+', '_', clean)
            return f"{n_slug}_{f_slug}"
    return clean


def _safe_char_filename(storage_id):
    """Filesystem-safe stem for a character storage_id.
    Matches the sanitization used by save_character_data().
    """
    return "".join([c for c in str(storage_id) if c.isalnum() or c in (' ', '_', '-')]).strip()


def _cleanup_stale_same_hash_files(storage_id, canonical_path, ext=".cfg"):
    """Remove stale same-ID files with an outdated name prefix after a successful save."""
    if not os.path.exists(CHARACTERS_DIR):
        return

    suffix = _safe_char_filename(str(storage_id))
    canonical_name = os.path.basename(canonical_path)

    for stale_name in os.listdir(CHARACTERS_DIR):
        if not stale_name.endswith(f"__{suffix}{ext}") or stale_name == canonical_name:
            continue

        stale_path = os.path.join(CHARACTERS_DIR, stale_name)
        try:
            # For CFG we must load via dack to check ID
            if ext == ".cfg":
                stale_data = dack.load(stale_path)
            else:
                with open(stale_path, "r", encoding="utf-8") as stale_fh:
                    stale_data = json.load(stale_fh)

            if str(stale_data.get("ID", "")) != str(storage_id):
                continue
            os.remove(stale_path)
            logging.debug(f"CLEANUP: removed stale {stale_name} (superseded by {canonical_name})")
        except Exception as e:
            logging.warning(f"CLEANUP: could not remove stale {stale_name}: {e}")


def _legacy_character_path(storage_id, name=None):
    """Full path to a character's legacy JSON file."""
    if name:
        name_slug = _safe_char_filename(str(name))
        if name_slug:
            suffix = hashlib.blake2s(str(storage_id).encode("utf-8"), digest_size=6).hexdigest()
            return os.path.join(CHARACTERS_DIR, f"{name_slug}__{suffix}.json")
    return os.path.join(CHARACTERS_DIR, f"{_safe_char_filename(storage_id)}.json")


def _character_path(storage_id, name=None):
    """Full path to a character's Dack CFG file in CHARACTERS_DIR."""
    if name:
        name_slug = _safe_char_filename(str(name))
        if name_slug:
            id_slug = _safe_char_filename(str(storage_id))
            return os.path.join(CHARACTERS_DIR, f"{name_slug}__{id_slug}.cfg")
    return os.path.join(CHARACTERS_DIR, f"{_safe_char_filename(storage_id)}.cfg")


def _character_history_path(storage_id, name=None):
    """Full path to a character's history TXT file."""
    hist_dir = os.path.join(CHARACTERS_DIR, "history")
    os.makedirs(hist_dir, exist_ok=True)
    if name:
        name_slug = _safe_char_filename(str(name))
        if name_slug:
            id_slug = _safe_char_filename(str(storage_id))
            return os.path.join(hist_dir, f"{name_slug}__{id_slug}_History.txt")
    return os.path.join(hist_dir, f"{_safe_char_filename(storage_id)}_History.txt")


@app.route('/log', methods=['POST'])
def log_dialogue():
    data = request.json
    if not data:
        return jsonify({"status": "error"}), 400

    npc_name = data.get('npc', 'Someone')
    player_name = data.get('player', 'Drifter')
    player_message = data.get('message', '')
    npc_response = data.get('response', '')
    context = data.get('context', '')
    npc_id = extract_id_from_context(context)

    char_data = get_character_data(npc_name, context, char_id=npc_id)

    # CRITICAL FIX: Use the stable ID from char_data, NOT the volatile serial ID
    storage_id = char_data.get("ID") or npc_name

    time_prefix = get_current_time_prefix()

    if player_message:
        char_data["ConversationHistory"].append(f"{time_prefix}{player_name}: {player_message}")
        record_event_to_history("DIALOGUE", player_name, npc_name, player_message)

    if npc_response:
        char_data["ConversationHistory"].append(f"{time_prefix}{npc_name}: {npc_response}")
        record_event_to_history("DIALOGUE", npc_name, player_name, npc_response)

    if len(char_data["ConversationHistory"]) > 45:
        char_data["ConversationHistory"] = char_data["ConversationHistory"][-45:]

    if should_save_profile(npc_name, storage_id, char_data):
        save_character_data(storage_id, char_data)
    logging.info(f"LOG [{npc_name} ({storage_id})]: {npc_response}")
    return jsonify({"status": "ok"})


@app.route('/get_unique_identity', methods=['POST'])
def get_unique_identity():
    data = request.json
    if not data:
        return jsonify({"status": "error"}), 400

    current_name = data.get('name', 'Someone')
    race = data.get('race', 'Human')
    gender = data.get('gender', 'Neutral')

    # Check if this name is generic
    is_generic = is_npc_name_generic(current_name)

    if is_generic:
        new_name = generate_unique_lore_name(gender=gender)
        logging.info(f"IDENTITY: Assigning unique {gender} name '{new_name}' to generic NPC '{current_name}'")
        return jsonify({
            "status": "rename",
            "new_name": new_name
        })

    return jsonify({"status": "ok", "name": current_name})


@app.route('/get_batch_identities', methods=['POST'])
def get_batch_identities():
    batch = request.json  # Expect list of {serial, name, gender, race}
    if not batch or not isinstance(batch, list):
        return jsonify({"status": "error", "message": "Invalid batch format"}), 400
    enable_animal_renamer = load_settings().get("enable_animal_renamer", True)

    results = []
    rename_count = 0
    for item in batch:
        serial = item.get('serial')
        persistent_id = item.get('persistent_id', '')
        current_name = str(item.get('name', 'Someone')).strip()
        gender = item.get('gender', 'Neutral')
        race = item.get('race', 'Unknown')

        is_generic = is_npc_name_generic(current_name)

        if is_generic:
            is_humanoid = False
            for hr in ["greenlander", "scorchlander", "shek", "skeleton", "hive", "human"]:
                if hr in race.lower():
                    is_humanoid = True
                    break

            if not enable_animal_renamer and not is_humanoid:
                logging.info(f"IDENTITY-BATCH: Skipping animal/machine rename for '{current_name}' (race: {race}) due to settings.")
                results.append({"serial": serial, "status": "ok"})
                continue

            new_name = generate_unique_lore_name(gender=gender)
            results.append({
                "serial": serial,
                "status": "rename",
                "new_name": new_name
            })
            logging.info(f"IDENTITY-BATCH: Assigning unique name '{new_name}' to generic NPC '{current_name}' (serial {serial})")
            rename_count += 1
        else:
            results.append({
                "serial": serial,
                "status": "ok"
            })

    if results:
        logging.info(f"IDENTITY: Batch processed {len(results)} items. Renamed: {rename_count}")
    return jsonify(results)


@app.route('/rename', methods=['POST'])
def rename_character():
    data = request.json
    if not data:
        return jsonify({"status": "error"}), 400

    old_name = data.get('old_name')
    new_name = data.get('new_name')
    context = data.get('context', '')

    if not old_name or not new_name:
        return jsonify({"status": "error", "message": "Missing names"}), 400

    logging.info(f"RENAME: Attempting to rename '{old_name}' to '{new_name}'")

    # 1. Resolve existing profile (do not generate if missing)
    char_data = get_character_data(old_name, context, skip_generate=True)
    if char_data.get("_transient"):
        logging.info(f"RENAME: No persistent profile for {old_name}, renaming aborted (will create new on next chat)")
        return jsonify({"status": "ok", "message": "No profile to rename"})

    old_id = char_data.get("ID")
    if not old_id:
        return jsonify({"status": "error", "message": "Profile ID resolution failed"}), 500

    # 2. Update internal Name
    char_data["Name"] = new_name

    # 3. Handle File Renaming
    # Find the old file — try new Name__hash format first, fall back to legacy plain format.
    old_path = _character_path(old_id, name=old_name)
    if not os.path.exists(old_path):
        old_path = _character_path(old_id)

    if _is_strong_uid(old_id):
        # Persistent ID: storage_id is stable — only the filename prefix changes.
        new_id = old_id
        new_path = _character_path(new_id, name=new_name)
    else:
        # Legacy name-based ID: rebuild with the new name while preserving faction.
        new_id = make_storage_id(new_name, char_data.get("Faction", ""))
        new_path = _character_path(new_id, name=new_name)

    if os.path.exists(old_path) and not os.path.exists(new_path):
        try:
            char_data["ID"] = new_id
            save_character_data(new_id, char_data)  # Handles generating history txt and config cfg

            try:
                os.remove(old_path)
            except:
                pass

            # The old history and legacy files
            old_hist_path = _character_history_path(old_id, name=old_name)
            if os.path.exists(old_hist_path):
                try:
                    os.remove(old_hist_path)
                except:
                    pass
            else:
                old_hist_path2 = _character_history_path(old_id)
                try:
                    os.remove(old_hist_path2)
                except:
                    pass

            legacy_json = _legacy_character_path(old_id, name=old_name)
            if os.path.exists(legacy_json):
                try:
                    os.remove(legacy_json)
                except:
                    pass
            else:
                legacy_json2 = _legacy_character_path(old_id)
                try:
                    os.remove(legacy_json2)
                except:
                    pass

            logging.info(f"RENAME: Migrated profile file {old_id} -> {new_id}")
            return jsonify({"status": "ok", "new_id": new_id})
        except Exception as e:
            logging.error(f"RENAME: Failed to migrate profile file: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

    # Fallback: Just update internal data
    char_data["ID"] = new_id
    save_character_data(new_id, char_data)
    return jsonify({"status": "ok"})


@app.route('/ambient', methods=['POST'])
def ambient_event():
    debug_logger.debug("ROUTE: /ambient [POST]")
    data = request.json
    if not data:
        return jsonify({"status": "error"}), 400

    npcs_data = data.get('npcs', [])
    player_name = data.get('player', 'Drifter')

    logging.info(f"RADIANT: Received ambient banter request ({len(npcs_data)} NPCs nearby)")

    if not npcs_data:
        return jsonify({"status": "ignore"})
    if direct_chat_active():
        logging.info("RADIANT: Deferred/ignored because a direct chat is active.")
        return jsonify({"status": "ignore"})

    # Build profiles for nearby characters
    char_profiles = ""
    name_to_id = {}

    # Filter out recently-used speakers so one NPC doesn't dominate every bark.
    candidate_npcs = []
    for npc in npcs_data:
        name = npc.get('name', 'Unknown') if isinstance(npc, dict) else str(npc)
        explicit_id = None
        context = None
        if isinstance(npc, dict):
            explicit_id = npc.get("storage_id") or npc.get("id")
            context = npc
        if not ambient_candidate_allowed(name=name, context=context, explicit_id=explicit_id):
            continue
        candidate_npcs.append(npc)

    npc_limit = candidate_npcs[:12]  # Small pool keeps ambient light and more varied
    if len(npc_limit) < 2:
        logging.info("RADIANT: Skipping ambient - insufficient eligible speakers after cooldown filters.")
        return jsonify({"status": "ignore"})

    # 1. Pre-check for missing profiles to batch generate
    missing_npcs = []
    for npc in npc_limit:
        if isinstance(npc, dict):
            name = npc.get('name', 'Unknown')
            if name.lower() in CANON_CHARACTERS or "your squad" in name.lower():
                continue

            # Pre-check for missing profiles to batch generate (skip individual generation)
            info = get_character_data(name, context=json.dumps(npc), skip_generate=True)
            if info.get("_transient"):
                missing_npcs.append(npc)

    if missing_npcs:
        queue_batch_profile_generation(missing_npcs)

    # 2. Extract and format profile summary for banter call (parallelised)
    def _fetch_npc_profile(npc):
        if isinstance(npc, dict):
            name = npc.get('name', 'Unknown')
            nid = npc.get('id', 0)
            d = get_character_data(name, context=json.dumps(npc), skip_generate=True)
            health = npc.get('health', 'Healthy')
            gear = npc.get('equipment', 'nothing notable')
            profile_line = f"\n- {name}|{nid} ({npc.get('gender')} {npc.get('race')}, {npc.get('faction')}) | Health: {health} | Gear: {gear} | Personality: {d.get('Personality', 'A traveler.')}"
        else:
            name = npc
            nid = 0
            d = get_character_data(npc, "", skip_generate=True)
            profile_line = f"\n- {npc} (A traveler): {d.get('Personality', 'A traveler.')}"
        return name, nid, d, profile_line

    recent_dialogue = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        # submit preserves order via index — collect results in original NPC order
        futures = [pool.submit(_fetch_npc_profile, npc) for npc in npc_limit]
        for future in futures:
            name, nid, d, profile_line = future.result()
            name_to_id[name] = nid
            if d.get("ConversationHistory"):
                recent_dialogue.extend(d["ConversationHistory"][-15:])
            char_profiles += profile_line

    # Normalize a ConversationHistory line to "Speaker: message" format,
    # stripping timestamps, (Overheard) prefix, and [ACTION: TAG] tags.
    def _normalize(line):
        k = re.sub(r'^\[Day[^\]]+\]\s*(?:\(Overheard\)\s*)?', '', line)
        k = re.sub(r'\s*\[ACTION:[^\]]*\]', '', k)
        return k.strip()

    # 1. Pull from individual NPC memories, normalized to "Speaker: message"
    all_history = [_normalize(line) for line in recent_dialogue]

    # 2. Extract global banter/chat history from EVENT_HISTORY for the current location
    location = ""
    if PLAYER_CONTEXT:
        env = PLAYER_CONTEXT.get("environment", {})
        location = env.get("town_name", "") if isinstance(env, dict) else ""

    banter_events = []
    for evt in reversed(EVENT_HISTORY):
        if (" [BANTER] " in evt or " [CHAT] " in evt):
            if not location or f"@ {location}" in evt or "@" not in evt:
                if ": " in evt:
                    msg_part = evt.split(": ", 1)[1]
                    match = re.search(r'\]\s*(.*?)\s*(?:\(.*?\))?\s*->', evt)
                    speaker = match.group(1).strip() if match else None
                    banter_events.append(f"{speaker}: {msg_part}" if speaker else msg_part)
        if len(all_history) + len(banter_events) > 100:
            break
    all_history.extend(reversed(banter_events))

    # Deduplicate, keeping most recent on collision, then take last 80
    seen_history = set()
    unique_history = []
    for line in reversed(all_history):
        if line not in seen_history:
            unique_history.append(line)
            seen_history.add(line)
    unique_history = list(reversed(unique_history))[-80:]

    history_block = ""
    if unique_history:
        history_block = "\nRECENT LOCAL DIALOGUE (DO NOT REPEAT TOPICS OR JOKES FROM HERE):\n" + "\n".join(unique_history)

    ambient_npc_data = None
    if npc_limit and isinstance(npc_limit[0], dict):
        ambient_npc_data = get_character_data(npc_limit[0].get('name', 'Unknown'), "", skip_generate=True)

    world_lore = fetch_dynamic_lore(ambient_npc_data)
    events_str = build_events_block()

    ambient_system_prompt = f"""[SYSTEM CORE]
You are generating a short, atmospheric back-and-forth conversation (banter) between NPCs in the brutal world of Kenshi.

WORLD LORE:
{world_lore}

{events_str}

NEARBY CHARACTERS:
{char_profiles}

{history_block}

INSTRUCTIONS:
1. Select 2 or 3 characters from the list to have a short conversation.
2. Keep it brief: total 3-6 lines. Each participant should speak at least once, and no one speaker should dominate the exchange.
3. DO NOT include the Player as a speaker and DO NOT let the Player participate.
4. The topic should be grounded in the harsh reality of Kenshi: local rumors, faction politics, the weather, gear maintenance, hunger, or a passing, often cynical comment about the 'drifter' (player) nearby.
5. Format MUST be 'Name|ID: Message' (e.g., 'Lungrot|1234: Wheeze...').
6. Only use characters from the NEARBY list.
7. Use the EXACT Name and ID strings provided in the list for the 'Name|ID' portion.
8. DO NOT use [ACTION] tags or any bracketed text. Radiant mode is for atmospheric dialogue only.
9. CRITICAL: Do NOT repeat topics, lines, or jokes found in the RECENT LOCAL DIALOGUE section. Talk about something new.
10. WORLD-CENTRIC: Remember that in Kenshi, the player is NOT the center of the universe. NPCs have their own lives, problems, and social circles. They should speak to and about each other about what is going on around them more often than they speak about the player.
"""

    messages = [
        {"role": "system", "content": ambient_system_prompt},
        {"role": "user", "content": "The world is quiet. Generate a radiant interaction."}
    ]

    content = call_llm(messages, max_tokens=400)
    if content:
        # Strip any stray [ACTION] tags that the LLM might hallucinated despite instructions
        content = re.sub(r'\[\s*[A-Z_]+(?::\s*[^\]]+)?\s*\]', '', content).strip()

        # Basic cleaning - remove quotes
        content = content.replace('"', '').strip()

        # Post-process to ensure IDs are present
        lines = []
        for line in content.split('\n'):
            line = line.strip()
            if not line:
                continue

            if ':' in line:
                header, msg = line.split(':', 1)
                name_part = header.split('|')[0].strip()

                # Hallucination check
                if name_part.lower() == player_name.lower():
                    continue

                # Ensure ID is present even if LLM forgot
                if '|' not in header:
                    if name_part in name_to_id:
                        header = f"{name_part}|{name_to_id[name_part]}"

                lines.append(f"{header.strip()}: {msg.strip()}")
            elif '|' in line and len(line) < 100:  # Maybe just a name header LLM hallucinated
                continue
            else:
                # Append raw text if no colon, though prompt asks for colon
                if len(line) > 5:
                    lines.append(line)

        final_text = "\n".join(lines)

        # 5. Optimized History Update (One save per NPC)
        # Pre-load character memories for the nearby group (only those in npc_limit)
        memories = {}
        speaker_names = set()
        for npc_obj in npc_limit:
            name = npc_obj.get('name') if isinstance(npc_obj, dict) else npc_obj
            # Use skip_generate=True here just in case, though they should be generated by now
            memories[name] = get_character_data(name, context=json.dumps(npc_obj) if isinstance(npc_obj, dict) else "", skip_generate=True)

        for line in lines:
            if ':' in line:
                header, msg = line.split(':', 1)
                speaker_name = header.split('|')[0].strip()
                speaker_names.add(speaker_name)

                # Also log to global history for narrative synthesis
                speaker_faction = memories.get(speaker_name, {}).get("Faction", "None")
                record_event_to_history("BANTER", speaker_name, "Nearby", msg.strip(), actor_faction=speaker_faction)

        mark_ambient_speakers(
            (speaker_name, name_to_id.get(speaker_name), memories.get(speaker_name))
            for speaker_name in speaker_names
        )

        logging.info(f"AMBIENT BARK:\n{final_text}")
        return jsonify({"status": "ok", "text": final_text})

    return jsonify({"status": "none"})


@app.route('/ping', methods=['GET', 'POST'])
def ping():
    return jsonify({"status": "ok"})


@app.route('/test_llm', methods=['GET', 'POST'])
def test_llm():
    """Verify both server and LLM connectivity."""
    try:
        messages = [{"role": "user", "content": "Keep your response extremely short. Reply with the word: Success"}]
        response = call_llm(messages, max_tokens=10, temperature=0.7)
        if response:
            logging.info(f"TEST_LLM: Success! Response: {response}")
            # Ensure fixed key order and no extra spaces for C++ parsing
            return '{"status":"ok","llm":"ok","response":"' + response.replace('"', "'") + '"}'
        else:
            logging.error("TEST_LLM: call_llm returned None.")
            return '{"status":"ok","llm":"error","message":"Global LLM call failed."}'
    except Exception as e:
        logging.error(f"TEST_LLM: Exception during test: {e}")
        return jsonify({"status": "error", "message": str(e)})


@app.route('/lore_debug', methods=['GET', 'POST'])
def lore_debug():
    """Debug endpoint: returns the lore sections that would be injected for a given NPC.
    Accepts optional JSON body: { "faction": "...", "race": "...", "religion": "...",
                                   "platoons": [...], "town": "...", "biome": "..." }
    Can also be called with no body (GET) to see Global-only lore.
    Example: curl http://127.0.0.1:5000/lore_debug -H "Content-Type: application/json"
             -d '{"faction":"Shek Kingdom","race":"Shek","religion":"Devoted to Kral"}'
    """
    data = request.get_json(silent=True) or {}
    # Build a synthetic npc_data from request params
    npc_data = {
        "Faction": data.get("faction", ""),
        "Race": data.get("race", ""),
        "SourcePlatoons": data.get("platoons", []),
        "Traits": {"Religion": data.get("religion", "")},
    }
    # Optionally inject location context without overwriting global PLAYER_CONTEXT
    town = data.get("town", "")
    biome = data.get("biome", "")

    env_override = {"town_name": town, "biome": biome} if (town or biome) else None

    lore_output = fetch_dynamic_lore(npc_data, env_override=env_override)

    # Build a diagnostic summary alongside the output
    search_terms = ["Global"]
    faction = npc_data.get("Faction", "")
    if faction and faction != "Unknown":
        search_terms.append(faction)
    search_terms.extend(p for p in npc_data.get("SourcePlatoons", []) if p)
    race = npc_data.get("Race", "")
    if race and race != "Unknown":
        search_terms.append(race)
    religion = npc_data.get("Traits", {}).get("Religion", "")
    if religion and religion not in ("N/A", "Unknown", "Hive-Bound"):
        search_terms.append(religion)
    if town:
        search_terms.append(town)
    if biome:
        search_terms.append(biome)

    matched_ids = [
        chunk["id"] for chunk in LORE_DATABASE
        if any(t in chunk.get("tags", []) for t in search_terms)
    ]

    return jsonify({
        "search_terms": search_terms,
        "matched_chunks": matched_ids,
        "chunk_count": len(matched_ids),
        "total_chars": len(lore_output),
        "lore_output": lore_output,
    })


@app.route('/record_major_event', methods=['POST'])
def record_major_event():
    """Append a major historical event to campaign_chronicle.json.
    Required body fields: summary (str), factions_full (list), radius (str), location (str).
    Optional: location_region (str), summary_vague (str), tags (list), day (int).
    """
    logging.info("ROUTE: /record_major_event [POST]")
    data = request.json or {}

    summary = data.get("summary", "").strip()
    factions_full = data.get("factions_full", [])
    radius = data.get("radius", "")
    location = data.get("location", "").strip()

    if not summary:
        return jsonify({"status": "error", "message": "Missing required field: summary"}), 400
    if not isinstance(factions_full, list):
        return jsonify({"status": "error", "message": "factions_full must be a list"}), 400
    if radius not in ("local", "regional", "global"):
        return jsonify({"status": "error", "message": "radius must be local|regional|global"}), 400
    if not location:
        return jsonify({"status": "error", "message": "Missing required field: location"}), 400

    event = {
        "summary": summary,
        "factions_full": factions_full,
        "radius": radius,
        "location": location,
        "location_region": data.get("location_region", "").strip(),
        "summary_vague": data.get("summary_vague", "").strip(),
        "tags": data.get("tags", []),
        "timestamp": time.time(),
    }
    if "day" in data:
        try:
            event["day"] = int(data["day"])
        except (TypeError, ValueError):
            pass

    cdir = get_campaign_dir()
    events = load_chronicle(cdir)
    events.append(event)
    events = save_chronicle(cdir, events)

    logging.info(
        f"CHRONICLE: Recorded '{summary[:60]}' "
        f"(radius={radius}, factions_full={factions_full})"
    )
    return jsonify({"status": "ok", "total_events": len(events)})


@app.route('/regenerate_profile', methods=['POST'])
def regenerate_profile_route():
    """Evolves an NPC's Personality, Backstory, and SpeechQuirks based on their
    conversation history with the player. Preserves all other profile fields including Traits.
    POST body: {"sid": "<npc_storage_id>"}
    """
    logging.info("ROUTE: /regenerate_profile [POST]")
    data: dict[str, str] = request.json or {}
    sid = data.get("sid")
    if not sid or sid == None:
        return jsonify({"status": "error", "message": "Missing NPC ID (sid)"}), 400

    # Resolve by storage ID first so Name__hash filenames can be found without
    # abusing the storage ID as a display name.
    char_data = load_existing_profile(sid)
    if not char_data:
        return jsonify({"status": "error", "message": "Profile not found"}), 404

    real_name = char_data.get("Name", sid)
    real_faction = char_data.get("Faction", "")
    char_data = get_character_data(real_name, {"faction": real_faction, "persistent_id": sid}, char_id=sid, skip_generate=True)
    if not char_data:
        return jsonify({"status": "error", "message": "Profile not found"}), 404

    history = char_data.get("ConversationHistory", [])
    if not history:
        return jsonify({"status": "error",
                        "message": "No conversation history. Talk to this NPC first."}), 400

    name = char_data.get("Name", sid)
    race = char_data.get("Race", "Unknown")
    faction = char_data.get("Faction", "Unknown")
    personality = char_data.get("Personality", "Unknown")
    backstory = char_data.get("Backstory", "Unknown")

    # Cap history sent to LLM to avoid token overflow; full history stays in the file
    history_block = "\n".join(history[-80:])

    system_msg = ("You are an expert on Kenshi lore and character growth. "
                  "You write NPC profiles in a grounded, cynical tone. "
                  "You ALWAYS respond ONLY with a valid JSON object.")
    user_msg = f"""Rewrite the Personality and Backstory for the Kenshi NPC "{name}" based on their conversation history.

CURRENT PROFILE:
Personality: {personality}
Backstory: {backstory}
Race: {race} | Faction: {faction}

CONVERSATION HISTORY:
{history_block}

Instructions:
- EVOLVE the profile to reflect their experiences with the player.
- Maintain the Kenshi world's grounded, cynical tone.
- If they've bonded with the player, reflect that. If there was conflict, reflect that too.
- Response MUST be ONLY a JSON object with keys: "Personality", "Backstory", "SpeechQuirks"."""

    logging.info(f"REGEN: Evolving profile for {name} ({len(history)} history lines)...")

    try:
        response_text = call_llm(
            [{"role": "system", "content": system_msg},
             {"role": "user", "content": user_msg}],
            max_tokens=1500, temperature=0.7
        )

        if not response_text or "Empty Response" in response_text:
            return jsonify({"status": "error",
                            "message": "LLM returned an empty response. Try again or use an NPC with fewer memories."}), 500

        result = robust_json_parse(response_text)
        if not result:
            logging.error(f"REGEN: JSON parse failed for {name}. Raw: {response_text[:300]}")
            return jsonify({"status": "error", "message": "LLM response was not valid JSON. Try again."}), 500

        # Update only the three narrative fields; Traits and all metadata are preserved
        char_data["Personality"] = result.get("Personality", personality)
        char_data["Backstory"] = result.get("Backstory", backstory)
        char_data["SpeechQuirks"] = result.get("SpeechQuirks", char_data.get("SpeechQuirks", ""))

        save_character_data(sid, char_data)
        logging.info(f"REGEN: Successfully evolved profile for {name}.")
        return jsonify({"status": "ok", "message": f"Successfully evolved {name}'s profile."})

    except Exception as e:
        logging.error(f"REGEN: Failed for {sid}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/chat', methods=['POST'])
def chat():
    global CURRENT_MODEL_KEY
    data = request.json
    debug_logger.debug(f"ROUTE: /chat [POST] (Request details omitted for security)")
    if not data:
        return jsonify({"text": "Error: No JSON data provided"}), 400

    # Parse comma-separated NPC names and stabilize IDs
    raw_npc = data.get('npc', 'Someone')
    raw_npcs = data.get('npcs', [])

    # Stabilize name-to-id mapping for resolution accuracy
    name_to_id = {}

    def register(raw):
        if not raw:
            return ""
        raw_str = str(raw).strip()
        clean = _clean_npc_name(raw_str)
        if not clean:
            return ""
        name_to_id[clean] = raw_str if '|' in raw_str else clean
        return clean

    primary_npc = register(raw_npc)
    npcs = [register(n) for n in raw_npcs]

    # Ensure primary_npc is logic-ready
    player_name = data.get('player', 'Drifter')
    mode = data.get('mode', 'talk')

    # 3. Update LIVE_CONTEXTS from provided nearby data (ensures reactions work immediately)
    nearby = data.get('nearby', [])
    if nearby:
        for n in nearby:
            name = _clean_npc_name(n.get('name'))
            if name:
                n_ctx = _parse_context_dict(n, fallback_name=name)
                runtime_id = str(n_ctx.get('runtime_id') or n.get('runtime_id') or n_ctx.get('id') or n.get('id') or "").strip() or None
                persistent_id = str(n_ctx.get('persistent_id') or n.get('persistent_id') or "").strip() or None
                stable_storage_id = n_ctx.get('storage_id')
                _, _existing = resolve_live_context(name=name, context=n_ctx, explicit_id=(runtime_id or stable_storage_id))
                self_marker = runtime_id or stable_storage_id or name
                live_payload = {
                    "id": runtime_id,
                    "runtime_id": runtime_id,
                    "persistent_id": persistent_id,
                    "storage_id": stable_storage_id,
                    "name": name,
                    "race": n_ctx.get('race', 'Unknown'),
                    "faction": n_ctx.get('faction', 'Unknown'),
                    "gender": n_ctx.get('gender', 'Unknown'),
                    "nearby": [
                        x for x in nearby
                        if (
                            str(x.get('runtime_id') or x.get('id') or "").strip()
                            or _preferred_storage_id(
                                _clean_npc_name(x.get('name')),
                                x.get('faction') or x.get('Faction') or x.get('origin_faction') or x.get('OriginFaction'),
                                x.get('storage_id'),
                                uid=x.get('persistent_id')
                            )
                            or _clean_npc_name(x.get('name'))
                        ) != self_marker
                    ],
                    "player_dist": n_ctx.get('dist', 999.0),
                    "is_trader": (_existing or {}).get("is_trader", False),
                    "in_shop": (_existing or {}).get("in_shop", False),
                }
                store_live_context(live_payload, name=name, explicit_id=(runtime_id or stable_storage_id))
                name_to_id[name] = f"{name}|{runtime_id}" if runtime_id else name
                continue

    # Filter player out of available NPCs to avoid hallucinated PC responses
    npcs = [n for n in npcs if n != player_name]
    if primary_npc == player_name and len(npcs) > 0:
        primary_npc = npcs[0]

    player_message = data.get('message', '')
    direct_chat_lease = _DirectChatLease()

    # --- TEST COMMAND INTERCEPT ---
    if player_message.startswith('/'):
        cmd_parts = player_message[1:].split(' ', 1)
        cmd = cmd_parts[0].lower()
        args = cmd_parts[1].strip() if len(cmd_parts) > 1 else ""

        test_action = None
        if cmd == "help" or cmd == "commands":
            help_text = "[DEBUG] Available test commands:\n" + \
                        "/take, /attack, /follow, /idle, /patrol, /join, /leave, /free, /breakout,\n" + \
                        "/move, /movefast, /home, /shop, /raid [Town], /travel [Town], /medic, /rescue, /repair,\n" + \
                        "/notify [msg], /give_cats [n], /take_cats [n], /drop [item],\n" + \
                        "/take_item [item], /spawn [Templ|Name|Desc], /relations [Fact] [n], /task [TASK]"
            return jsonify({"text": help_text, "actions": []}), 200

        if cmd == "attack":
            test_action = "[ATTACK]"
        elif cmd == "follow":
            test_action = "[ACTION: FOLLOW_PLAYER]"
        elif cmd == "idle":
            test_action = "[ACTION: IDLE]"
        elif cmd == "patrol":
            test_action = "[ACTION: PATROL_TOWN]"
        elif cmd == "join":
            test_action = "[ACTION: JOIN_PARTY]"
        elif cmd == "leave":
            test_action = "[ACTION: LEAVE]"
        elif cmd == "free":
            test_action = "[ACTION: FREE_PLAYER]"
        elif cmd == "breakout":
            test_action = "[ACTION: BREAKOUT_PLAYER]"
        elif cmd == "move":
            test_action = "[ACTION: MOVE_ON_FREE_WILL]"
        elif cmd == "movefast":
            test_action = "[ACTION: MOVE_ON_FREE_WILL_FAST]"
        elif cmd == "home":
            test_action = "[ACTION: GO_HOMEBUILDING]"
        elif cmd == "shop":
            test_action = "[ACTION: STAND_AT_SHOPKEEPER_NODE]"
        elif cmd == "raid":
            test_action = f"[ACTION: RAID_TOWN: {args}]"
        elif cmd == "travel":
            test_action = f"[ACTION: TRAVEL_TO_TARGET_TOWN: {args}]"
        elif cmd == "medic":
            test_action = "[ACTION: JOB_MEDIC]"
        elif cmd == "rescue":
            test_action = "[ACTION: FIND_AND_RESCUE]"
        elif cmd == "repair":
            test_action = "[ACTION: JOB_REPAIR_ROBOT]"
        elif cmd == "notify":
            test_action = f"[ACTION: NOTIFY: {args}]"
        elif cmd == "give_cats":
            test_action = f"[ACTION: GIVE_CATS: {args}]"
        elif cmd == "take_cats":
            test_action = f"[ACTION: TAKE_CATS: {args}]"
        elif cmd == "take_item":
            test_action = f"[ACTION: TAKE_ITEM: {args}]"
        elif cmd == "take":
            inv = PLAYER_CONTEXT.get("inventory", [])
            if inv:
                item_name = inv[0].get("name", "Unknown Item")
                test_action = f"[ACTION: TAKE_ITEM: {item_name}]"
            else:
                return jsonify({"text": "[DEBUG] Error: Player inventory is empty or unknown. Call /context to refresh.", "actions": []}), 200
        elif cmd == "drop":
            test_action = f"[ACTION: DROP_ITEM: {args}]"
        elif cmd == "spawn":
            test_action = f"[ACTION: SPAWN_ITEM: {args}]"
        elif cmd == "relations":
            rparts = args.rsplit(' ', 1)
            if len(rparts) == 2:
                test_action = f"[ACTION: FACTION_RELATIONS: {rparts[0].strip()}: {rparts[1].strip()}]"
        elif cmd == "task":
            test_action = f"[TASK: {args.upper()}]"

        if test_action:
            logging.info(f"TEST COMMAND: {cmd} -> {test_action}")
            return jsonify({
                "text": f"[DEBUG] Executing test command: {test_action}",
                "actions": [test_action]
            }), 200

    event = data.get('event')

    # Ignore internal events that aren't chat prompts
    if event == "selection_clear":
        return jsonify({"status": "ignored"}), 200

    # Prevent unprompted generation if no message is provided (unless it's an ambient event)
    if not player_message and event != "ambient_flavor":
        direct_chat_lease.release()
        return jsonify({"text": "...", "actions": []}), 200

    # Handle Ambient Flavor (NPC to NPC chat)
    is_ambient = event == "ambient_flavor"
    if is_ambient:
        player_message = "[AMBIENT CONVERSATION TRIGGERED]"
    else:
        direct_chat_lease.begin()

    context = data.get('context', '')
    primary_ref = name_to_id.get(primary_npc, primary_npc)
    if primary_npc and not is_ambient:
        resolved_name, resolved_context, resolved_id, resolved_ref = resolve_primary_target(
            raw_npc,
            context=context,
            nearby_data=nearby,
            mode=mode,
        )
        if resolved_name:
            primary_npc = resolved_name
        if resolved_context is not None:
            context = resolved_context
        primary_id = resolved_id or extract_id_from_context(context)
        primary_ref = resolved_ref or name_to_id.get(primary_npc, primary_npc)
    else:
        primary_id = extract_id_from_context(context)

    if primary_npc:
        name_to_id[primary_npc] = primary_ref or primary_npc

    if not is_ambient and primary_npc:
        mark_recent_direct_chat(primary_npc, context=context, explicit_id=primary_id)

    # 3.1 Register Primary NPC with LIVE_CONTEXTS (critical for batch generation)
    primary_ctx_dict = {}  # captured here, used later for transient-upgrade queue item
    if primary_npc and context:
        try:
            ctx_dict = json.loads(context) if isinstance(context, str) else context
            if ctx_dict:
                runtime_hint = str(ctx_dict.get("runtime_id") or ctx_dict.get("id") or "").strip() or None
                if primary_id and _is_strong_uid(primary_id) and "persistent_id" not in ctx_dict:
                    ctx_dict["persistent_id"] = primary_id
                elif primary_id and not runtime_hint:
                    ctx_dict["id"] = primary_id
                store_live_context(ctx_dict, name=primary_npc, explicit_id=(runtime_hint or primary_id))
                primary_ctx_dict = dict(ctx_dict)  # shallow copy after enrichment
        except Exception as e:
            logging.error(f"Error registering primary context: {e}")

    # radii
    whisper_radius, talk_radius, yell_radius = get_config_radii()

    npcs_in_radius = []
    # USE THE ROOT NEARBY LIST FOR ACCURATE PROXIMITY DETECTION
    nearby_data = data.get('nearby', [])
    primary_summary = _context_identity_summary(context, fallback_name=primary_npc) if primary_npc else {}
    primary_markers = set(
        filter(
            None,
            [
                primary_summary.get("runtime_id"),
                primary_summary.get("storage_id"),
                primary_summary.get("key"),
            ],
        )
    )
    if not primary_markers and primary_npc:
        primary_markers = {primary_npc}
    for n in nearby_data:
        n_ctx = _parse_context_dict(n, fallback_name=n.get("name", ""))
        name = _clean_npc_name(n_ctx.get("name") or n.get("name"))
        if not name or name == player_name:
            continue

        n_markers = set(
            filter(
                None,
                [
                    str(n_ctx.get("id") or n.get("id") or "").strip(),
                    _preferred_storage_id(
                        name,
                        n_ctx.get("faction") or n_ctx.get("Faction") or n_ctx.get("origin_faction") or n_ctx.get("OriginFaction"),
                        n_ctx.get("storage_id"),
                        n.get("storage_id"),
                    ),
                ],
            )
        )
        if not n_markers:
            n_markers = {name}
        if primary_markers.intersection(n_markers):
            continue

        try:
            dist = float(n_ctx.get("dist", n.get("dist", 999.0)) or 999.0)
        except Exception:
            dist = 999.0
        # Check if they are in radius based on communication mode
        if mode == "whisper":
            # Whisper is one-on-one, no one eavesdrops in this mode now
            continue
        elif mode == "talk":
            if dist <= talk_radius:
                npcs_in_radius.append(name)
        elif mode == "yell":
            if dist <= yell_radius:
                npcs_in_radius.append(name)

    # 4. History Update (Overhearing)

    def get_local_context_and_id(target_name):
        # Clean target_name for comparison
        clean_target = _clean_npc_name(target_name)
        target_id = target_name.split('|', 1)[1].strip() if '|' in target_name else None

        if clean_target == primary_npc and (not target_id or str(target_id) == str(primary_id)):
            return context, primary_id

        # Check current request's nearby data first (highest accuracy)
        nearby_data = data.get('nearby', [])
        for n in nearby_data:
            n_ctx = _parse_context_dict(n, fallback_name=n.get("name", ""))
            n_name = _clean_npc_name(n_ctx.get("name", n.get("name", "")))
            clean_n = n_name
            n_runtime = n_ctx.get("runtime_id") or n_ctx.get("id")
            n_sid = n_ctx.get("persistent_id") or n_ctx.get("storage_id") or n_runtime
            if target_id and str(n_runtime or n_sid) == str(target_id):
                return json.dumps(n_ctx), (n_runtime or n_sid)
            if clean_n == clean_target:
                return json.dumps(n_ctx), (n_runtime or n_sid)

        _, cached_ctx = resolve_live_context(name=clean_target, explicit_id=target_id)
        if cached_ctx:
            return json.dumps(cached_ctx), (
                cached_ctx.get("runtime_id")
                or cached_ctx.get("persistent_id")
                or cached_ctx.get("storage_id")
                or cached_ctx.get("id")
            )

        return "", None

    # Determine listeners (everyone in radius)
    # Ensure listeners are clean names for logic processing
    raw_listeners = list(set([primary_npc] + npcs_in_radius))
    listeners = []
    for l in raw_listeners:
        clean_l = _clean_npc_name(l)
        if clean_l not in listeners:
            listeners.append(clean_l)

    # 5. Determine who the LLM actually responds as
    if mode == 'yell':
        # Cap at 6 responders (1 primary + 5 others) to keep prompt under ~4000 tokens.
        # More than 6 voices adds marginal immersion but doubles generation time.
        others = [n for n in listeners if n != primary_npc]
        npcs = [primary_npc] + others[:5]
    else:
        npcs = [primary_npc]

    if not primary_id:
        _, _lc = resolve_live_context(name=primary_npc, explicit_id=primary_id)
        _lc = _lc or {}
        if _lc:
            primary_id = _lc.get("runtime_id") or _lc.get("storage_id") or _lc.get("id")

    # BATCH GENERATION: Pre-emptively generate profiles for anyone (participants or overhearers) missing one
    missing_for_batch = []
    checked_ids = set()
    for name in listeners:
        cid = primary_id if name == primary_npc else None
        npc_ctx, local_cid = get_local_context_and_id(name)
        sid = cid if cid else local_cid
        ctx_dict = _parse_context_dict(npc_ctx)
        _, live_ctx = resolve_live_context(name=name, context=ctx_dict, explicit_id=sid)
        live_ctx = live_ctx or {}

        # Collision-safe storage ID: name+faction so two same-named NPCs don't share a file
        storage_id = (
            ctx_dict.get("storage_id")
            or live_ctx.get("storage_id")
            or make_storage_id(name, ctx_dict.get("faction") or live_ctx.get("faction", ""))
        )

        if storage_id in checked_ids:
            continue
        checked_ids.add(storage_id)

        path = _character_path(storage_id)
        existing_profile = load_existing_profile(storage_id)
        needs_profile = (not os.path.exists(path)) or profile_needs_upgrade(existing_profile)

        if needs_profile:
            # Skip duplicates already queued elsewhere; queue helper will mark new ones.
            with PROGRESS_LOCK:
                if storage_id in PROFILES_IN_PROGRESS:
                    continue

            # Get data for batch
            if not ctx_dict:
                live = live_ctx
                ctx_dict = {
                    "name": name,
                    "race": live.get("race", "Unknown"),
                    "gender": live.get("gender", "Unknown"),
                    "faction": live.get("faction", "Unknown"),
                    "storage_id": storage_id
                }
            else:
                ctx_dict["storage_id"] = storage_id

            missing_for_batch.append(ctx_dict)

    if missing_for_batch:
        queue_batch_profile_generation(missing_for_batch)

    char_datas = {}
    threads = []

    def fetch_npc_thread(name, cid, delay):
        if delay > 0:
            time.sleep(delay)
        try:
            npc_context, local_cid = get_local_context_and_id(name)
            thread_cid = cid if cid else local_cid
            char_datas[name] = get_character_data(name, npc_context, char_id=thread_cid, skip_generate=True)
        except Exception as e:
            logging.error(f"Thread Error fetching {name}: {e}")

    delay_counter = 0
    for name in listeners:
        cid = primary_id if name == primary_npc else None
        npc_context, local_cid = get_local_context_and_id(name)
        effective_id = cid if cid else local_cid
        ctx_dict = _parse_context_dict(npc_context)
        _, live_ctx = resolve_live_context(name=name, context=ctx_dict, explicit_id=effective_id)
        live_ctx = live_ctx or {}

        # Collision-safe storage ID for delay-check
        storage_id = (
            ctx_dict.get("storage_id")
            or live_ctx.get("storage_id")
            or make_storage_id(name, ctx_dict.get("faction") or live_ctx.get("faction", ""))
        )

        path = _character_path(storage_id)
        existing_profile = load_existing_profile(storage_id)

        delay = 0
        if (not os.path.exists(path)) or profile_needs_upgrade(existing_profile):
            delay = delay_counter
            delay_counter += 1

        t = threading.Thread(target=fetch_npc_thread, args=(name, cid, delay), daemon=True)
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    # Safety Fallback
    for name in npcs:
        if name not in char_datas or not char_datas[name]:
            logging.error(f"Failed to retrieve data for {name}, using fallback.")
            char_datas[name] = {
                "Name": name, "ID": name,
                "Race": "Unknown", "Faction": "Unknown", "OriginFaction": "Unknown",
                "Gender": "Unknown", "Job": "None",
                "Personality": "A generic NPC.", "Backstory": "Unknown",
                "SpeechQuirks": "None.", "Relation": 0,
                "ConversationHistory": [],
                "_transient": True,
            }

    # TALK mode now allows fall-through to prompt only the primary NPC
    # while others overheard via history updates above.

    logging.info(f"Prompting LLM for {mode} communication with {primary_npc} (Total participants: {len(npcs)})...")
    # Context building similar to Fallout 2 mod...
    primary_data = char_datas[primary_npc]

    # Simple history append for now — keep as list so the overflow guard can trim it
    history_lines = list(primary_data["ConversationHistory"][-100:])
    history_str = "\n".join(history_lines)

    npc_profiles = ""
    for name in npcs:
        d = char_datas[name]
        if name != primary_npc:
            # Compact profile for secondary NPCs in all modes — saves ~80 tokens vs full format
            # Includes full personality + backstory opening sentence to preserve LLM accuracy
            faction = d.get('Faction', 'Unknown')
            race = d.get('Race', 'Unknown')
            job = d.get('Job', 'traveler')
            personality = d.get('Personality', 'A wanderer in the wasteland.')
            backstory = d.get('Backstory', '')
            backstory_note = (backstory.split('.')[0] + '.') if backstory else ''
            npc_profiles += f"\nCHARACTER: {name} ({race}, {faction}, {job}): {personality} {backstory_note}\n"
            continue

        # Full profile for the primary respondent (or any NPC in non-yell modes)
        npc_profiles += f"\nCHARACTER: {name}\n"
        npc_profiles += f"RACE: {d.get('Race')}\n"
        # Only pay for faction description once when origin and current match
        origin = d.get('OriginFaction', 'Unknown')
        current = d.get('Faction', 'Unknown')
        if origin == current or origin in ('Unknown', None):
            npc_profiles += f"FACTION: {get_faction_info(current)}\n"
        else:
            npc_profiles += f"ORIGIN FACTION: {get_faction_info(origin)}\n"
            npc_profiles += f"CURRENT FACTION: {get_faction_info(current)}\n"
        npc_profiles += f"JOB: {d.get('Job', 'None')}\n"
        npc_profiles += f"PERSONALITY: {d.get('Personality')}\n"
        npc_profiles += f"BACKSTORY: {d.get('Backstory')}\n"
        npc_profiles += f"PERSONAL RELATION TO PLAYER: {d.get('Relation', 0)} (Scale: -100 to 100)\n"
        _traits = d.get('Traits') or {}
        if _traits:
            _trait_parts = get_trait_parts(_traits)
            if _trait_parts:
                npc_profiles += f"TRAITS: {' | '.join(_trait_parts)}\n"

        # Add live context (stats, health, etc.)
        _, live_ctx = resolve_live_context(name=name, context=d, explicit_id=d.get("ID"))
        live_context = build_detailed_context_string(name, char_data=d, live_ctx=live_ctx)
        if live_context:
            npc_profiles += f"{live_context}\n"

    primary_race = primary_data.get('Race', 'Unknown')
    is_animal = any(kw.lower() in primary_race.lower() for kw in ANIMAL_RACES)
    is_machine = any(kw.lower() in primary_race.lower() for kw in MACHINE_RACES)

    if is_machine:
        dynamic_system_prompt = f"CRITICAL: {primary_npc} is a MECHANICAL UNIT ({primary_race}). It is a robot or automated machine — it cannot speak human language, make animal sounds, or express emotion. It outputs only brief mechanical status signals."
        final_instruction = f"Respond as {primary_npc} (the machine). Output a single terse mechanical status emission (e.g. [SCANNING], [TARGET LOST], [UNIT NOMINAL], [WARNING: INTRUDER], [LOW POWER]). No words, no personality, no gestures. Keep it under 5 words."
    elif is_animal:
        dynamic_system_prompt = f"CRITICAL: {primary_npc} is an ANIMAL ({primary_race}). Animals in Kenshi CANNOT speak human languages. They do not use words, symbols, or telegram-style speech. They ONLY react with brief physical actions, sounds, or gestures described within asterisks."
        final_instruction = f"Respond as {primary_npc} (the animal). Provide a single, BRIEF action description or sound in asterisks (e.g. *Growls*, *Tilts head*, *Nuzzles hand*). DO NOT USE WORDS OR SPEECH. Keep it under 6 words."
    else:
        dynamic_system_prompt = build_system_prompt(player_name, primary_data)

        if mode == 'yell':
            volume_status = "The player is addressing everyone nearby at a clear, projected volume."
            yell_instruction = f"\nCRITICAL: {volume_status} This can be heard by everyone nearby ({', '.join(npcs)}). This is a public address or talking to a crowd; it is NOT yelling or shouting aggressively. DO NOT tell the player to quiet down or react with annoyance to the volume. You SHOULD respond as multiple characters from the list to create a realistic crowd reaction. Every speaker MUST be on a new line started with 'Name: ' (e.g., 'Beep: Hey!').\nACTION TAGS IN CROWD MODE: If a character decides to take an action (attack, flee, join, etc.), place the [ACTION: TAG] at the END of THAT CHARACTER'S OWN LINE, not at the end of the whole response. Example: 'Hobbs: I'm with you! [ACTION: JOIN_PARTY]'\nCRITICAL JOIN RULE: If any character says they will follow, join, come along, or is 'in' (e.g. 'Count me in', 'I'll come', 'Lead the way', 'I'm with you'), that character's line MUST end with [ACTION: JOIN_PARTY]. Saying it in words WITHOUT the tag has NO game effect."
            dynamic_system_prompt += yell_instruction
        elif mode == 'whisper':
            volume_status = "The player is WHISPERING to you privately. This is a quiet, intimate, or secretive moment."
            whisper_instruction = f"\nCRITICAL: {volume_status} ONLY {primary_npc} should respond. Keep the tone hushed and private."
            dynamic_system_prompt += whisper_instruction
        else:
            volume_status = "The player is speaking at a normal, conversational volume."

            # Transition reinforcement: inform LLM they stopped the public address
            if "[ACTION: ADDRESSES GROUP]" in history_str:
                volume_status += " They have STOPPED addressing the group and are now speaking at a calm, normal volume."

            talk_instruction = f"\nINFO: {volume_status} Respond naturally. This is a standard, polite conversation. You are calm and composed. DO NOT tell the player to quiet down, do NOT react with annoyance to their volume, and do NOT mention noise or shouting unless they are actually being aggressive."

            # Relation Judgment (Direct talk only)
            if not is_ambient:
                talk_instruction += "\nJUDGMENT: At the end of your response, you MUST judge the player's tone and the quality of this interaction on a scale of -5 (extremely aggressive/hostile/insulting) to 5 (extremely friendly/helpful/respectful). 0 is neutral. Format this judgment as a tag like [JUDGMENT: n] at the very end."

            dynamic_system_prompt += talk_instruction

        # If the player is talking to multiple people (Yell or Group Talk), adjust the instructions
        if len(npcs) > 1 and mode == 'yell':
            group_instruction = f"\nCONTEXT: You are facilitating a group conversation. YOU SHOULD RESPOND AS SEVERAL DIFFERENT CHARACTERS to create a lively atmosphere. Each speaker MUST use the format: 'Name: Dialogue'."
            dynamic_system_prompt += group_instruction

        final_instruction = f"Respond as {primary_npc} to the player's last message."
        if mode != 'yell':
            final_instruction = f"Respond ONLY as {primary_npc}. Do not speak as anyone else. Keep the response to 1-2 short sentences in a single paragraph."
        else:
            final_instruction = f"Respond as several characters from this list: ({', '.join(npcs)}) to the player's group address. Ensure at least 2-3 unique characters speak on separate lines if they are nearby."

    # Limit response length to discourage rambling
    final_instruction += " Keep it immersive, short, and grounded in the world of Kenshi. Response should be 1-3 sentences maximum."

    template = load_prompt_component("prompt_chat_template.txt", """[SYSTEM CORE]
{system_prompt}

[CURRENT CHARACTER: {primary_npc}]
{npc_profiles}

[CONVERSATION HISTORY]
{history_str}

[FINAL INSTRUCTION]
{final_instruction}
You MUST write your final response exclusively in {language_str}.
""")

    settings = load_settings()
    user_lang = settings.get("language", "English")

    events_str = build_events_block()
    cdir = get_campaign_dir()
    chronicle_str = build_chronicle_block(primary_data, cdir)
    rich_prompt = template.format(
        system_prompt=dynamic_system_prompt,
        primary_npc=primary_npc,
        npc_profiles=npc_profiles,
        chronicle_str=chronicle_str,
        events_str=events_str,
        player_status_str=format_player_status(PLAYER_CONTEXT),
        player_inventory_str=format_player_inventory(PLAYER_CONTEXT),
        history_str=history_str,
        final_instruction=final_instruction,
        language_str=user_lang
    )

    # --- Pre-flight context guard ---
    # LM Studio context: 16384 tokens. 15000 cap leaves headroom for output + buffer.
    # Kenshi prompts run ~3.5 chars/token (structured text, brackets, short words).
    # Use chars * 2 // 7 (≈ ÷ 3.5) to estimate tokens conservatively.
    _CONTEXT_LIMIT = 11000
    _MAX_DIAL_TOKENS = 150   # max output tokens for one NPC line
    _USER_MSG_BUFFER = 250    # tokens for the player message + timestamp
    _PROMPT_BUDGET = _CONTEXT_LIMIT - _MAX_DIAL_TOKENS - _USER_MSG_BUFFER  # 14600

    def _est_tokens(text):
        return len(text) * 2 // 7  # ≈ chars ÷ 3.5

    while _est_tokens(rich_prompt) > _PROMPT_BUDGET and history_lines:
        history_lines.pop(0)  # Drop oldest history line
        history_str = "\n".join(history_lines)
        rich_prompt = template.format(
            system_prompt=dynamic_system_prompt,
            primary_npc=primary_npc,
            npc_profiles=npc_profiles,
            chronicle_str=chronicle_str,
            events_str=events_str,
            player_status_str=format_player_status(PLAYER_CONTEXT),
            player_inventory_str=format_player_inventory(PLAYER_CONTEXT),
            history_str=history_str,
            final_instruction=final_instruction,
            language_str=user_lang
        )

    est_tokens = _est_tokens(rich_prompt)
    logging.info(f"PROMPT: {primary_npc} | ~{est_tokens} tokens | {len(history_lines)} history lines")
    if est_tokens > _PROMPT_BUDGET:
        logging.warning(f"PROMPT: Budget exceeded even with empty history (~{est_tokens} tokens). "
                        f"NPC profile too large for {_CONTEXT_LIMIT}-token context budget.")
        DEBUG_LOG = os.path.join(KENSHI_SERVER_DIR, "logs", "llm_debug.log")
        try:
            with open(DEBUG_LOG, "a", encoding="utf-8") as f:
                f.write(f"\n{'=' * 50}\n")
                f.write(f"TIMESTAMP: {time.ctime()}\n")
                f.write(f"REQUEST FOR: {primary_npc} [GUARD FIRED - PROMPT TOO LARGE]\n")
                f.write(f"EST. TOKENS: ~{est_tokens} | BUDGET: {_PROMPT_BUDGET}\n")
                f.write(f"{'=' * 50}\n")
        except:
            pass
        return jsonify({"text": "...", "actions": []}), 200

    # Tag the player message with mode for history clarity
    mode_action = ""
    if mode == 'whisper':
        mode_action = f" [ACTION: WHISPERS TO {primary_npc}]"
    elif mode == 'yell':
        mode_action = " [ACTION: ADDRESSES GROUP]"
    else:
        # If they were addressing the group before, explicitly state they are talking normally now
        if "[ACTION: ADDRESSES GROUP]" in history_str:
            mode_action = " [ACTION: TALKS NORMALLY]"
    time_prefix = get_current_time_prefix()
    full_player_entry = f"{time_prefix}{player_name}{mode_action}: {player_message}"

    messages = [
        {"role": "system", "content": rich_prompt},
        {"role": "user", "content": full_player_entry}
    ]

    # Debug Logging: Log the full request
    DEBUG_LOG = os.path.join(KENSHI_SERVER_DIR, "logs", "llm_debug.log")
    try:
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n{'=' * 50}\n")
            f.write(f"TIMESTAMP: {time.ctime()}\n")
            f.write(f"REQUEST FOR: {primary_npc} (Mode: {mode})\n")
            f.write(f"EST. TOKENS: ~{_est_tokens(rich_prompt)}\n")
            f.write(f"PROMPT:\n{rich_prompt}\n")
            f.write(f"USER MESSAGE: {player_message}\n")
            f.write(f"{'-' * 30}\n")
    except:
        pass

    logging.info(f"Calling main chat LLM...")
    content = call_llm(messages, max_tokens=_MAX_DIAL_TOKENS)

    # Debug Logging: Log the response
    if content:
        try:
            with open(DEBUG_LOG, "a", encoding="utf-8") as f:
                f.write(f"RAW LLM RESPONSE:\n{content}\n")
                f.write(f"{'=' * 50}\n")
        except:
            pass
    else:
        logging.error("LLM returned None for chat response.")
        try:
            with open(DEBUG_LOG, "a", encoding="utf-8") as f:
                f.write(f"LLM RESPONSE FAILED (None)\n")
                f.write(f"{'=' * 50}\n")
        except:
            pass

    if content:
        # 0a. Normalize "Name: Speaker\nDialogue" → "Speaker: Dialogue" for yell mode.
        # Some models emit a header line instead of the inline "Speaker: text" format.
        if mode == 'yell':
            normalized_lines = []
            pending_name = None
            for raw_line in content.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                if line.lower().startswith("name:"):
                    remainder = line[5:].strip()
                    if not remainder:
                        pending_name = None
                        continue
                    if ":" in remainder:
                        normalized_lines.append(remainder)
                        pending_name = None
                    else:
                        pending_name = remainder
                    continue
                if pending_name:
                    normalized_lines.append(f"{pending_name}: {line}")
                    pending_name = None
                else:
                    normalized_lines.append(line)
            content = "\n".join(normalized_lines)

        # 0. Per-speaker action parsing (for YELL/Group mode)
        # We must do this BEFORE global cleaning removes the tags.
        per_speaker_actions = []
        speaker_judgments = {}  # speaker -> val
        if mode == 'yell':
            raw_lines = content.split('\n')
            for rline in raw_lines:
                rline = rline.strip()
                if not rline:
                    continue
                if rline.lower().startswith("name:"):
                    rline = rline[5:].strip()
                    if not rline:
                        continue
                # Look for "Name: ... [TAG]"
                match = re.match(r'^([^:]+):\s*(.*)$', rline)
                if match:
                    speaker = match.group(1).strip()
                    payload = match.group(2).strip()
                    # Extract ALL tags from this specific sub-line
                    speaker_tags = re.findall(r'\[\s*[^\]]+\s*\]', payload)
                    _has_join = any("JOIN_PARTY" in t.upper() for t in speaker_tags)
                    for stag in speaker_tags:
                        # Re-attribute: "Name: [TAG]"
                        per_speaker_actions.append(f"{speaker}: {stag}")
                        logging.info(f"YELL ATTRIBUTION: {speaker} took action {stag}")

                        # Extract judgment if present
                        if "JUDGMENT" in stag.upper():
                            j_match = re.search(r'-?\d+', stag)
                            if j_match:
                                try:
                                    val = int(j_match.group(0))
                                    speaker_judgments[speaker] = max(-5, min(5, val))
                                except:
                                    pass

                    # Yell recruitment safeguard: inject JOIN_PARTY if speaker agreed without tag
                    if not _has_join:
                        _yell_affirm = [
                            "count me in", "i'm with you", "i'm in", "lead the way",
                            "right behind you", "i'll follow", "i'll come", "let's go",
                            "stand with you", "i'll join", "by your side"
                        ]
                        _yell_refusals = [
                            r"\bno\b", r"\bnope\b", r"\bwon't\b", r"\bcan't\b",
                            r"\brefuse\b", r"\bnever\b", r"\bdecline\b"
                        ]
                        _pm_lower_y = player_message.lower()
                        _pay_lower = payload.lower()
                        _is_recruit_y = any(k in _pm_lower_y for k in ["join", "recruit", "follow me", "come with", "squad", "crew"])
                        _affirmed_y = any(p in _pay_lower for p in _yell_affirm)
                        _refused_y = any(re.search(p, _pay_lower) for p in _yell_refusals)
                        if _is_recruit_y and _affirmed_y and not _refused_y:
                            per_speaker_actions.append(f"{speaker}: [ACTION: JOIN_PARTY]")
                            logging.info(f"RECRUIT: Injected JOIN_PARTY for yell speaker {speaker} — prose agreement detected")

        # Use a very generous regex to find anything that looks like a tag
        all_bracketed = re.findall(r'\[\s*[^\]]+\s*\]', content)

        actions = []
        global_judgment = 0

        # Mapping of common sloppy keywords to formal C++ tags
        formal_map = {
            "GIVE_CATS": "GIVE_CATS", "TAKE_CATS": "TAKE_CATS",
            "GIVE_ITEM": "GIVE_ITEM", "TAKE_ITEM": "TAKE_ITEM",
            "DROP_ITEM": "DROP_ITEM", "SPAWN_ITEM": "SPAWN_ITEM",
            "JOIN_PARTY": "JOIN_PARTY", "LEAVE": "LEAVE",
            "IDLE": "IDLE", "PATROL_TOWN": "PATROL_TOWN",
            "RELEASE_PLAYER": "RELEASE_PLAYER", "FREE_PLAYER": "FREE_PLAYER",
            "NOTIFY": "NOTIFY", "FACTION_RELATIONS": "FACTION_RELATIONS",
            "ATTACK_TOWN": "ATTACK_TOWN", "TRAVEL_TO_TARGET_TOWN": "TRAVEL_TO_TARGET_TOWN",
            "RAID_TOWN": "RAID_TOWN", "ATTACK": "ATTACK",
            "RELEASE_PRISONER": "RELEASE_PRISONER",
            "BREAKOUT_PRISONER": "BREAKOUT_PRISONER", "BREAKOUT_PLAYER": "BREAKOUT_PLAYER",
            "JOB_MEDIC": "JOB_MEDIC", "JOB_REPAIR_ROBOT": "JOB_REPAIR_ROBOT",
            "FIND_AND_RESCUE": "FIND_AND_RESCUE", "JUDGMENT": "JUDGMENT"
        }

        for raw in all_bracketed:
            inner = raw.strip("[] \t")
            # 1. Strip any recursive-like "ACTION:" or "TASK:" prefixes first
            # We use a loop to handle weird double-prefixes like "ACTION: ACTION: TAKE_CATS"
            clean = inner
            while True:
                prev = clean
                clean = re.sub(r'^(ACTION|TASK|TAG):\s*', '', clean, flags=re.IGNORECASE).strip()
                if clean == prev:
                    break

            # 2. Extract Keyword and Args
            if ":" in clean:
                parts = clean.split(":", 1)
                kw = parts[0].strip().upper()
                args = parts[1].strip()

                # Recursive keyword fix: Handle [ACTION: TAKE_CATS: TAKE_CATS: TAKE_CATS: 40]
                while args.upper().startswith(kw):
                    args = re.sub(rf'^{re.escape(kw)}\s*:?\s*', '', args, flags=re.IGNORECASE).strip()
            else:
                kw = clean.upper()
                args = ""

            # 3. Handle Judgment (Extract value for server logic only — never forward to DLL)
            if kw == "JUDGMENT" or "JUDGMENT" in kw:
                j_val = args or re.search(r'-?\d+', kw)
                if j_val:
                    try:
                        j_str = j_val.group(0) if isinstance(j_val, re.Match) else str(j_val)
                        global_judgment = max(-5, min(5, int(j_str)))
                        logging.info(f"RELATION: Interaction judged as {global_judgment}")
                    except:
                        pass
                continue  # JUDGMENT is server-side only; sending it to the DLL breaks bubble display

            # 4. Handle Actions/Tasks
            # Fuzzy match the keyword against our known list
            matched_ka = None
            for formal in formal_map:
                if formal == kw or (formal in kw and len(kw) < len(formal) + 3):
                    matched_ka = formal_map[formal]
                    break

            if matched_ka:
                # Strip quantity suffixes from GIVE_ITEM/TAKE_ITEM args (e.g. "Skeleton Leg x4" -> "Skeleton Leg")
                if matched_ka in ("GIVE_ITEM", "TAKE_ITEM", "DROP_ITEM"):
                    args = re.sub(r'\s*[x×]\s*\d+\s*$', '', args, flags=re.IGNORECASE).strip()

                # Normalize item names to canonical Kenshi template IDs
                if matched_ka in ("GIVE_ITEM", "TAKE_ITEM", "DROP_ITEM"):
                    args = normalize_trade_item_name(args)
                elif matched_ka == "SPAWN_ITEM" and args:
                    # SPAWN_ITEM format: "Template:Count | Name | Description" — normalize template only
                    if "|" in args:
                        _si_template, _si_rest = args.split("|", 1)
                        args = normalize_trade_item_name(_si_template.strip()) + " | " + _si_rest.lstrip()
                    else:
                        args = normalize_trade_item_name(args)

                # Rebuild the tag exactly as C++ expects it, avoiding double prefixes
                if matched_ka in ["WANDERER", "CHASE", "IDLE", "MELEE_ATTACK"]:
                    final_tag = f"[TASK: {matched_ka}{f': {args}' if args else ''}]"
                else:
                    # Special case: LEAVE needs the origin faction for squad dismissal
                    if matched_ka == "LEAVE" and not args:
                        origin_faction = primary_data.get("Faction", "Unknown")
                        final_tag = f"[ACTION: LEAVE: {origin_faction}]" if origin_faction != "Unknown" else "[ACTION: LEAVE]"
                    else:
                        final_tag = f"[ACTION: {matched_ka}{f': {args}' if args else ''}]"

                # Check for redundant task assigned in consecutive turns
                if "TASK:" in final_tag:
                    last_hist = primary_data["ConversationHistory"][-1] if primary_data["ConversationHistory"] else ""
                    if final_tag in last_hist:
                        continue

                # GIVE_ITEM inventory check: if item not in NPC's live inventory, fall back to SPAWN_ITEM.
                # For shopkeepers, always use SPAWN_ITEM — ACT_GIVE_ITEM searches the NPC's personal
                # inventory by substring match; shop items live in a separate container object and are
                # never found that way, so GIVE_ITEM silently fails for traders.
                if matched_ka == "GIVE_ITEM" and args:
                    _, _resolved_live_ctx = resolve_live_context(name=primary_npc, context=primary_data, explicit_id=primary_data.get("ID"))
                    _live_ctx_gi = _resolved_live_ctx or {}
                    _is_shopkeeper = _live_ctx_gi.get("is_trader", False) or _live_ctx_gi.get("in_shop", False)
                    if _is_shopkeeper:
                        final_tag = f"[ACTION: SPAWN_ITEM: {args} | {args} | A trade item.]"
                        logging.info(f"TRADE: Shopkeeper '{primary_npc}' — switched GIVE_ITEM to SPAWN_ITEM for reliable delivery")
                    else:
                        _live_inv = _live_ctx_gi.get("inventory", [])
                        _held_names = [i.get("name", "").lower() for i in _live_inv if not i.get("equipped")]
                        _item_lower = args.lower()
                        _in_inventory = any(_item_lower in n or n in _item_lower for n in _held_names)
                        if not _in_inventory:
                            final_tag = f"[ACTION: SPAWN_ITEM: {args} | {args} | A trade item.]"
                            logging.info(f"TRADE: '{args}' not in {primary_npc}'s inventory — auto-switched GIVE_ITEM to SPAWN_ITEM")

                actions.append(final_tag)

        # 5. Apply judgment to NPC's personal relation score and faction relations
        if not is_ambient:
            # Aggregate all participants who judged
            judges = speaker_judgments if speaker_judgments else {primary_npc: global_judgment}

            for judge_name, j_val in judges.items():
                if j_val == 0:
                    continue

                # Get data for this speaker (must have been loaded in char_datas)
                j_data = char_datas.get(judge_name)
                if not j_data:
                    # If it's a yell participant we didn't fully load, skip
                    continue

                current_rel = j_data.get("Relation", 0)
                try:
                    current_rel = int(current_rel)
                except:
                    current_rel = 0

                new_rel = max(-100, min(100, current_rel + j_val))
                if new_rel != current_rel:
                    j_data["Relation"] = new_rel
                    logging.info(f"RELATION: {judge_name} personal relation updated {current_rel} -> {new_rel} (judgment={j_val})")

                # Faction relation impact (Only for significant judgments)
                f_delta = 0
                if j_val >= 5:
                    f_delta = 2
                elif j_val >= 4:
                    f_delta = 1
                elif j_val <= -5:
                    f_delta = -2
                elif j_val <= -4:
                    f_delta = -1

                if f_delta != 0:
                    npc_f = j_data.get("Faction", "None")
                    if npc_f and npc_f not in ["None", "Nameless", "No Faction"]:
                        f_tag = f"[ACTION: FACTION_RELATIONS: {npc_f}: {f_delta}]"
                        actions.append(f_tag)
                        logging.info(f"RELATION: Scheduled faction relation change via {judge_name} for {npc_f}: {f_delta}")

        # 5b. Recruitment intent safeguard (direct talk only)
        # Detect when: player asked NPC to join + NPC agreed in prose + tag was omitted by model
        _join_tag = "[ACTION: JOIN_PARTY]"
        if _join_tag not in " ".join(actions) and mode != 'yell':
            _recruit_asks = [
                "join", "recruit", "come with me", "travel with me", "follow me",
                "part of my squad", "part of my group", "my crew", "my team"
            ]
            _affirm_phrases = [
                "stand with you", "i'll follow", "follow you", "count me in",
                "lead the way", "right behind you", "i'm in", "i'm with you",
                "i'll come", "by your side", "i'll join", "signed on",
                "let's go", "i'll stand"
            ]
            _refusal_patterns = [
                r"\bno\b", r"\bnope\b", r"\bwon't\b", r"\bcan't\b", r"\bcannot\b",
                r"\brefuse\b", r"\bnever\b", r"\bnot going\b", r"\bstay here\b",
                r"\bdecline\b", r"\bnot interested\b"
            ]
            _pm_lower = player_message.lower()
            _ct_lower = content.lower()
            _is_recruit_ask = any(kw in _pm_lower for kw in _recruit_asks)
            _has_affirmation = any(p in _ct_lower for p in _affirm_phrases)
            _has_refusal = any(re.search(p, _ct_lower) for p in _refusal_patterns)
            if _is_recruit_ask and _has_affirmation and not _has_refusal:
                actions.append(_join_tag)
                logging.info(f"RECRUIT: Injected JOIN_PARTY for {primary_npc} — prose agreement detected without tag")

        # 5c. Trade payment safeguard (direct talk only)
        # Detect when: player explicitly paid/agreed + amount in message + TAKE_CATS was omitted
        if "[ACTION: TAKE_CATS" not in " ".join(actions) and mode != 'yell':
            _pay_confirms = [
                "deal", "take the cats", "here are the cats", "here's the cats",
                "here are your", "here is your", "here are my", "here is my",
                "here you go", "i'll pay", "i'll take it", "take it", "agreed",
                "take the money", "here's the money"
            ]
            _pm_lower_t = player_message.lower()
            _is_paying = any(k in _pm_lower_t for k in _pay_confirms)
            if _is_paying:
                # First try to find the amount in the player's own message
                _amt_match = re.search(r'\b(\d+)\s*cats?\b', _pm_lower_t)
                if not _amt_match:
                    # Player confirmed without stating a number (e.g. "take the cats") —
                    # fall back to the price the NPC quoted in their current response
                    _amt_match = re.search(r'\b(\d+)\s*cats?\b', content.lower())
                if _amt_match:
                    _pay_amount = int(_amt_match.group(1))
                    actions.append(f"[ACTION: TAKE_CATS:{_pay_amount}]")
                    logging.info(f"TRADE: Injected TAKE_CATS:{_pay_amount} for {primary_npc} — player confirmed payment without tag")

        # 6. Clean Dialogue Text - strip backend action tags but preserve narrative
        # brackets like [laughter] or [sighs]. Anchored to known tag prefixes so
        # hallucinated variants like [ACTION: TAKE_CATS: TAKE_CATS: 40] are still caught.
        content = re.sub(
            r'\[\s*(?:ACTION|TASK|TAG|STATUS|EFFECT|EMOTE|THOUGHT)(?:\s*:\s*[^\]]+)?\s*\]',
            '', content, flags=re.IGNORECASE
        ).strip()

        # Strip fake inventory/money bracket notations the model sometimes invents
        # e.g. "[1300 cats removed from Houston's inventory]", "[JUDGMENT: 5]" already handled above
        content = re.sub(r'\[\s*\d[\d,]*\s*cats?\s+[^\]]{0,60}\]', '', content, flags=re.IGNORECASE).strip()
        content = re.sub(r'\[\s*\d[\d,]*\s*(?:removed|added|transferred|deducted)[^\]]{0,60}\]', '', content, flags=re.IGNORECASE).strip()

        # In YELL mode, prepend per-speaker attributed actions so C++ resolves
        # each action to the correct NPC via the "NpcName: [ACTION: X]" prefix.
        if mode == 'yell' and per_speaker_actions:
            logging.info(f"YELL ACTIONS: {per_speaker_actions}")
            actions = per_speaker_actions + actions

        # Advanced Cleaning
        content = content.replace('"', '').strip()

        # Split into lines and filter out thoughts/meta-text
        lines = content.split('\n')
        filtered_lines = []
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Filter lines that leak prompt context back into the response
            if re.search(r'\[(?:Visible Gear|SHOP STOCK|Inventory Held)', line, re.IGNORECASE):
                continue

            # Re-apply tag removal to individual lines just in case
            line = re.sub(r'\[\s*[^\]]+\s*\]', '', line).strip()
            if not line:
                continue

            # If in YELL mode, look for "Name: Response" format to split bubbles
            is_group_response = (mode == 'yell')
            if is_group_response:
                if line.lower().startswith("name:"):
                    line = line[5:].strip()
                    if not line:
                        continue
                # Try to extract "Beep: Hello!" or "Hobbs: Let's go."
                match = re.match(r'^([^:]+):\s*(.*)$', line)
                if match:
                    actor_name = match.group(1).strip()
                    actor_clean = actor_name.lower()
                    actor_speech = match.group(2).strip()
                    # Only accept if actor is NOT the player (hallucination)
                    if actor_clean != player_name.lower():
                        # Use full ID if mapping exists to aid C++ resolution
                        full_actor = name_to_id.get(actor_name, actor_name)
                        filtered_lines.append(f"{full_actor}: {actor_speech}")
                        continue
                    else:
                        logging.info(f"Hallucination Filter: Discarded LLM attempt to speak as {player_name}")
                        continue

            # Skip common non-dialogue prefixes/meta-talk and hallucinated log lines
            lower_line = line.lower()
            if any(lower_line.startswith(prefix) for prefix in [
                "thought:", "thinking:", "observation:", "note:", "(thinking",
                "*", "as an ai", "i cannot", "here is", "raw llm response:",
                "timestamp:", "request for:", "prompt:", "user message:",
                "history:", "character:", "personality:", "backstory:", "current condition"
            ]):
                continue

            # Skip separator lines
            if line.startswith('=') or line.startswith('-') or len(set(line)) <= 2:
                continue

            # Remove "CHARACTER_NAME: " prefixes ONLY if NOT in multi/squad mode
            if len(npcs) <= 1:
                # Hallucination Filter: If talking to ONE person, ensure they don't speak as the player or someone else
                prefix_match = re.match(r'^([A-Za-z0-9 _\-\.]+):\s*', line)
                if prefix_match:
                    p = prefix_match.group(1).strip().lower()
                    if p == player_name.lower():
                        logging.info(f"Hallucination Filter: Discarded player entry {line}")
                        continue
                    if p != primary_npc.lower():
                        # Discard line for a different persona
                        logging.info(f"Hallucination Filter: Discarded line from {p} (expected {primary_npc})")
                        continue
                # Strip the prefix if it existed
                line = re.sub(r'^[A-Za-z0-9 _\-\.]+:\s*', '', line)
                # Discard lines that are solely an NPC name (e.g. "Benek\n" before the dialogue)
                if line.lower() in [n.lower() for n in npcs]:
                    continue

            # intra-line splitting for multi/squad talk (catch "Name1: text Name2: text")
            if len(npcs) > 1:
                # Find all "Name: Dialogue" blocks
                # We look for a name followed by a colon, then text until the next name: or string end
                # The name must avoid common dialogue words
                pattern = r'([A-Z][a-z0-9 \-\.]+):\s*([^:]+?)(?=\s+[A-Z][a-z0-9 \-\.]+:\s*|$)'
                sub_matches = re.findall(pattern, line)
                if sub_matches:
                    for actor, speech in sub_matches:
                        actor_clean = actor.strip()
                        if actor_clean.lower() != player_name.lower():
                            full_actor = name_to_id.get(actor_clean, actor_clean)
                            filtered_lines.append(f"{full_actor}: {speech.strip()}")
                    continue

            if line:
                filtered_lines.append(line)

        # Join lines - newlines represent separate bubbles in multi-NPC mode
        if filtered_lines:
            if mode != 'yell':
                # For single responder modes, merge into one bubble to prevent rapid-fire flashing
                content = " ".join(filtered_lines)
            else:
                content = "\n".join(filtered_lines)
        else:
            content = "..."

        # Final safety truncation
        _MAX_SINGLE_RESPONSE_CHARS = 500
        _MAX_YELL_RESPONSE_CHARS = 900
        _MAX_YELL_LINES = 8
        if mode == 'yell':
            if len(content) > _MAX_YELL_RESPONSE_CHARS or len(filtered_lines) > _MAX_YELL_LINES:
                kept_lines = []
                total_chars = 0
                for line in filtered_lines:
                    next_total = total_chars + (1 if kept_lines else 0) + len(line)
                    if kept_lines and (len(kept_lines) >= _MAX_YELL_LINES or next_total > _MAX_YELL_RESPONSE_CHARS):
                        break
                    if not kept_lines and len(line) > _MAX_YELL_RESPONSE_CHARS:
                        kept_lines.append(line[:_MAX_YELL_RESPONSE_CHARS - 3].rstrip() + "...")
                        break
                    kept_lines.append(line)
                    total_chars = next_total
                content = "\n".join(kept_lines) if kept_lines else "..."
        elif len(content) > _MAX_SINGLE_RESPONSE_CHARS:
            content = content[:_MAX_SINGLE_RESPONSE_CHARS - 3] + "..."

        # Log initial player prompt to global history once
        player_faction = PLAYER_CONTEXT.get("faction", "None")
        primary_faction = char_datas.get(primary_npc, {}).get("Faction", "None")
        record_event_to_history("CHAT", player_name, primary_npc, player_message, actor_faction=player_faction, target_faction=primary_faction)

        # Save history for ALL listeners (Participants + Overhearers)
        for name in listeners:
            is_overhearing = name not in npcs
            overheard_tag = "(Overheard) " if is_overhearing else ""

            if name not in char_datas:
                # Need to fetch for overhearers who weren't participants
                ctx, sid = get_local_context_and_id(name)
                char_datas[name] = get_character_data(name, ctx, char_id=sid, skip_generate=True)

            char_datas[name]["ConversationHistory"].append(f"{time_prefix}{overheard_tag}{player_name}{mode_action}: {player_message}")

            # If multiple lines/speakers, append them all to history
            if "\n" in content:
                _content_lines = [l.strip() for l in content.split('\n') if l.strip()]
                for _idx, line in enumerate(_content_lines):
                    # Ensure the line has a speaker attribution in the history
                    history_line = line
                    # Strip pipe IDs from speaker names (e.g. "Name|12345: text" → "Name: text")
                    if ':' in history_line and '|' in history_line.split(':', 1)[0]:
                        _spk, _rest = history_line.split(':', 1)
                        history_line = f"{_spk.split('|')[0].strip()}: {_rest.strip()}"
                    if ':' not in history_line:
                        # Append primary name if LLM forgot the prefix in single-responder modes
                        history_line = f"{primary_npc}: {history_line}"

                    # If this is the LAST line and there are actions, append them for history context
                    if _idx == len(_content_lines) - 1 and actions:
                        history_line += f" {' '.join(actions)}"

                    char_datas[name]["ConversationHistory"].append(f"{time_prefix}{overheard_tag}{history_line}")

                    # Log NPC speech to global history
                    if ':' in history_line:
                        h, m = history_line.split(':', 1)
                        speaker_name = h.strip()
                        speaker_faction = char_datas.get(speaker_name, {}).get("Faction", "None")
                        player_faction = PLAYER_CONTEXT.get("faction", "None")
                        record_event_to_history("CHAT", speaker_name, player_name, m.strip(), actor_faction=speaker_faction, target_faction=player_faction)
                    else:
                        primary_faction = char_datas.get(primary_npc, {}).get("Faction", "None")
                        player_faction = PLAYER_CONTEXT.get("faction", "None")
                        record_event_to_history("CHAT", primary_npc, player_name, history_line, actor_faction=primary_faction, target_faction=player_faction)
            else:
                # Fallback for single-line responses
                history_line = content
                # Strip pipe IDs from speaker names (e.g. "Name|12345: text" → "Name: text")
                if ':' in history_line and '|' in history_line.split(':', 1)[0]:
                    _spk, _rest = history_line.split(':', 1)
                    history_line = f"{_spk.split('|')[0].strip()}: {_rest.strip()}"
                if ':' not in history_line:
                    history_line = f"{primary_npc}: {history_line}"

                history_entry = f"{time_prefix}{overheard_tag}{history_line}"
                if actions:
                    history_entry += f" {' '.join(actions)}"
                char_datas[name]["ConversationHistory"].append(history_entry)

                primary_faction = char_datas.get(primary_npc, {}).get("Faction", "None")
                player_faction = PLAYER_CONTEXT.get("faction", "None")
                record_event_to_history("CHAT", primary_npc, player_name, content, actor_faction=primary_faction, target_faction=player_faction)

            # Limit history to 45 lines (matches save_character_data and get_character_data caps)
            if len(char_datas[name]["ConversationHistory"]) > 45:
                char_datas[name]["ConversationHistory"] = char_datas[name]["ConversationHistory"][-45:]

            storage_id = char_datas[name].get("ID", name)
            # Relaxed transient check: if they have history, allow save even if technically transient
            has_history = len(char_datas[name].get("ConversationHistory", [])) > 0
            if char_datas[name].get("_transient") and not has_history:
                logging.debug(f"SKIP SAVE: {name} is using a transient fallback profile with no history. Blocking disk override.")
            elif should_save_profile(name, storage_id, char_datas[name]):
                save_character_data(storage_id, char_datas[name])

        logging.info(f"AI RESPONSE: {content} | ACTIONS: {actions}")
        direct_chat_lease.release()

        # Queue primary NPC for batch upgrade if their profile is still transient.
        # Nearby NPCs are handled by the pre-chat batch loop; the primary NPC is not.
        # Placed after release() so the queue is not deferred by the direct-chat active guard.
        _primary_profile = char_datas.get(primary_npc)
        _primary_sid = _primary_profile.get("ID", primary_npc) if _primary_profile else primary_npc
        _needs_upgrade = profile_needs_upgrade(_primary_profile) if _primary_profile else False
        _diag_running = False
        if _needs_upgrade:
            with PROGRESS_LOCK:
                _diag_running = _primary_sid in PROFILES_IN_PROGRESS
        if not _primary_profile or _needs_upgrade:
            logging.info(
                f"UPGRADE_DIAG: npc={primary_npc!r} "
                f"present={bool(_primary_profile)} "
                f"transient={_primary_profile.get('_transient') if _primary_profile else 'N/A'} "
                f"needs={_needs_upgrade} "
                f"sid={_primary_sid!r} "
                + (f"in_progress={_diag_running}" if _needs_upgrade else "")
            )
        if _primary_profile and _needs_upgrade:
            _psid = _primary_sid
            _already_running = _diag_running
            if not _already_running:
                queue_batch_profile_generation([{
                    "name": primary_npc,
                    "storage_id": _psid,
                    "race": _primary_profile.get("Race") or primary_ctx_dict.get("race", "Unknown"),
                    "gender": _primary_profile.get("Sex") or primary_ctx_dict.get("gender", "Unknown"),
                    "faction": _primary_profile.get("Faction") or primary_ctx_dict.get("faction", "Unknown"),
                    "origin_faction": _primary_profile.get("OriginFaction") or primary_ctx_dict.get("origin_faction", "Unknown"),
                    "job": _primary_profile.get("Job") or primary_ctx_dict.get("job", "None"),
                    "runtime_id": primary_ctx_dict.get("runtime_id") or primary_ctx_dict.get("id"),
                    "persistent_id": primary_ctx_dict.get("persistent_id"),
                }])
                logging.info(f"UPGRADE: Queued transient primary NPC '{primary_npc}' ({_psid}) for batch profile upgrade.")

        return jsonify({"text": content, "actions": actions})
    direct_chat_lease.release()
    return jsonify({"text": "...", "actions": []})


def record_event_to_history(etype, actor, target, msg, actor_faction="None", target_faction="None"):
    """Centralized helper to record events for both the log and narrative synthesis."""
    global EVENT_HISTORY, EVENT_HISTORY_SET, GLOBAL_EVENT_COUNTER, EVENT_THROTTLE, LAST_STATE_LOG
    if not msg:
        return

    # Format: [TYPE] Actor (Faction) -> Target (Faction) @ Location: Message
    p_fact = PLAYER_CONTEXT.get('faction', 'Nameless')
    a_fact_display = actor_faction
    if actor_faction == "Nameless" or actor_faction == p_fact:
        a_fact_display = f"Player's Squad: {p_fact}"

    t_fact_display = target_faction
    if target_faction == "Nameless" or target_faction == p_fact:
        t_fact_display = f"Player's Squad: {p_fact}"

    actor_part = f"{actor} ({a_fact_display})" if a_fact_display and a_fact_display != "None" else actor
    target_part = f"{target} ({t_fact_display})" if t_fact_display and t_fact_display != "None" else target

    # Include location from player context if available
    location = ""
    if PLAYER_CONTEXT:
        env = PLAYER_CONTEXT.get("environment", {})
        town = env.get("town_name", "") if isinstance(env, dict) else ""
        if town:
            location = f" @ {town}"

    time_str = get_current_time_prefix().strip()
    prefix = f"{time_str} " if time_str else ""
    evt_str = f"{prefix}[{etype}] {actor_part} -> {target_part}{location}: {msg}"

    # --- STATE SUPPRESSION ---
    # For repetitive state hooks (knockout, recovery, etc), only log if the status actually CHANGES.
    state_key = f"{target_part}|{etype}"
    with STATE_LOCK:
        if LAST_STATE_LOG.get(state_key) == msg:
            return  # Message is identical to last recorded state, skip
        LAST_STATE_LOG[state_key] = msg
        # Cleanup if it gets massive
        if len(LAST_STATE_LOG) > 2000:
            LAST_STATE_LOG.clear()

    # --- THROTTLE CHECK ---
    # Cooldown for non-stateful rapid repeats
    throttle_key = f"{etype}|{actor_part}|{target_part}|{msg}"
    now = time.time()
    with THROTTLE_LOCK:
        last_time = EVENT_THROTTLE.get(throttle_key, 0)
        # Increased cooldown to 30s for exact same event to prevent spam
        if now - last_time < 30.0:
            return
        EVENT_THROTTLE[throttle_key] = now
        # Periodic cleanup: Instead of clearing everything, just trim if it gets too large
        if len(EVENT_THROTTLE) > 1000:
            # Simple way to trim: keep most recent half
            sorted_items = sorted(EVENT_THROTTLE.items(), key=lambda x: x[1])
            EVENT_THROTTLE = dict(sorted_items[500:])

    # Log to file (Active Campaign Log) - Always log for live debugger feed
    try:
        cdir = get_campaign_dir()
        log_dir = os.path.join(cdir, "logs")
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        with open(os.path.join(log_dir, "global_events.log"), "a", encoding="utf-8") as f:
            f.write(f"{evt_str}\n")

        # Also copy to server.log so it shows up in both tabs if relevant
        logging.info(f"EVENT: {evt_str}")
    except Exception as e:
        logging.warning(f"EVENT: Failed to write to global_events.log: {e}")

    # Simple deduplication based on exact string for memory/synthesis
    # CRITICAL: Filter out "looting" events from the narrative history to prevent spam.
    if etype == "looting":
        return

    if evt_str not in EVENT_HISTORY_SET:
        EVENT_HISTORY.append(evt_str)
        EVENT_HISTORY_SET.add(evt_str)
        GLOBAL_EVENT_COUNTER += 1
        if GLOBAL_EVENT_COUNTER % 10 == 0:
            save_campaign_history()
        if len(EVENT_HISTORY) > 500:
            del EVENT_HISTORY[:-500]
            EVENT_HISTORY_SET = set(EVENT_HISTORY)


def generate_global_narrative_thread():
    """Synthesizes the last 100 events into a global rumor for NPCs to overhear."""
    global EVENT_HISTORY
    # Lower threshold for manual trigger so small sessions can still synthesize
    min_needed = 5
    if len(EVENT_HISTORY) < min_needed:
        logging.warning(f"NARRATIVE: Not enough events to synthesize (have {len(EVENT_HISTORY)}, need {min_needed}).")
        return None

    settings = load_settings()

    # Cap at 75 events to keep synthesis prompt under ~2K tokens (was 250, caused ~10K token prompts).
    sample_size = min(len(EVENT_HISTORY), 75)
    last_chunk = EVENT_HISTORY[-sample_size:]

    # Pre-compress raw events into compact daily summaries before feeding to LLM.
    # Turns ~75 verbose lines into ~10-15 summary lines, covering more days of history
    # in the same token budget → richer, more varied rumours.
    if _HAVE_COMPRESSOR:
        assert _sge_parse != None
        assert _sge_compress != None
        assert _sge_reduce != None
        try:
            raw_text = "\n".join(last_chunk)
            events = _sge_parse(raw_text)
            compressed = _sge_reduce(_sge_compress(events))
            if compressed.strip():
                last_chunk = compressed.splitlines()
                logging.info(f"NARRATIVE: Compressed {sample_size} events → {len(last_chunk)} summary lines.")
            else:
                logging.warning("NARRATIVE: Compressor returned empty output — falling back to raw events.")
        except Exception as _ce:
            logging.error(f"NARRATIVE: Compressor failed ({_ce}) — falling back to raw events.")

    # GROUP BY LOCATION
    # Events often contain " @ TownName"
    grouped_events = {}
    for evt in last_chunk:
        location = "Unknown Region"
        if " @ " in evt:
            # Extract location between " @ " and the following ":"
            try:
                parts = evt.split(" @ ")
                if len(parts) > 1:
                    location = parts[1].split(":")[0].strip()
            except Exception as e:
                logging.warning(f"NARRATIVE: Failed to parse location from event line ({e})")

        if location not in grouped_events:
            grouped_events[location] = []
        grouped_events[location].append(evt)

    # Format grouped text
    events_text = ""
    for loc, evts in grouped_events.items():
        events_text += f"\n--- {loc.upper()} ---\n"
        events_text += "\n".join(evts) + "\n"

    logging.info(f"NARRATIVE: Grouped {len(last_chunk)} events into {len(grouped_events)} locations.")
    # logging.debug(f"NARRATIVE GROUPING:\n{events_text}")

    # Load existing rumors to prevent repeats
    past_rumors_block = ""
    world_events_path = os.path.join(get_campaign_dir(), "world_events.txt")
    if os.path.exists(world_events_path):
        try:
            with open(world_events_path, "r", encoding="utf-8") as f:
                # Find the actual [RUMOR: ...] text in the last few lines
                rumor_lines = []
                for line in f.readlines()[-20:]:  # Scan last 20 lines
                    match = re.search(r'\[RUMOR:\s*(.*?)\]', line)
                    if match:
                        rumor_lines.append(f"- {match.group(1).strip()}")

                if rumor_lines:
                    past_rumors_block = "\nPREVIOUS RUMORS (Do NOT repeat these):\n" + "\n".join(rumor_lines[-5:])
        except Exception as e:
            logging.warning(f"NARRATIVE: Failed to read past rumors from world_events.txt ({e})")

    p_fact = PLAYER_CONTEXT.get("faction", "The Nameless")

    template = load_prompt_component("prompt_world_synthesis.txt", """[KENSHI WORLD SYNERGY]
The following is a log of recent interactions in the world of Kenshi, grouped by location.
Your task is to synthesize these events into a single, high-impact 'Global Rumor'.

RECENT LOGS:
{events_text}
{past_rumors_block}

INSTRUCTIONS:
1. Treat the PLAYER and their squad ({p_fact}) as just another group of wanderers. 
2. DO NOT make the player out to be a hero or legend unless they have performed a truly massive feat (e.g. liberating a city or killing a faction leader).
3. ONLY attribute events to the player if their name or 'Player's Squad' actually appears as an actor in the logs.
4. If an actor is 'Unknown', do NOT assume it is the player. Treat it as a mysterious figure or a random incident.
5. If the player is merely starving, dying, or performing minor trades, either ignore it or mention it as a minor misfortune of another 'unlucky nomad'.
6. Focus on patterns: frequent battles, faction clashes, or specific NPC actions.
7. Write one flavorful, cynical rumor — 1 to 3 sentences. Ground it in Kenshi's brutal reality.
8. Output ONLY the rumor text itself, with no prefix tags or formatting.
9. DO NOT blow minor scuffles out of proportion; keep it grounded.
10. VARIETY: Do NOT produce a rumor that is logically identical to the PREVIOUS RUMORS listed above.
""")
    prompt = template.format(events_text=events_text, past_rumors_block=past_rumors_block, p_fact=p_fact)

    # Apply language instruction so rumors respect the UI language setting
    language = settings.get("language", "English")
    if language and language.lower() != "english":
        prompt += f"\nLANGUAGE: You MUST write the rumor ONLY in {language}. Do not use English."

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": "Synthesize the rumors of the borderlands."}
    ]

    logging.info("NARRATIVE: Calling LLM to synthesize world events...")
    rumor_text = call_llm(messages, max_tokens=150)

    if rumor_text:
        # Strip any accidental tags the LLM might still output
        rumor_text = rumor_text.strip()
        # If LLM still used the old format, extract just the inner text
        tag_match = re.search(r'\[RUMOR:\s*(.*?)\]', rumor_text, re.DOTALL)
        if tag_match:
            rumor_text = tag_match.group(1).strip()
        # Remove any leading dashes or bullets
        rumor_text = re.sub(r'^[-•*]\s*', '', rumor_text).strip()

        if len(rumor_text) > 10:
            time_prefix = get_current_time_prefix().strip()
            rumor_tagged = f"- {time_prefix} [RUMOR: {rumor_text}]"
            # Try campaign dir first
            world_events_path = os.path.join(get_campaign_dir(), "world_events.txt")
            if not os.path.exists(world_events_path):
                # Create empty if missing
                with open(world_events_path, "w", encoding="utf-8") as f:
                    f.write("# Dynamic rumors generated for this campaign\n")

            try:
                with open(world_events_path, "a", encoding="utf-8") as f:
                    f.write(f"\n{rumor_tagged}\n")
                logging.info(f"NARRATIVE: Generated and saved new global event: {rumor_tagged}")
                # Notify player of the new rumor in-game
                send_to_pipe(f"NOTIFY: [WORLD EVENT] {rumor_text}")
                return rumor_tagged
            except Exception as e:
                logging.error(f"Error saving global event rumor: {e}")
    return None


@app.route('/synthesize', methods=['POST'])
def manual_synthesize():
    """Manual trigger for global narrative synthesis."""
    # Run synchronously for the manual trigger so we can return the result
    rumor = generate_global_narrative_thread()
    if rumor:
        return jsonify({"status": "ok", "rumor": rumor})
    else:
        return jsonify({"status": "error", "message": "Failed to generate rumor or not enough events (need 5)."}), 400


@app.route('/events', methods=['GET', 'POST'])
def list_events():
    logging.info(f"ROUTE: /events [{request.method}]")

    """Return only synthesized [RUMOR:] entries from world_events.txt.
    Left list: '1. First few words...' — no # symbol (avoids MyGUI color-tag parsing).
    Right panel: full formatted card for the selected rumor.
    """
    world_events_path = os.path.join(get_campaign_dir(), "world_events.txt")
    rumors = []

    if os.path.exists(world_events_path):
        try:
            with open(world_events_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            rumor_count = 0
            for i, line in enumerate(lines):
                stripped = line.strip()
                # Find [RUMOR: ...] anywhere in the line to skip over new date tags
                match = re.search(r'\[RUMOR:\s*(.*?)\]', stripped)
                if not match:
                    continue

                rumor_count += 1
                inner = match.group(1).strip()

                # Build a safe label: "N. first 7 words..." with no special chars
                words = inner.split()
                short = " ".join(words[:7]) + ("..." if len(words) > 7 else "")
                label = f"{rumor_count}. {short}"
                rumors.append({"id": str(i + 1), "title": label[:80], "content": stripped, "inner": inner})

        except Exception as e:
            logging.error(f"Error reading world_events.txt: {e}")

    formatted = "--- DYNAMIC WORLD RUMORS ---\n" + "\n".join(r["content"] for r in rumors) if rumors else "(No rumors yet. Use 'Synthesize Rumors' to generate some.)"
    return jsonify({"status": "ok", "text": formatted, "events": rumors})


@app.route('/events/content', methods=['POST'])
def events_content():
    """Return formatted multi-line detail text for a selected world event entry.
    The right panel (SetEventsText) splits on newlines, so each line becomes a row.
    """
    data = request.json or {}
    line_id = data.get("day", "")

    # Only use campaign-specific events
    world_events_path = os.path.join(get_campaign_dir(), "world_events.txt")

    try:
        line_num = int(line_id) - 1  # id is 1-indexed line number
        with open(world_events_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if 0 <= line_num < len(lines):
            raw = lines[line_num].strip()
            match = re.search(r'\[RUMOR:\s*(.*?)\]', raw)
            if match:
                # Extract plain text from the capture group
                inner = match.group(1).strip()
                wrapped = textwrap.wrap(inner, width=76)
                card_lines = [
                    "=" * 38,
                    "  WORLD RUMOR",
                    "=" * 38,
                    "",
                ] + wrapped + [
                    "",
                    "(Synthesized from recent world events)"
                ]
                return jsonify({"status": "ok", "text": "\n".join(card_lines)})
    except Exception as e:
        logging.error(f"events/content error: {e}")
    return jsonify({"status": "error", "text": "Entry not found."}), 404


@app.route('/context', methods=['POST'])
def update_context():
    global PLAYER_CONTEXT, LAST_NPC_NAME
    data = request.json
    if not data:
        return jsonify({"status": "error"}), 400

    # Process and deduplicate world events
    # SKIP processing if the game is paused or at speed 0 to prevent loops
    is_paused = data.get("is_paused", False)
    game_speed = data.get("gamespeed", 1.0)

    if not is_paused and game_speed > 0.05:
        new_events = data.get("events", [])
        for e in new_events:
            record_event_to_history(
                e.get("type", "EVENT"),
                e.get("actor", "Unknown"),
                e.get("target", "None"),
                e.get("msg", ""),
                actor_faction=e.get("actor_faction", "None"),
                target_faction=e.get("target_faction", "None")
            )
    elif is_paused:
        # Check if we should log at least once that the world is paused?
        # No, better to keep it clean.
        pass

    if data.get("type") == "player":
        prev_paused = PLAYER_CONTEXT.get("is_paused")
        PLAYER_CONTEXT = data
        if prev_paused != data.get("is_paused"):
            logging.info(f"CONTEXT: Player pause state changed to {data.get('is_paused')} (Speed: {data.get('gamespeed')})")
    else:
        name = data.get("name")
        if name:
            store_live_context(
                data,
                name=name,
                explicit_id=(
                    data.get("runtime_id")
                    or data.get("id")
                    or data.get("persistent_id")
                    or data.get("storage_id")
                ),
            )
            # Force update LAST_STATE_LOG for immediate debugger visibility
            with STATE_LOCK:
                LAST_STATE_LOG["npc"] = _parse_context_dict(data)
    return jsonify({"status": "ok"})


@app.route('/context', methods=['GET'])
def get_context():
    """Returns the most recent player and NPC context for the debugger/UI."""
    # Try to grab the last active NPC from live contexts
    last_npc = None
    if LAST_NPC_KEY and LAST_NPC_KEY in LIVE_CONTEXTS:
        last_npc = LIVE_CONTEXTS[LAST_NPC_KEY]
    elif LIVE_CONTEXTS:
        last_npc_id = list(LIVE_CONTEXTS.keys())[-1]
        last_npc = LIVE_CONTEXTS[last_npc_id]

    # Use the global tracking for synthesis
    elapsed = SYNTHESIS_STATUS.get("elapsed", 0)
    interval = SYNTHESIS_STATUS.get("interval", 60)

    return jsonify({
        "status": "ok",
        "player": PLAYER_CONTEXT or LAST_STATE_LOG.get("player", {}),
        "npc": last_npc or LAST_STATE_LOG.get("npc", {}),
        "campaign": ACTIVE_CAMPAIGN,
        "synthesis": {
            "elapsed": elapsed,
            "interval": interval
        }
    })


@app.route('/rename', methods=['POST'])
def rename_endpoint():
    data = request.json or {}
    old_name = data.get("old_name", "")
    new_name = data.get("new_name", "")
    context = data.get("context", {})

    if not new_name or not old_name:
        return jsonify({"status": "error", "message": "Missing names"}), 400

    target_id = context.get("storage_id")
    if not target_id:
        target_id = context.get("persistent_id") or context.get("id") or old_name

    cdata, file_path = get_character_data(target_id, context, skip_generate=False)
    if cdata:
        cdata["Name"] = new_name
        dack.save(file_path, cdata)
        logging.info(f"RENAME: Updated identity for '{old_name}' -> '{new_name}' in {file_path}")
        return jsonify({"status": "ok", "new_name": new_name})

    return jsonify({"status": "error", "message": "Character data not found"}), 404


@app.route('/settings', methods=['GET', 'POST'])
def settings_endpoint():
    global CURRENT_MODEL_KEY
    if request.method == 'POST' and request.content_length:
        logging.info(f"ROUTE: /settings [{request.method}]")
    else:
        logging.debug(f"ROUTE: /settings [{request.method}]")
    load_configs()

    # ---------- READ (GET or POST with no body) ----------
    data = None
    if request.method == 'POST':
        try:
            data = request.get_json(silent=True)
        except:
            data = None

    if not data:
        # The C++ WelcomeWindow calls POST /settings with empty body to fetch config.
        # The visual_debugger calls GET /models. Both need the same response.
        settings = load_settings()
        r, t, y = get_config_radii()
        campaigns = [d for d in os.listdir(CAMPAIGNS_DIR) if os.path.isdir(os.path.join(CAMPAIGNS_DIR, d))] if os.path.exists(CAMPAIGNS_DIR) else []

        # Grouped map for dropdowns: Provider -> [Models]
        mbp = {}
        for k, v in MODELS_CONFIG.items():
            p = v.get("provider", "unknown")
            if p not in mbp:
                mbp[p] = []
            mbp[p].append(k)

        # Determine current provider
        curr_prov = MODELS_CONFIG.get(CURRENT_MODEL_KEY, {}).get("provider", "unknown")

        return jsonify({
            "status": "ok",
            "models": mbp,        # C++ dropdowns loop uses this
            "all_models": MODELS_CONFIG,  # C++ initialization lookup
            "providers": list(PROVIDERS_CONFIG.keys()),
            "current": CURRENT_MODEL_KEY,
            "current_provider": curr_prov,
            "campaigns": campaigns,
            "current_campaign": ACTIVE_CAMPAIGN,
            "enable_ambient": settings.get("enable_ambient", True),
            "enable_renamer": settings.get("enable_renamer", True),
            "enable_animal_renamer": settings.get("enable_animal_renamer", True),
            "ambient_timer": settings.get("radiant_delay", 240),
            "synthesis_timer": settings.get("synthesis_interval_minutes", 15),
            "global_events_count": settings.get("global_events_count", 7),
            "dialogue_speed": settings.get("dialogue_speed_seconds", 5),
            "bubble_life": settings.get("bubble_life", 5),
            "chat_hotkey": settings.get("chat_hotkey", "\\"),
            "radii": {
                "radiant": settings.get("radiant_range", r),
                "talk": settings.get("talk_radius", t),
                "yell": settings.get("yell_radius", y)
            },
            "language": settings.get("language", "English"),
            "supported_languages": list(LOCALIZATION_CONFIG.keys()),
            "ui_translation": LOCALIZATION_CONFIG.get(settings.get("language", "English"), {})
        })

    # ---------- WRITE (POST with JSON body) ----------
    logging.info(f"Received settings update request: {json.dumps(data)}")
    changes = {}

    new_model = data.get("current_model")
    if new_model and new_model in MODELS_CONFIG:
        CURRENT_MODEL_KEY = new_model
        changes["current_model"] = CURRENT_MODEL_KEY
        logging.info(f"Model switched to: {CURRENT_MODEL_KEY}")

    enable_ambient = data.get("enable_ambient")
    if enable_ambient is not None:
        changes["enable_ambient"] = enable_ambient
        send_to_pipe(f"SET_CONFIG: g_enableAmbient: {'1' if enable_ambient else '0'}")
        logging.info(f"Ambient enabled set to: {enable_ambient}")

    enable_renamer = data.get("enable_renamer")
    if enable_renamer is not None:
        changes["enable_renamer"] = enable_renamer
        send_to_pipe(f"SET_CONFIG: g_enableRenamer: {'1' if enable_renamer else '0'}")
        logging.info(f"Renamer enabled set to: {enable_renamer}")

    enable_animal_renamer = data.get("enable_animal_renamer")
    if enable_animal_renamer is not None:
        changes["enable_animal_renamer"] = enable_animal_renamer
        send_to_pipe(f"SET_CONFIG: g_enableAnimalRenamer: {'1' if enable_animal_renamer else '0'}")
        logging.info(f"Animal Renamer enabled set to: {enable_animal_renamer}")

    ambient_timer = data.get("ambient_timer")
    if ambient_timer is not None:
        try:
            val = int(ambient_timer)
            changes["radiant_delay"] = val
            send_to_pipe(f"SET_CONFIG: g_ambientIntervalSeconds: {val}")
            logging.info(f"Radiant delay set to: {val}")
        except (ValueError, TypeError):
            pass

    radii = data.get("radii")
    if radii:
        r = radii.get("radiant")
        t = radii.get("talk")
        y = radii.get("yell")
        if r is not None:
            send_to_pipe(f"SET_CONFIG: g_radiantRange: {r}")
        if t is not None:
            send_to_pipe(f"SET_CONFIG: g_talkRadius: {t}")
        if y is not None:
            send_to_pipe(f"SET_CONFIG: g_yellRadius: {y}")
        changes["radii"] = radii

    min_rel = data.get("min_faction_relation")
    if min_rel is not None:
        send_to_pipe(f"SET_CONFIG: g_minFactionRelation: {min_rel}")
        changes["min_faction_relation"] = min_rel

    lang = data.get("language")
    if lang is not None:
        changes["language"] = lang
        logging.info(f"Language set to: {lang}")

    max_rel = data.get("max_faction_relation")
    if max_rel is not None:
        send_to_pipe(f"SET_CONFIG: g_maxFactionRelation: {max_rel}")
        changes["max_faction_relation"] = max_rel

    ge_count = data.get("global_events_count")
    if ge_count is not None:
        try:
            val = int(ge_count)
            changes["global_events_count"] = val
            logging.info(f"Global events count set to: {val}")
        except (ValueError, TypeError):
            logging.warning(f"SETTINGS: invalid value for global_events_count: {ge_count!r}, ignoring")

    syn_timer = data.get("synthesis_timer")
    if syn_timer is not None:
        try:
            val = int(syn_timer)
            changes["synthesis_interval_minutes"] = val
            logging.info(f"Synthesis timer set to: {val} minutes")
        except (ValueError, TypeError):
            logging.warning(f"SETTINGS: invalid value for synthesis_timer: {syn_timer!r}, ignoring")

    diag_speed = data.get("dialogue_speed")
    if diag_speed is not None:
        try:
            val = int(diag_speed)
            changes["dialogue_speed_seconds"] = val
            send_to_pipe(f"SET_CONFIG: g_dialogueSpeedSeconds: {val}")
            logging.info(f"Dialogue speed set to: {val} seconds")
        except (ValueError, TypeError):
            logging.warning(f"SETTINGS: invalid value for dialogue_speed: {diag_speed!r}, ignoring")

    bubble_life = data.get("bubble_life")
    if bubble_life is not None:
        try:
            val = float(bubble_life)
            changes["bubble_life"] = val
            send_to_pipe(f"SET_CONFIG: g_speechBubbleLife: {val}")
            logging.info(f"Bubble life set to: {val} seconds")
        except (ValueError, TypeError):
            logging.warning(f"SETTINGS: invalid value for bubble_life: {bubble_life!r}, ignoring")

    chat_hotkey = data.get("chat_hotkey")
    if chat_hotkey is not None:
        changes["chat_hotkey"] = str(chat_hotkey)
        logging.info(f"Chat hotkey set to: {chat_hotkey}")

    campaign = data.get("current_campaign")
    if campaign:
        if switch_campaign(campaign):
            changes["current_campaign"] = ACTIVE_CAMPAIGN
            logging.info(f"Campaign switched to: {ACTIVE_CAMPAIGN}")

    if changes:
        save_settings(changes)
        logging.info(f"Successfully saved {len(changes)} setting changes.")
        return jsonify({"status": "ok", **changes})

    return jsonify({"status": "error", "message": "No valid settings provided"}), 400


@app.route('/campaigns/list', methods=['GET'])
def list_campaigns_route():
    logging.info("ROUTE: /campaigns/list [GET]")
    if not os.path.exists(CAMPAIGNS_DIR):
        os.makedirs(CAMPAIGNS_DIR)

    # Ensure Default exists
    d_dir = os.path.join(CAMPAIGNS_DIR, "Default")
    if not os.path.exists(d_dir):
        os.makedirs(d_dir)

    camps = [d for d in os.listdir(CAMPAIGNS_DIR) if os.path.isdir(os.path.join(CAMPAIGNS_DIR, d))]
    return jsonify({"status": "ok", "campaigns": camps, "current": ACTIVE_CAMPAIGN})


@app.route('/campaigns/create', methods=['POST'])
def create_campaign_route():
    logging.info("ROUTE: /campaigns/create [POST]")
    data = request.json
    name = data.get("name")
    if not name:
        return jsonify({"status": "error", "message": "Missing name"}), 400

    # Sanitize
    safe_name = "".join([c for c in name if c.isalnum() or c in (' ', '_', '-')]).strip()
    if not safe_name:
        return jsonify({"status": "error", "message": "Invalid name"}), 400

    cdir = os.path.join(CAMPAIGNS_DIR, safe_name)
    if os.path.exists(cdir):
        return jsonify({"status": "error", "message": "Campaign already exists"}), 400

    os.makedirs(cdir)
    ensure_campaign_seeded(cdir)

    # Automatically switch to the new campaign
    switch_campaign(safe_name)

    logging.info(f"CAMPAIGN: Created and switched to new campaign '{safe_name}'")
    return jsonify({"status": "ok", "name": safe_name, "current": ACTIVE_CAMPAIGN})


@app.route('/campaigns/switch', methods=['POST'])
def switch_campaign_route():
    logging.info("ROUTE: /campaigns/switch [POST]")
    data = request.json
    name = data.get("name")
    if not name:
        return jsonify({"status": "error", "message": "Missing name"}), 400
    if switch_campaign(name):
        return jsonify({"status": "ok", "current": ACTIVE_CAMPAIGN})
    return jsonify({"status": "error", "message": "Campaign not found"}), 404


@app.route('/campaigns/cull', methods=['POST'])
def cull_campaign_route():
    logging.info("ROUTE: /campaigns/cull [POST]")

    current_day = int(PLAYER_CONTEXT.get("day", 0))
    current_hour = int(PLAYER_CONTEXT.get("hour", 0))
    current_min = int(PLAYER_CONTEXT.get("minute", 0))

    cdir = get_campaign_dir()
    logging.info(f"CULL: Starting cull for [Day {current_day}, {current_hour:02d}:{current_min:02d}] in {cdir}")

    # 1. Cull NPC History TXTs
    hist_dir = os.path.join(cdir, "characters", "history")
    if os.path.exists(hist_dir):
        for f in os.listdir(hist_dir):
            if f.endswith(".txt"):
                fpath = os.path.join(hist_dir, f)
                try:
                    with open(fpath, "r", encoding="utf-8") as fh:
                        history = [l.strip() for l in fh.read().split('\n') if l.strip()]

                    new_history = [l for l in history if not is_future_timestamp(l, current_day, current_hour, current_min)]

                    if len(new_history) != len(history):
                        with open(fpath, "w", encoding="utf-8") as fw:
                            fw.write("\n".join(new_history))
                        logging.info(f"CULL: Culled {len(history) - len(new_history)} lines from {f}")
                except Exception as e:
                    logging.warning(f"CULL: Error processing {fpath}: {e}")

    # 2. Cull event_history.json
    ev_history_path = os.path.join(cdir, "event_history.json")
    if os.path.exists(ev_history_path):
        try:
            with open(ev_history_path, "r", encoding="utf-8") as fh:
                ev_data = json.load(fh)
            new_ev_data = [l for l in ev_data if not is_future_timestamp(l, current_day, current_hour, current_min)]
            if len(new_ev_data) != len(ev_data):
                with open(ev_history_path, "w", encoding="utf-8") as fw:
                    json.dump(new_ev_data, fw, indent=2)
                global EVENT_HISTORY, EVENT_HISTORY_SET
                EVENT_HISTORY = new_ev_data
                EVENT_HISTORY_SET = set(EVENT_HISTORY)
                logging.info(f"CULL: Culled {len(ev_data) - len(new_ev_data)} events from event_history.json")
        except Exception as e:
            logging.warning(f"CULL: Error processing event_history.json: {e}")

    # 3. Cull world_events.txt (rumors)
    world_events_path = os.path.join(cdir, "world_events.txt")
    if os.path.exists(world_events_path):
        try:
            with open(world_events_path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
            new_lines = [l for l in lines if not is_future_timestamp(l, current_day, current_hour, current_min)]
            if len(new_lines) != len(lines):
                with open(world_events_path, "w", encoding="utf-8") as fw:
                    fw.writelines(new_lines)
                logging.info(f"CULL: Culled {len(lines) - len(new_lines)} lines from world_events.txt")
        except Exception as e:
            logging.warning(f"CULL: Error processing world_events.txt: {e}")

    return jsonify({"status": "ok"})


def switch_campaign(name):
    global ACTIVE_CAMPAIGN, LIVE_CONTEXTS, EVENT_HISTORY, EVENT_HISTORY_SET, _RUMORS_CACHE_MTIME
    cdir = os.path.join(CAMPAIGNS_DIR, name)
    if os.path.exists(cdir):
        ACTIVE_CAMPAIGN = name
        save_settings({"current_campaign": name})  # Persist across restarts
        # Clear volatile state
        clear_live_context_cache()
        EVENT_HISTORY = []
        EVENT_HISTORY_SET = set()
        _RUMORS_CACHE_MTIME = 0.0
        load_campaign_config()
        update_world_index()  # Re-scan save for new campaign context
        return True
    return False


@app.route('/history', methods=['POST'])
def get_history():
    logging.info("ROUTE: /history [POST]")
    data = request.json or {}

    # Accept both 'npc' (from Library) and 'name' (from older calls)
    npc_name = data.get('npc', data.get('name', 'Someone'))

    logging.info(f"HISTORY: Request for {npc_name}")

    # CRITICAL: Clean the name from pipes (serial IDs) before any lookup.
    clean_npc_name = npc_name.split('|')[0] if '|' in npc_name else npc_name
    context = data.get('context', '')

    # DIRECT FILE LOAD — context-first resolution, never arbitrary filesystem order.
    # Uses the same identity pipeline as /chat to pick the right file.
    char_data = None
    safe_fn = _safe_char_filename(clean_npc_name)

    ident = _context_identity_summary(context, fallback_name=clean_npc_name)
    strength = ident.get("strength", 0)

    if strength >= 2:
        # Context yielded a storage_id — try that exact file, no scanning needed.
        sid = ident["storage_id"]
        char_data = load_existing_profile(sid, name=clean_npc_name)
        if char_data:
            logging.info(f"HISTORY: Resolved {clean_npc_name} via context storage_id {sid}")

    elif strength == 1:
        # Name only (no faction in context). Try plain Name.cfg first (unambiguous),
        # then scan for a single faction-qualified file. Multiple candidates → ambiguous,
        # fall through to get_character_data rather than guess.
        char_data = load_existing_profile(clean_npc_name, name=clean_npc_name)
        if char_data:
            logging.info(f"HISTORY: Resolved {clean_npc_name} via plain name file")

        if not char_data and os.path.exists(CHARACTERS_DIR):
            prefix = safe_fn + "_"
            scan_candidates = [
                os.path.join(CHARACTERS_DIR, fname)
                for fname in os.listdir(CHARACTERS_DIR)
                if fname.startswith(prefix) and (fname.endswith(".cfg") or fname.endswith(".json"))
            ]
            if len(scan_candidates) == 1:
                try:
                    f_name = os.path.basename(scan_candidates[0])
                    # If it's a Dack file, extract ID directly so history resolves properly.
                    if f_name.endswith('.cfg'):
                        temp_data = dack.load(scan_candidates[0])
                        sid = temp_data.get('ID', f_name.replace(".cfg", ""))
                    else:
                        sid = f_name.replace(".json", "")

                    char_data = load_existing_profile(sid, name=clean_npc_name)
                    if char_data:
                        logging.info(f"HISTORY: Resolved {clean_npc_name} via unambiguous scan {f_name}")
                except Exception as e:
                    logging.error(f"HISTORY: Scan load failed for {scan_candidates[0]}: {e}")
            elif len(scan_candidates) > 1:
                logging.info(f"HISTORY: Ambiguous direct candidates for {clean_npc_name}; falling back to get_character_data")

    # strength == 0: empty context — fall through directly to get_character_data.

    # Fallback to standard resolution when direct load didn't find a safe match.
    # skip_generate=True: /history must never create a new profile — return empty history if absent.
    if not char_data:
        logging.debug(f"HISTORY: Falling back to get_character_data for {clean_npc_name}")
        char_data = get_character_data(clean_npc_name, context, skip_generate=True)

    # Schema migration for legacy files
    if "ConversationHistory" not in char_data:
        char_data["ConversationHistory"] = []
    if "Race" not in char_data:
        char_data["Race"] = "Unknown"
    if "Faction" not in char_data:
        char_data["Faction"] = "Unknown"

    # Return full history as requested
    history = char_data.get('ConversationHistory', [])

    def _wrap(text):
        if not text:
            return ""
        paragraphs = text.split('\n')
        wrapped = []
        for p in paragraphs:
            if not p.strip():
                wrapped.append("")
                continue
            wrapped.extend(textwrap.wrap(p, width=110))
        return "\n".join(wrapped)

    lines = []
    lines.append(f"--- PROFILE: {char_data.get('Name', clean_npc_name)} ---")
    lines.append(f"Faction: {char_data.get('Faction', 'Unknown')} | Race: {char_data.get('Race', 'Unknown')}")
    lines.append(generate_relation_bar(char_data.get('Relation', 0)))
    lines.append("-" * 30)
    lines.append("PERSONALITY:")
    lines.append(_wrap(char_data.get('Personality', 'Unknown')))
    lines.append("")
    lines.append("BACKSTORY:")
    lines.append(_wrap(char_data.get('Backstory', 'Unknown')))
    lines.append("-" * 30)
    lines.append(f"CONVERSATION LOG (Showing last 250 of {len(history)} lines):")
    if history:
        # Limit display to 250 lines to prevent UI freeze
        trimmed_history = history[-250:]
        for log_line in trimmed_history:
            lines.append(_wrap(log_line))
    else:
        lines.append("(No history recorded)")

    formatted_output = "\n".join(lines)

    logging.info(f"HISTORY: Returning formatted report for {clean_npc_name} ({len(history)} lines)")
    return jsonify({
        "status": "ok",
        "text": formatted_output
    })


@app.route('/characters', methods=['GET', 'POST'])
def list_characters():
    data = request.json or {}
    sort_mode = data.get("sort", "alphabetical")  # alphabetical or latest

    settings = load_settings()
    favorites = settings.get("favorites", [])

    logging.info(f"Scanning for characters in: {CHARACTERS_DIR} (Sort: {sort_mode})")
    if not os.path.exists(CHARACTERS_DIR):
        return jsonify({"status": "ok", "characters": ""})

    npc_list = []
    for f in os.listdir(CHARACTERS_DIR):
        if not f.endswith('.cfg'):
            continue
        fpath = os.path.join(CHARACTERS_DIR, f)
        try:
            mtime = os.path.getmtime(fpath)
            cdata = dack.load(fpath)
            storage_id = str(cdata.get('ID') or "").strip()
            if not storage_id:
                raise ValueError("missing character ID")
            display = cdata.get('Name', storage_id)

            npc_list.append({
                "display": display,
                "sid": storage_id,
                "mtime": mtime,
                "is_fav": storage_id in favorites
            })
        except Exception as e:
            logging.warning(f"CHARACTERS: Skipping unreadable character file {f}: {e}")
            continue

    # Deduplicate by storage ID — same NPC cannot appear twice, but same-name NPCs
    # remain distinct entries.
    unique_npcs = {}
    for n in npc_list:
        sid = n["sid"]
        if sid not in unique_npcs or n["mtime"] > unique_npcs[sid]["mtime"]:
            unique_npcs[sid] = n

    final_list = list(unique_npcs.values())

    # Sorting logic
    if sort_mode == "latest":
        final_list.sort(key=lambda x: x["mtime"], reverse=True)
    else:
        final_list.sort(key=lambda x: x["display"].lower())

    # Favorites always on top
    favs = [n for n in final_list if n["is_fav"]]
    others = [n for n in final_list if not n["is_fav"]]

    sorted_npcs = favs + others

    names = [f"{n['display']}|{n['sid']}" for n in sorted_npcs]

    return jsonify({
        "status": "ok",
        "characters": ",".join(names),
        "names": ",".join(names),
        "favorites": favorites
    })


@app.route('/favorite', methods=['POST'])
def toggle_favorite():
    data = request.json or {}
    sid = data.get("sid")
    if not sid:
        return jsonify({"status": "error"}), 400

    settings = load_settings()
    favorites = settings.get("favorites", [])

    if sid in favorites:
        favorites.remove(sid)
        status = "removed"
    else:
        favorites.append(sid)
        status = "added"

    settings["favorites"] = favorites
    save_settings(settings)

    return jsonify({"status": "ok", "state": status})


@app.route('/player_profile', methods=['GET', 'POST'])
def player_profile_route():
    # Robust handling for C++ client sending empty JSON body
    data = None
    if request.is_json:
        try:
            data = request.get_json(silent=True)
        except:
            pass

    # If GET, or POST with no usable JSON (loading call)
    if request.method == 'GET' or not data:
        logging.info("PROMPT: Loading player profile (GUI request).")
        bio = load_prompt_component("character_bio.txt", "A mysterious drifter.")
        faction = load_prompt_component("player_faction_description.txt", "")
        return jsonify({
            "status": "ok",
            "character_bio": bio,
            "player_faction": faction
        })
    else:
        # Save
        bio = data.get("character_bio")
        faction = data.get("player_faction")

        cdir = get_campaign_dir()
        if bio is not None:
            with open(os.path.join(cdir, "character_bio.txt"), "w", encoding="utf-8") as f:
                f.write(bio)
        if faction is not None:
            with open(os.path.join(cdir, "player_faction_description.txt"), "w", encoding="utf-8") as f:
                f.write(faction)

        logging.info("PROMPT: Player profile updated via UI.")
        return jsonify({"status": "ok"})


@app.route('/test_connection', methods=['POST'])
def test_connection():
    logging.info("Testing LLM connection...")
    test_prompt = [{"role": "user", "content": "You are a Kenshi NPC. Say 'Connection Successful!' in a very short way."}]
    try:
        response = call_llm(test_prompt, max_tokens=20)
        if response:
            logging.info(f"Test Successful: {response}")
            return f"NOTIFY: Connection Successful! AI says: {response}", 200
        else:
            return "NOTIFY: ERROR: No response from AI. Check your API key and Provider settings.", 200
    except Exception as e:
        logging.error(f"Test Failed: {e}")
        return f"NOTIFY: ERROR: {str(e)}", 200


@app.route('/reset', methods=['POST'])
def reset_server():
    logging.info("Resetting server state...")
    try:
        clear_live_context_cache()
        load_configs()
        build_world_index()
        logging.info("Server reset complete (Cache cleared, configs reloaded).")
        return "NOTIFY: Server Reset Complete (Identity cache cleared and configs reloaded).", 200
    except Exception as e:
        return f"NOTIFY: Reset failed: {str(e)}", 200


def synthesis_loop():
    """Background loop to periodically synthesize world rumors."""
    logging.info("NARRATIVE: Synthesis background loop started.")
    elapsed_minutes = 0
    while True:
        try:
            settings = load_settings()
            interval = settings.get("synthesis_interval_minutes", 15)
            if interval < 1:
                interval = 1  # Safety

            SYNTHESIS_STATUS["interval"] = interval

            # If interval was shortened below current elapsed, trigger now
            if elapsed_minutes >= interval:
                logging.info(f"NARRATIVE: Interval shortened ({interval}m). Triggering synthesis.")
                generate_global_narrative_thread()
                elapsed_minutes = 0
                SYNTHESIS_STATUS["elapsed"] = 0
                continue

            # Sleep in smaller chunks to be responsive to game state changes
            for _ in range(6):  # 6 × 10s = ~60s per loop iteration
                time.sleep(10)

            # After ~60s of real time, check if game was running
            speed = PLAYER_CONTEXT.get("gamespeed", 1.0)

            if speed > 0.1:
                elapsed_minutes += 1
                SYNTHESIS_STATUS["elapsed"] = elapsed_minutes
                if elapsed_minutes % 10 == 0:
                    logging.info(f"NARRATIVE: Timer progress: {elapsed_minutes}/{interval} minutes.")

            if elapsed_minutes >= interval:
                logging.info(f"NARRATIVE: Timer reached ({interval}m). Triggering periodic synthesis.")
                generate_global_narrative_thread()
                elapsed_minutes = 0
                SYNTHESIS_STATUS["elapsed"] = 0

        except Exception as e:
            logging.error(f"Error in synthesis loop: {e}")
            time.sleep(60)


# Start synthesis thread
threading.Thread(target=synthesis_loop, daemon=True).start()


def deferred_profile_flush_loop():
    """Periodically flush deferred profile batches when foreground chat is idle."""
    while True:
        try:
            flushed = flush_deferred_profile_batches()
            if flushed:
                logging.info(f"BATCH: Flushed {flushed} deferred profiles after direct chat.")
        except Exception as e:
            logging.error(f"Error in deferred profile flush loop: {e}")
        time.sleep(2)


# Start deferred profile flush thread
threading.Thread(target=deferred_profile_flush_loop, daemon=True).start()


def player2_ping_loop():
    """Periodically pings player2 server and refreshes p2Key if it is the active provider."""
    global PLAYER2_SESSION_KEY
    # Use debug for the thread start to stay out of the way for non-p2 users
    logging.debug("HEALTH: Player2 background thread initialized.")
    game_id = "019c93fc-7a93-7ac4-8c6e-df0fd09bec01"

    while True:
        try:
            model_entry = MODELS_CONFIG.get(CURRENT_MODEL_KEY)
            if model_entry and model_entry.get("provider") == "player2":
                # 1. Quick Start: Attempt to fetch fresh p2Key from local Player2 App
                # ONLY if we don't already have one (Beginning of session/usage)
                if not PLAYER2_SESSION_KEY:
                    try:
                        auth_url = f"http://localhost:4315/v1/login/web/{game_id}"
                        auth_resp = requests.post(auth_url, timeout=5)
                        if auth_resp.status_code == 200:
                            new_key = auth_resp.json().get("p2Key")
                            if new_key:
                                PLAYER2_SESSION_KEY = new_key
                                logging.info("HEALTH: Player2 session authorized at startup.")
                    except Exception as e:
                        # App might not be running or not logged in; silently fall back
                        pass

                # 2. Ping /health as a health check
                provider_config = PROVIDERS_CONFIG.get("player2")
                if provider_config:
                    base_url = (provider_config.get("base_url") or "").rstrip("/")
                    try:
                        # Use player2-game-key header and Authorization for health check
                        h = {
                            "player2-game-key": game_id,
                            "Authorization": f"Bearer {PLAYER2_SESSION_KEY}" if PLAYER2_SESSION_KEY else ""
                        }
                        resp = requests.get(f"{base_url}/health", headers=h, timeout=5)
                        if resp.status_code == 200:
                            logging.debug("HEALTH: Player2 server is UP")
                        else:
                            logging.warning(f"HEALTH: Player2 server returned status {resp.status_code}")
                    except Exception as e:
                        logging.error(f"HEALTH: Player2 server is DOWN or unreachable: {e}")

        except Exception as e:
            logging.error(f"Error in player2 background thread: {e}")

        time.sleep(60)


# Start player2 ping thread
threading.Thread(target=player2_ping_loop, daemon=True).start()


def monitor_kenshi_process():
    """Background thread that monitors the parent process (Kenshi) and exits if it's gone."""
    try:
        ppid = os.getppid()
        if ppid <= 1:
            logging.info("SYSTEM: Parent PID is 0 or 1, skipping auto-shutdown monitor.")
            return

        logging.info(f"SYSTEM: Monitoring parent process (PID {ppid}) for auto-shutdown.")

        # Windows constants
        PROCESS_QUERY_INFORMATION = 0x0400
        STILL_ACTIVE = 259

        # Use ctypes for more reliable process checking on Windows
        kernel32 = ctypes.windll.kernel32

        while True:
            handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, ppid)
            if not handle:
                # If we can't open it, the process is likely gone
                logging.info(f"SYSTEM: Parent Kenshi process (PID {ppid}) no longer found. Shutting down server.")
                os._exit(0)

            exit_code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                if exit_code.value != STILL_ACTIVE:
                    kernel32.CloseHandle(handle)
                    logging.info(f"SYSTEM: Parent Kenshi process (PID {ppid}) has exited. Shutting down server.")
                    os._exit(0)
            else:
                # GetExitCodeProcess failed, might be gone
                kernel32.CloseHandle(handle)
                logging.info(f"SYSTEM: Failed to query parent process state. Assuming it closed. Shutting down server.")
                os._exit(0)

            kernel32.CloseHandle(handle)
            time.sleep(5)

    except Exception as e:
        logging.error(f"SYSTEM: Error in kenshi process monitor: {e}")


# Start Kenshi monitor thread
threading.Thread(target=monitor_kenshi_process, daemon=True).start()


# --- WEB DEBUGGER ROUTES (v2.0) ---


@app.route('/debugger')
def serve_debugger():
    """Serve the modern web-based visual debugger."""
    return render_template('debugger.html')


@app.route('/models', methods=['GET'])
def get_models_alias():
    """Alias for settings endpoint to satisfy web debugger."""
    return settings_endpoint()


@app.route('/api/command', methods=['POST'])
def web_command():
    """Relay commands from the web UI to the Kenshi pipe."""
    data = request.json or {}
    cmd = data.get('command')
    if not cmd:
        return jsonify({"status": "error", "message": "Missing command"}), 400

    # Handle specialized web commands
    if cmd == "MANUAL_SYNTHESIZE":
        generate_global_narrative_thread()
        return jsonify({"status": "ok", "message": "Synthesis triggered"})
    elif cmd == "RESCAN_SAVES":
        update_world_index()
        return jsonify({"status": "ok", "message": "Save index updated"})
    elif cmd == "RESET_SERVER":
        clear_live_context_cache()
        LAST_STATE_LOG.clear()
        EVENT_THROTTLE.clear()
        return jsonify({"status": "ok", "message": "Server state reset"})

    # Standard pipe relay
    send_to_pipe(cmd)
    logging.info(f"WEB_CMD: Relayed command: {cmd}")
    return jsonify({"status": "ok"})


@app.route('/api/test_trade', methods=['POST'])
def test_trade_alias():
    """Endpoint for debugger to test item normalization"""
    data = request.json or {}
    item = data.get('item', '')
    if not item:
        return jsonify({"status": "error", "message": "Missing item name"}), 400
    normalized = normalize_trade_item_name(item)
    return jsonify({"status": "ok", "original": item, "normalized": normalized})


@app.route('/api/logs/<path:log_name>')
def stream_logs(log_name):
    """Serve log files for the real-time event feed."""
    if ".." in log_name:
        return "Access Denied", 403

    # Priority 1: server.log or llm_debug.log (the main tool/app logs)
    if log_name in ["server.log", "llm_debug.log"]:
        log_path = os.path.join(KENSHI_SERVER_DIR, "logs", log_name)
        if os.path.exists(log_path):
            return send_from_directory(os.path.dirname(log_path), os.path.basename(log_path))

    # Priority 2: campaign-specific logs
    log_dir = os.path.join(get_campaign_dir(), "logs")
    if os.path.exists(os.path.join(log_dir, log_name)):
        return send_from_directory(log_dir, log_name)

    # Priority 3: general logs fallback
    fallback_dir = os.path.join(KENSHI_SERVER_DIR, "logs")
    return send_from_directory(fallback_dir, log_name)


if __name__ == '__main__':
    logging.info("Kenshi LLM Server Starting on port 5000...")
    # Enable threaded=True to handle multiple simultaneous requests (polling + settings)
    app.run(host='127.0.0.1', port=5000, threaded=True)
