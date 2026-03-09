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

import os
import ctypes
import json
import logging
import subprocess
import signal
import requests
import re
import time
import threading
import random
import configparser
from flask import Flask, request, jsonify
import sys
import logging.handlers
import traceback
import collections

# --- PATH DEFINITIONS (The absolute source of truth) ---
SCRIPT_PATH = os.path.abspath(__file__)
SCRIPT_DIR = os.path.dirname(SCRIPT_PATH)
KENSHI_SERVER_DIR = os.path.dirname(SCRIPT_DIR)
KENSHI_MOD_DIR = os.path.dirname(KENSHI_SERVER_DIR)
KENSHI_ROOT = os.path.dirname(os.path.dirname(KENSHI_MOD_DIR))

# Explicitly add script dir to path for imports
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from save_reader import build_world_index

# --- CORE GLOBALS & CONFIG PATHS ---
def resolve_mod_file(filename):
    """
    Helper to find a file in the mod directory.
    Normally files are in KENSHI_MOD_DIR (the root of the mod).
    During development they might be in a 'SentientSands_Mod' subdirectory.
    """
    # 1. Primary: Mod Root (Deployed state)
    path = os.path.join(KENSHI_MOD_DIR, filename)
    if os.path.exists(path):
        return path
        
    # 2. Secondary: Development Subfolder
    dev_path = os.path.join(KENSHI_MOD_DIR, "SentientSands_Mod", filename)
    if os.path.exists(dev_path):
        return dev_path
        
    # 3. Tertiary: Sibling project folder (Source layout)
    alt_path = os.path.join(os.path.dirname(KENSHI_MOD_DIR), "SentientSands_Mod", filename)
    if os.path.exists(alt_path):
        return alt_path

    return path

INI_PATH = resolve_mod_file("SentientSands_Config.ini")
MODELS_PATH = os.path.join(KENSHI_SERVER_DIR, "config", "models.json")
PROVIDERS_PATH = os.path.join(KENSHI_SERVER_DIR, "config", "providers.json")
NAMES_PATH = os.path.join(KENSHI_SERVER_DIR, "config", "names.json")
GENERIC_NAMES_PATH = os.path.join(KENSHI_SERVER_DIR, "config", "generic_names.json")
LOCALIZATION_PATH = os.path.join(KENSHI_SERVER_DIR, "config", "localization.json")

MODELS_CONFIG = {}
PROVIDERS_CONFIG = {}
NAMES_CONFIG = {}
GENERIC_CONFIG = {}
CURRENT_MODEL_KEY = "player2-default" # Default
ACTIVE_CAMPAIGN = "Default"      # Default

CAMPAIGNS_DIR = os.path.join(KENSHI_SERVER_DIR, "campaigns")
TEMPLATES_DIR = os.path.join(KENSHI_SERVER_DIR, "templates")
CHARACTERS_DIR = os.path.join(KENSHI_SERVER_DIR, "characters") # Initial fallback
CURRENT_CAMPAIGN = "Default" # Global track for UI
LAST_GENERATE_TIME = 0 # Track last rumor timestamp
GLOBAL_SYNTHESIS_INTERVAL = 60 # Default minutes

EVENT_HISTORY = []
PROFILES_IN_PROGRESS = set()
PROGRESS_LOCK = threading.Lock()
LIVE_CONTEXTS = {}
PLAYER_CONTEXT = {}
LAST_NPC_NAME = None
PLAYER2_SESSION_KEY = None
EVENT_THROTTLE = {} 
THROTTLE_LOCK = threading.Lock()
LAST_STATE_LOG = {} # { "NPCName|etype": "last_msg" }
STATE_LOCK = threading.Lock()
SYNTHESIS_STATUS = {"elapsed": 0, "interval": 60}

MAJOR_FACTIONS = [
    "The Holy Nation", "United Cities", "Shek Kingdom",
    "Traders Guild", "Slave Traders", "Western Hive",
    "Anti-Slavers", "Flotsam Ninjas", "Mongrel", "The Hub",
    "Hounds", "Deadcat", "Black Desert City"
]

ANIMAL_RACES = [
    "Bonedog", "Boneyard Wolf", "Garru", "Beak Thing", "Gorillo",
    "Landbat", "Goat", "Bull", "Leviathan", "Blood Spider", "Skin Spider",
    "Cave Crawler", "Crab", "Raptor", "Darkfinger", "Thrasher", "Cleaner",
    "Crimper", "Skimmer", "Beeler", "Bat", "Spider", "Wolf",
    "Dog", "Turtle", "Cleanser", "Gurgler", "Fishman"
]

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

def get_config_radii():
    settings = load_settings()
    # Use radii from settings if present, otherwise fall back to defaults
    r = float(settings.get('radiant_range', 100.0))
    t = float(settings.get('talk_radius', 100.0))
    y = float(settings.get('yell_radius', 200.0))
    return r, t, y
def sanitize_llm_text(text):
    if not text: return ""
    # Replace common unicode/smart characters that Kenshi's engine might choke on
    replacements = {
        '\u2018': "'", '\u2019': "'", # Smart single quotes
        '\u201c': '"', '\u201d': '"', # Smart double quotes
        '\u2013': '-', '\u2014': '-', # En/Em dashes
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
    if not text: return None
    
    # 1. Basic cleaning
    text = text.strip()
    
    # 2. Extract content between first { and last }
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1:
        return None
    
    json_str = text[start:end+1]
    
    # 3. Remove trailing commas within arrays/objects using regex
    json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
    
    # 4. Filter out any single-line comments // or multi-line /* */
    json_str = re.sub(r'//.*?\n', '\n', json_str)
    json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
    
    try:
        return json.loads(json_str)
    except Exception as eFirst:
        # 5. Attempt: Sanitize unescaped quotes in middle of strings
        # Looks for " surrounded by letters/numbers which are usually internal dialogue quotes
        try:
            sanitized = re.sub(r'(?<=[a-zA-Z0-9])"(?=[a-zA-Z0-9\s])', "'", json_str)
            return json.loads(sanitized)
        except:
            logging.error(f"ROBUST_JSON_PARSE: Final failure on string: {json_str[:200]}...")
            raise eFirst

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
    _file_handler = logging.handlers.RotatingFileHandler(_log_file, maxBytes=512*1024, backupCount=3, encoding='utf-8')
    _file_handler.setFormatter(_log_fmt)
    
    _stream_handler = logging.StreamHandler()
    _stream_handler.setFormatter(_log_fmt)
    
    # debug.log: 1MB limit, 1 backup
    _debug_handler = logging.handlers.RotatingFileHandler(_debug_file, maxBytes=1024*1024, backupCount=1, encoding='utf-8')
    _debug_handler.setFormatter(_log_fmt)
    _debug_handler.setLevel(logging.DEBUG)

    # Global config
    logging.basicConfig(level=logging.INFO, handlers=[_stream_handler, _file_handler, _debug_handler])
    
    # Specialized logger for high-volume telemetry (prompts, raw data)
    # This prevents server.log from becoming a wall of text.
    debug_logger = logging.getLogger('kenshi_debug')
    debug_logger.setLevel(logging.DEBUG)
    debug_logger.addHandler(_debug_handler)
    debug_logger.propagate = False # Do not double-log to root handlers

except Exception as e:
    # Fallback to stream only if file handler fails
    logging.basicConfig(level=logging.INFO)
    logging.error(f"Failed to initialize file logging: {e}")

# Silence noise
logging.getLogger('werkzeug').setLevel(logging.ERROR)
logging.getLogger('urllib3').setLevel(logging.WARNING)

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
                    time.sleep(1) # Give it a moment to clear the port
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
    global CHARACTERS_DIR, EVENT_HISTORY
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
                logging.info(f"CAMPAIGN: Loaded {len(EVENT_HISTORY)} events for '{ACTIVE_CAMPAIGN}'")
            except Exception as e:
                logging.error(f"Failed to load event history: {e}")
                EVENT_HISTORY = []
        else:
            EVENT_HISTORY = []
        # 3. Push generic names to DLL
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
    if not name: return True
    
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
    "Reaver", "Grass Pirate", "Black Dog", "Crab Raider", "Skeleton Bandit",
    "Bar Thug", "Barman", "Pacifier"
]

KENSHI_NAME_POOL = [
    "Kaelen", "Korg", "Vayn", "Sark", "Mina", "Rook", "Drake", "Silas", "Tane", "Kuna",
    "Zarek", "Jorn", "Lyra", "Kael", "Brena", "Torin", "Sola", "Fen", "Krax", "Vora",
    "Dax", "Nyx", "Garek", "Sora", "Thane", "Kira", "Zane", "Lara", "Marek", "Vina",
    "Rel", "Kaan", "Siv", "Tork", "Meda", "Grox", "Vael", "Syra", "Keld", "Bara",
    "Dorn", "Neld", "Gora", "Sark", "Vane", "Kura", "Zora", "Lena", "Morn", "Vora",
    "Rael", "Kona", "Sima", "Teld", "Mora", "Grak", "Vael", "Sura", "Karn", "Bena",
    "Drak", "Nala", "Gora", "Sina", "Vara", "Kela", "Zana", "Lina", "Mina", "Vorna",
    "Hark", "Skal", "Vorn", "Grek", "Myla", "Rion", "Daka", "Sith", "Tyla", "Korr",
    "Zent", "Lyr", "Brax", "Vort", "Nara", "Grel", "Syk", "Tarn", "Moko", "Vull",
    "Kess", "Tory", "Vann", "Sael", "Miro", "Lorn", "Gryf", "Dael", "Sina", "Kura"
]

def get_used_names():
    if not os.path.exists(CHARACTERS_DIR): return set()
    names = set()
    for f in os.listdir(CHARACTERS_DIR):
        if f.endswith(".json"):
            base = f.replace(".json", "")
            # Handle both formats: Name.json and Name_Faction.json
            if "_" in base:
                name = base.split("_")[0]
                names.add(name.lower())
            else:
                names.add(base.lower())
    return names

def generate_unique_lore_name(gender="Neutral"):
    used = get_used_names()
    
    gender_key = "Neutral"
    if gender.lower() == "male": gender_key = "Male"
    elif gender.lower() == "female": gender_key = "Female"
    
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
    bar[pos] = "X" # Marker
    bar_str = "".join(bar)
    
    # Status Label
    label = "NEUTRAL"
    if rel <= -90: label = "ARCH-ENEMY"
    elif rel <= -60: label = "HOSTILE"
    elif rel <= -25: label = "UNFRIENDLY"
    elif rel >= 90: label = "SOUL-MATE"
    elif rel >= 60: label = "ALLIED"
    elif rel >= 25: label = "FRIENDLY"
    
    # Add color tags for MyGUI (if supported, using # prefix)
    # Actually, let's keep it plain text for max compatibility across UI versions
    return f"RELATION: [{label}] [{bar_str}] ({rel:+} pts)"

def is_future_timestamp(line, cur_d, cur_h, cur_m):
    """Checks if a string containing [Day X, HH:MM] is ahead of the provided current time."""
    match = re.search(r"\[Day (\d+)(?:, (\d+):(\d+))?\]", line)
    if not match: return False
    d = int(match.group(1))
    h = int(match.group(2)) if match.group(2) else 0
    m = int(match.group(3)) if match.group(3) else 0
    if d > cur_d: return True
    if d < cur_d: return False
    if h > cur_h: return True
    if h < cur_h: return False
    return m > cur_m


# Mappings for Kenshi enums

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

def build_detailed_context_string(npc_name, char_data=None):
    # Try to get live context for this specific NPC
    ctx = LIVE_CONTEXTS.get(npc_name)
    
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
        "imprisoned":     f"CRITICAL: {npc_name} is currently IMPRISONED. They are locked up and cannot move freely. They should speak with desperation, resignation, or defiance.",
        "enslaved":       f"CRITICAL: {npc_name} is ENSLAVED and wearing shackles. They are bound to a master. They should speak with fear, exhaustion, or suppressed rage.",
        "escaped-slave":  f"CRITICAL: {npc_name} is an ESCAPED SLAVE — no longer chained but hunted. They should be paranoid, guarded, and desperate.",
        "unconscious":    f"CRITICAL: {npc_name} is UNCONSCIOUS and cannot speak.",
        "dead":           f"CRITICAL: {npc_name} is DEAD.",
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
        lines.append(shop_note)
    
    # Leader Status
    if ctx.get("is_leader", False):
        lines.append(f"ROLE: {npc_name} is the LEADER of their faction. They speak with authority and make final decisions for their group.")

    lines.append(f"- CURRENT GOAL/JOB: {job}")
    if relation is not None:
        lines.append(f"- FACTION RELATION TO PLAYER: {relation} (Stance: {'ALLIED' if relation >= 50 else 'FRIENDLY' if relation > 0 else 'NEUTRAL' if relation == 0 else 'HOSTILE' if relation <= -30 else 'UNFRIENDLY'})")
    lines.append(f"- MONEY: {money} cats")

    # Group Leader Awareness
    player_faction = PLAYER_CONTEXT.get('faction', 'Nameless')
    if faction == player_faction or ctx.get("factionID") == "Nameless":
        lines.append(f"CRITICAL CONTEXT: {npc_name} is a member of the PLAYER'S FACTION ({player_faction}).")
        lines.append(f"THE PLAYER IS THE LEADER of this group. {npc_name} understand that they and the player are cooperating, this can take many forms such as direct leadership, partnership, or even just individuals traveling together.")
    elif any(f.lower() in faction.lower() for f in MAJOR_FACTIONS):
        lines.append(f"LOYALTY NOTE: {npc_name} belongs to {faction}, a major world power. They are deeply rooted in their society. They will NOT desert their faction to join the player's minor squad without an EXTREMELY compelling narrative reason, high reputation, or having their life saved multiple times. Be highly resistant to recruitment.")
    # Medical
    med = ctx.get("medical", {})
    if med:
        blood = med.get("blood", 100)
        hunger = med.get("hunger", 300)
        limbs = med.get("limbs", {})
        
        status_parts = []
        
        # Hunger Logic
        if hunger < 100: status_parts.append("STARVING")
        elif hunger < 250: status_parts.append("HUNGRY")
        else: status_parts.append("WELL FED") 
        
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
            
        if med.get("is_unconscious"): status_parts.append("UNCONSCIOUS")
        
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
        if env.get("indoors"): loc.append("Indoors")
        if env.get("in_town"): loc.append(f"In town ({env.get('town_name', 'Unknown')})")
        if loc: lines.append(f"- LOCATION: {', '.join(loc)}")

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
            if val > 15: # Only show competent skills
                notable.append(f"{s.replace('_', ' ').capitalize()}: {val}")
        if notable:
            lines.append(f"- NOTABLE SKILLS: {', '.join(notable)}")

    # Memories
    mem = ctx.get("memories", {})
    st = [SHORT_TERM_MEM.get(m, str(m)) for m in mem.get("short_term", [])]
    lt = [LONG_TERM_MEM.get(m, str(m)) for m in mem.get("long_term", [])]
    
    if st or lt:
        lines.append(f"PERCEPTION OF PLAYER:")
        if st: lines.append(f"- SHORT TERM: {', '.join(st)}")
        if lt: lines.append(f"- HISTORY TAGS: {', '.join(lt)}")
        
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
            # Show first 12 for brevity
            for item in held[:12]:
                lines.append(f"- {item['name']} (x{item.get('count', 1)})")
            if len(held) > 12:
                lines.append(f"- ... (and {len(held)-12} other items)")
    else:
        lines.append(f"INVENTORY: Empty")

    # Nearby Awareness (Sensory Perception)
    nearby = ctx.get("nearby", [])
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

# Mapping of internal setting keys to INI [Settings] keys
INI_KEY_MAP = {
    "current_model": "CurrentModel",
    "current_campaign": "ActiveCampaign",
    "enable_ambient": "EnableAmbientConversations",
    "radiant_delay": "RadiantDelay",
    "global_events_count": "GlobalEventsCount",
    "synthesis_interval_minutes": "SynthesisIntervalMinutes",
    "favorites": "Favorites",
    "radiant_range": "RadiantRange",
    "talk_radius": "TalkRadius",
    "yell_radius": "YellRadius",
    "min_faction_relation": "MinFactionRelation",
    "max_faction_relation": "MaxFactionRelation",
    "enable_welcome": "EnableWelcomePopup",
    "dialogue_speed_seconds": "DialogueSpeed",
    "bubble_life": "SpeechBubbleLife",
    "language": "Language"
}

def _save_settings_raw(settings):
    """Save settings to SentientSands_Config.ini."""
    try:
        config = configparser.ConfigParser()
        if os.path.exists(INI_PATH):
            config.read(INI_PATH)
        
        if 'Settings' not in config:
            config['Settings'] = {}
            
        for k, v in settings.items():
            ini_key = INI_KEY_MAP.get(k)
            if ini_key:
                if isinstance(v, list):
                    config['Settings'][ini_key] = ",".join(v)
                elif isinstance(v, bool):
                    config['Settings'][ini_key] = "1" if v else "0"
                else:
                    config['Settings'][ini_key] = str(v)
        
        with open(INI_PATH, "w") as f:
            config.write(f)
        # logging.info(f"Saved settings to INI: {INI_PATH}")
    except Exception as e:
        logging.error(f"Error saving Settings to INI at {INI_PATH}: {e}")

def load_settings():
    defaults = {
        "current_model": "player2-default",
        "current_campaign": "Default",
        "enable_ambient": True,
        "radiant_delay": 240,
        "global_events_count": 5,
        "synthesis_interval_minutes": 15,
        "favorites": [],
        "radiant_range": 100,
        "talk_radius": 100,
        "yell_radius": 200,
        "min_faction_relation": -100,
        "max_faction_relation": 100,
        "enable_welcome": True,
        "dialogue_speed_seconds": 5,
        "bubble_life": 5.0,
        "language": "English"
    }
    
    settings = defaults.copy()
    if os.path.exists(INI_PATH):
        try:
            config = configparser.ConfigParser()
            config.read(INI_PATH)
            if 'Settings' in config:
                for k in defaults.keys():
                    ini_key = INI_KEY_MAP.get(k)
                    if ini_key and ini_key in config['Settings']:
                        val = config['Settings'][ini_key]
                        # Type conversion
                        if isinstance(defaults[k], bool):
                            settings[k] = (val == "1" or val.lower() == "true")
                        elif isinstance(defaults[k], int):
                            try: settings[k] = int(val)
                            except: pass
                        elif isinstance(defaults[k], float):
                            try: settings[k] = float(val)
                            except: pass
                        elif isinstance(defaults[k], list):
                            settings[k] = [x.strip() for x in val.split(",") if x.strip()]
                        else:
                            settings[k] = val
        except Exception as e:
            logging.error(f"Error loading settings from INI: {e}")
            
    return settings

def save_settings(new_settings):
    # Flatten multi-level structures if they come in (like radii)
    flat_changes = {}
    for k, v in new_settings.items():
        if k == "radii" and isinstance(v, dict):
            if "radiant" in v: flat_changes["radiant_range"] = v["radiant"]
            if "talk" in v: flat_changes["talk_radius"] = v["talk"]
            if "yell" in v: flat_changes["yell_radius"] = v["yell"]
        else:
            flat_changes[k] = v
            
    settings = load_settings()
    settings.update(flat_changes)
    _save_settings_raw(settings)

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
        _save_settings_raw(settings)
        
        migrate_to_campaigns()
        load_campaign_config()
        # Load event history AFTER campaign is determined
        _load_event_history_from_log()
    except Exception as e:
        logging.error(f"INIT: Critical state init failure: {e}")

init_server_state()

def load_prompt_component(filename, default_text=""):
    # Try active campaign first
    path = os.path.join(get_campaign_dir(), filename)
    source = f"campaign:{ACTIVE_CAMPAIGN}"
    
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    # Log occasionally or on first load to verify
                    logging.info(f"PROMPT: Loaded {filename} from {source}")
                    return content
        except Exception as e:
            logging.error(f"Error reading {filename} from {source}: {e}")
    
    # Secondary Fallback: Try the templates directory (read-only)
    template_path = os.path.join(TEMPLATES_DIR, filename)
    if os.path.exists(template_path):
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    logging.info(f"PROMPT: Loaded {filename} from templates (read-only)")
                    return content
        except Exception as e:
            logging.error(f"Error reading {filename} from templates: {e}")

    # We no longer fall back to the mod root to ensure campaign isolation.
    return default_text

def format_player_status(player_ctx):
    """Summarizes player vitals and faction into a readable block."""
    if not player_ctx: return "No status data."
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
        if hunger < 80: status.append("STARVING")
        elif hunger < 200: status.append("VERY HUNGRY")
        elif hunger < 250: status.append("HUNGRY")
        
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
    if not player_ctx: return "No inventory data."
    inv = player_ctx.get("inventory", [])
    if not inv: return "Inventory: Empty or not visible."
    
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
    res += "CONCEALED (In Bag/Pack):\n" + ("\n".join([f"- {b}" for b in bag[:15]]) if bag else "- Bag appears empty.")
    if len(bag) > 15:
        res += f"\n- ... and {len(bag)-15} more items."
    return res

def build_system_prompt(player_name="Drifter"):
    player_bio = load_prompt_component("character_bio.txt", "A mysterious drifter.")
    player_faction_desc = load_prompt_component("player_faction_description.txt", "")
    npc_base = load_prompt_component("npc_base.txt", "You are an NPC in the world of Kenshi. Stay in character.")
    world_lore = load_prompt_component("world_lore.txt", "The world is a brutal, sword-punk wasteland.")
    rules = load_prompt_component("response_rules.txt", "Respond naturally to the player.")
    action_tags = load_prompt_component("prompt_action_tags.txt", "")
    
    # Combined World Events / Rumors
    settings = load_settings()
    ge_count = settings.get("global_events_count", 5)
    events_list = []
    
    # 1. Load Synthesized Rumors (High-level)
    world_events_path = os.path.join(get_campaign_dir(), "world_events.txt")
    if os.path.exists(world_events_path):
        try:
            with open(world_events_path, "r", encoding="utf-8") as f:
                rumors = [l.strip() for l in f.readlines() if l.strip().startswith("- [")]
                # Take most recent rumors
                events_list.extend(rumors[-max(1, ge_count//2):])
        except: pass

    # 2. Load Raw Event History (Recent logs)
    if EVENT_HISTORY:
        raw_recent = EVENT_HISTORY[-max(1, ge_count - len(events_list)):]
        for e in raw_recent:
            events_list.append(f"- {e}")

    events_block = ""
    if events_list:
        events_block = "WORLD STATUS & RUMORS (Hearsay):\n" 
        events_block += "The following are bits of gossip and recent news circulating in the wasteland. Do NOT prioritize these over your core identity or immediate situation. Mention them only if relevant to the conversation.\n"
        events_block += "\n".join(events_list[-ge_count:])

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

{events_block}

PLAYER CHARACTER ({player_name}):
RACE: {player_race}
GENDER: {player_gender}
{player_bio}

{faction_block}

--- PLAYER AWARENESS & SENSORY RULES ---
CRITICAL ROLEPLAY RULE: You can SEE the player's VISIBLE equipment, but you CANNOT see what is inside their BAG/PACK.
- Do NOT mention or react to items listed under 'CONCEALED' unless the player explicitly grants you permission in the dialogue (e.g., 'look in my bag', 'take a look at my loot').
- If the player is heavily armed (swords, crossbows WORN), comment on it if appropriate. 
- If they are starving or injured, reflect that in your tone.

{format_player_status(PLAYER_CONTEXT)}
{format_player_inventory(PLAYER_CONTEXT)}

RESPONSE FORMAT RULES:
{rules}

{action_tags}
{language_instruction}"""
    return prompt.strip()


# Initial build
SYSTEM_PROMPT = build_system_prompt()

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
        if not clean_name: continue
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

    base_url = provider_config.get("base_url").rstrip("/")
    target_url = f"{base_url}/chat/completions"

    # Default headers
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # OpenRouter specific headers (encouraged by their API)
    if "openrouter.ai" in target_url:
        headers["X-Title"] = "Sentient Sands Mod"
        headers["HTTP-Referer"] = "https://github.com/harvicusdev-glitch/SentientSands"

    # player2 specific header
    if provider_name == "player2":
        headers["player2-game-key"] = "019c93fc-7a93-7ac4-8c6e-df0fd09bec01"

    payload = {
        "model": model_entry["model"],
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": 0.9,
    }
    
    last_error = None
    for attempt in range(3):
        try:
            debug_logger.debug(f"LLM REQUEST [{provider_name}] to {target_url} (Payload omitted for security)")
            start_time = time.time()
            response = requests.post(target_url, headers=headers, json=payload, timeout=120)
            elapsed = time.time() - start_time
            
            if response.status_code == 200:
                if not response.text.strip():
                    logging.error(f"Attempt {attempt+1}: Provider returned 200 OK but the response body is EMPTY.")
                    raise Exception("Empty response from provider (possible content filter or token limit?)")
                try:
                    data = response.json()
                except json.JSONDecodeError as je:
                    logging.error(f"Attempt {attempt+1} JSON Error: Content provided by provider is not valid JSON despite 200 OK status.")
                    logging.error(f"RESPONSE PREVIEW (200 OK): {response.text[:500]}")
                    raise Exception(f"Invalid JSON response from provider: {str(je)}")

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

                logging.info(f"API Success in {elapsed:.1f}s (Attempt {attempt+1})")
                
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
                
                logging.error(f"Attempt {attempt+1} failed after {elapsed:.1f}s: {last_error}")
                if attempt < 2:
                    time.sleep(1)
            else:
                last_error = f"API ERROR {response.status_code}: {response.text[:200]}"
                logging.error(f"Attempt {attempt+1} failed after {elapsed:.1f}s: {last_error}")
                if attempt < 2:
                    time.sleep(1)

        except Exception as e:
            last_error = str(e)
            logging.error(f"Attempt {attempt+1} Exception: {e}")
            debug_logger.error(f"LLM EXCEPTION STACK (Attempt {attempt+1}):\n{traceback.format_exc()}")
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

def generate_character_profile(name, context=""):
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

    # Extract race/faction from context or LIVE_CONTEXTS
    live_ctx = LIVE_CONTEXTS.get(name) or {}
    
    race = "Unknown"
    gender = "Unknown"
    faction = "Unknown"
    
    # Try context first
    ctx_data = {}
    if isinstance(context, dict):
        ctx_data = context
    elif isinstance(context, str) and context.strip().startswith('{'):
        try:
            ctx_data = json.loads(context)
        except: pass
        
    if ctx_data:
        race = ctx_data.get('race', race)
        gender = ctx_data.get('gender', gender)
        faction = ctx_data.get('faction', faction)
        if faction == "Unknown":
            faction = ctx_data.get('factionID', "Unknown")
        origin_faction = ctx_data.get('origin_faction', "Unknown")
        job = ctx_data.get('job', "None")
    
    # Fallback to LIVE_CONTEXTS if still unknown
    if race == "Unknown": race = live_ctx.get('race', 'Unknown')
    if gender == "Unknown": gender = live_ctx.get('gender', 'Unknown')
    if faction == "Unknown": 
        faction = live_ctx.get('faction', 'Unknown')
        if faction == "Unknown":
            faction = live_ctx.get('factionID', "Unknown")
    
    if origin_faction == "Unknown": origin_faction = live_ctx.get('origin_faction', 'Unknown')
    if job == "None": job = live_ctx.get('job', 'None')
    
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
    response_text = call_llm(messages, max_tokens=600, temperature=0.7)
    
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
        "Sex": gender
    }

def generate_batch_profiles(npc_list):
    """Lump multiple NPC profile generations into a single LLM call."""
    if not npc_list: return
    
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
    
    logging.info(f"BATCH: Generating {len(complete)} profiles in one call ({len(npc_list) - len(complete)} deferred)...")
    
    # Prepare descriptions
    descriptions = []
    for npc in complete:
        name = npc.get('name', 'Unknown')
        race = npc.get('race', 'Unknown')
        gender = npc.get('gender', 'Unknown')
        faction = npc.get('faction', 'Unknown')
        f_info = get_faction_info(faction)
        descriptions.append(f"- Name: {name}, Sex: {gender}, Race: {race}, Faction: {f_info}")
    
    desc_str = "\n".join(descriptions)
    
    template = load_prompt_component("prompt_batch_profile_generation.txt", """You are an expert on Kenshi lore. 
Task: Generate character profiles for several NPCs at once.

NPCS TO GENERATE:
{desc_str}

CRITICAL RULES:
1. CANON FIRST: If a name is a known Kenshi character (e.g. Beep, Holy Lord Phoenix), use exact canon lore.
2. NON-CANON: Generate grounded, cynical, or weary profiles fitting the harsh Kenshi setting.
3. OUTPUT: Return a JSON object where each key is the NPC's Name, and the value is an object with: "Personality", "Backstory", "SpeechQuirks".
""")
    prompt = template.format(desc_str=desc_str)
    
    # Apply language instruction for batch generation
    settings = load_settings()
    language = settings.get("language", "English")
    if language and language.lower() != "english":
        prompt += f"\nLANGUAGE: All generated profile values ('Personality', 'Backstory', 'SpeechQuirks') MUST be written entirely in {language}. Do not use English for the values.\n"
    
    messages = [{"role": "user", "content": prompt}]
    # We allow more tokens for batch
    response_text = call_llm(messages, max_tokens=1500, temperature=0.7)
    
    if response_text:
        try:
            batch_results = robust_json_parse(response_text)
            if batch_results:
                for npc in npc_list:
                    raw_name = npc.get('name', 'Unknown')
                    clean_name = raw_name.split('|')[0] if '|' in raw_name else raw_name
                    gender = npc.get('gender', 'Neutral')
                    
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
                    
                    if profile:
                        # Determine storage_id: use the name for storage
                        storage_id = clean_name
                        
                        # Clean the ID if it's the Name|ID format
                        if '|' in str(storage_id):
                            storage_id = str(storage_id).split('|')[0]

                        data = {
                            "ID": storage_id,
                            "Name": clean_name,
                            "OriginalName": clean_name,
                            "Race": npc.get('race', 'Unknown'),
                            "Sex": npc.get('gender', 'Unknown'),
                            "Faction": npc.get('faction') or npc.get('Faction') or 'Unknown',
                            "OriginFaction": npc.get('origin_faction', 'Unknown'),
                            "Job": npc.get('job', 'None'),
                            "Personality": profile.get("Personality", "A weary traveler."),
                            "Backstory": profile.get("Backstory", "Trying to survive in the harsh desert."),
                            "SpeechQuirks": profile.get("SpeechQuirks", "None."),
                            "ConversationHistory": [],
                            "Relation": int(float(npc.get("relation", 0)) / 2)
                        }
                        save_character_data(storage_id, data)
                        logging.info(f"BATCH: Saved profile for {clean_name} (ID: {storage_id})")
        except Exception as e:
            logging.error(f"BATCH: Failed to parse batch profiles: {e}")

def get_character_data(name, context="", char_id=None, skip_generate=False):
    # CRITICAL: If the name contains a pipe (serial ID), split it to get the clean name.
    # This prevents "Name|ID" from creating unique "NameID" junk profiles.
    if '|' in name:
        name_parts = name.split('|')
        name = name_parts[0]
        if not char_id and len(name_parts) > 1:
            char_id = name_parts[1]

    # Fallback to local live context if explicit context is missing
    live_ctx = LIVE_CONTEXTS.get(name) or {}
    
    ctx_data = {}
    if context:
        if isinstance(context, dict):
            ctx_data = context
        elif isinstance(context, str) and context.strip().startswith('{'):
            try:
                ctx_data = json.loads(context)
            except:
                pass
    if not ctx_data and live_ctx:
        ctx_data = live_ctx
    
    # PERSISTENCE UPGRADE: Force Name-only storage.
    # This ignores any volatile or faction-appended IDs from the context.
    name = str(name).strip()
    storage_id = name
    
    # Clean the ID if it's the Name|ID format
    if storage_id and '|' in str(storage_id):
        storage_id = str(storage_id).split('|')[0].strip()


    # Sanitize for filesystem
    storage_id_str = str(storage_id)
    safe_filename = "".join([c for c in storage_id_str if c.isalnum() or c in (' ', '_', '-')]).strip()
    path = os.path.join(CHARACTERS_DIR, f"{safe_filename}.json")
    
    # MIGRATION: Logic removed to prevent faction-appended names.
    # We now strictly enforce Name-only filenames.
    
    data = None
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.loads(f.read())
        except:
            pass
            
    # Schema Migration for legacy files
    if data:
        if "ConversationHistory" not in data: data["ConversationHistory"] = []
        if "Relation" not in data: 
            data["Relation"] = int(float(ctx_data.get("relation", 0)) / 2) if ctx_data else 0
        if "Race" not in data: data["Race"] = "Unknown"
        if "Sex" not in data: data["Sex"] = "Unknown"
        if "Faction" not in data: data["Faction"] = "Unknown"
        if "OriginFaction" not in data: data["OriginFaction"] = "Unknown"
        if "Job" not in data: data["Job"] = "None"

    # If we have context, try to update race/faction if they are unknown or missing
    ctx_data = {}
    if isinstance(context, dict):
        ctx_data = context
    elif isinstance(context, str) and context.strip().startswith('{'):
        try:
            ctx_data = json.loads(context)
        except:
            pass

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
                    safe_fn = "".join([c for c in str(storage_id) if c.isalnum() or c in (' ', '_', '-')]).strip()
                    save_character_data(safe_fn, data)
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
                "Relation": int(float(ctx_data.get("relation", 0)) / 2),
                "_transient": True
            }

        # Generation Lock: Prevent parallel single gens for the same NPC
        with PROGRESS_LOCK:
            if storage_id in PROFILES_IN_PROGRESS:
                logging.debug(f"TRANS-PATH-2: {name} (Already in progress: {storage_id})")
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
                    "Relation": int(float(ctx_data.get("relation", 0)) / 2),
                    "_transient": True
                }
            PROFILES_IN_PROGRESS.add(storage_id)

        try:
            # Generate real profile only if we have full context.
            profile = generate_character_profile(name, context)
            if profile is None:
                logging.debug(f"TRANS-PATH-3: {name} (Generator returned None)")
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
                    "Relation": int(float(ctx_data.get("relation", 0)) / 2),
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
                "Relation": int(float(ctx_data.get("relation", 0)) / 2)
            }
        finally:
            with PROGRESS_LOCK:
                if storage_id in PROFILES_IN_PROGRESS:
                    PROFILES_IN_PROGRESS.remove(storage_id)
    
    # Enrich with world-index data (Persistence check)
    if name in WORLD_INDEX:
        data["SourcePlatoons"] = WORLD_INDEX[name]

    if should_save_profile(name, storage_id, data):
        save_character_data(storage_id, data)
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

def save_character_data(storage_id, data):
    safe_filename = "".join([c for c in str(storage_id) if c.isalnum() or c in (' ', '_', '-')]).strip()
    path = os.path.join(CHARACTERS_DIR, f"{safe_filename}.json")
    # Global safety truncation
    if data and "ConversationHistory" in data and len(data["ConversationHistory"]) > 250:
        data["ConversationHistory"] = data["ConversationHistory"][-250:]
        
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logging.error(f"Error saving character {storage_id}: {e}")

def extract_id_from_context(context_json):
    if not context_json: return None
    try:
        # If it's a string, parse it
        if isinstance(context_json, str) and context_json.strip().startswith('{'):
            context_json = json.loads(context_json)
        if isinstance(context_json, dict):
            # PRIORITIZE 'storage_id' (stable) over 'id' (volatile)
            return context_json.get('storage_id') or context_json.get('id')
    except:
        pass
    return None


@app.route('/log', methods=['POST'])
def log_dialogue():
    data = request.json
    if not data: return jsonify({"status": "error"}), 400
        
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
        
    # Limit history to 250 lines to prevent massive file sizes and UI lag
    if len(char_data["ConversationHistory"]) > 250:
        char_data["ConversationHistory"] = char_data["ConversationHistory"][-250:]
    
    if should_save_profile(npc_name, storage_id, char_data):
        save_character_data(storage_id, char_data)
    logging.info(f"LOG [{npc_name} ({storage_id})]: {npc_response}")
    return jsonify({"status": "ok"})

@app.route('/get_unique_identity', methods=['POST'])
def get_unique_identity():
    data = request.json
    if not data: return jsonify({"status": "error"}), 400
    
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
    batch = request.json # Expect list of {serial, name, gender, race}
    if not batch or not isinstance(batch, list):
        return jsonify({"status": "error", "message": "Invalid batch format"}), 400
    
    results = []
    rename_count = 0
    for item in batch:
        serial = item.get('serial')
        current_name = str(item.get('name', 'Someone')).strip()
        gender = item.get('gender', 'Neutral')
        
        is_generic_client = item.get('is_generic', False)
        is_generic = is_generic_client or is_npc_name_generic(current_name)
        
        if is_generic:
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
    if not data: return jsonify({"status": "error"}), 400
    
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
    # Transition to name-only identities for all renamed characters
    old_safe = "".join([c for c in old_name if c.isalnum() or c in (' ', '_', '-')]).strip()
    if str(old_id).startswith(old_safe) or "_" in str(old_id):
        new_id = new_name
        
        # Sanitize for migration
        new_safe = "".join([c for c in str(new_id) if c.isalnum() or c in (' ', '_', '-')]).strip()
        
        old_path = os.path.join(CHARACTERS_DIR, f"{old_id}.json")
        new_path = os.path.join(CHARACTERS_DIR, f"{new_safe}.json")
        
        if os.path.exists(old_path) and not os.path.exists(new_path):
            try:
                char_data["ID"] = new_id
                with open(new_path, "w", encoding="utf-8") as f:
                    json.dump(char_data, f, indent=2)
                os.remove(old_path)
                logging.info(f"RENAME: Migrated profile file {old_id} -> {new_safe}")
                return jsonify({"status": "ok", "new_id": new_id})
            except Exception as e:
                logging.error(f"RENAME: Failed to migrate profile file: {e}")
                return jsonify({"status": "error", "message": str(e)}), 500

    # Fallback: Just update internal data
    save_character_data(old_id, char_data)
    return jsonify({"status": "ok"})

@app.route('/ambient', methods=['POST'])
def ambient_event():
    debug_logger.debug("ROUTE: /ambient [POST]")
    data = request.json
    if not data: return jsonify({"status": "error"}), 400
    
    npcs_data = data.get('npcs', [])
    player_name = data.get('player', 'Drifter')
    
    logging.info(f"RADIANT: Received ambient banter request ({len(npcs_data)} NPCs nearby)")
    
    if not npcs_data:
        return jsonify({"status": "ignore"})

    # Build profiles for nearby characters
    char_profiles = ""
    name_to_id = {}
    
    # 1. Pre-check for missing profiles to batch generate
    missing_npcs = []
    npc_limit = npcs_data[:12] # Increase limit to 12 for better town square coverage
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
        generate_batch_profiles(missing_npcs)

    # 2. Extract and format profile summary for banter call
    recent_dialogue = []
    for npc in npc_limit:
        if isinstance(npc, dict):
            name = npc.get('name', 'Unknown')
            nid = npc.get('id', 0)
            name_to_id[name] = nid
            # Use stable name-based retrieval for ambient profiles
            d = get_character_data(name, context=json.dumps(npc))
            
            # Collect recent dialogue to prevent repetition
            if d.get("ConversationHistory"):
                recent_dialogue.extend(d["ConversationHistory"][-15:])

            # Include ID and sensory details for deterministic referencing
            health = npc.get('health', 'Healthy')
            gear = npc.get('equipment', 'nothing notable')
            char_profiles += f"\n- {name}|{nid} ({npc.get('gender')} {npc.get('race')}, {npc.get('faction')}) | Health: {health} | Gear: {gear} | Personality: {d.get('Personality', 'A traveler.')}"
        else:
            name_to_id[npc] = 0
            d = get_character_data(npc, "")
            
            if d.get("ConversationHistory"):
                recent_dialogue.extend(d["ConversationHistory"][-15:])
                
            char_profiles += f"\n- {npc} (A traveler): {d.get('Personality', 'A traveler.')}"

    # Deduplicate and sort history (preserving order)
    # 1. Pull from individual NPC memories
    all_history = list(recent_dialogue)
    
    # 2. Extract global banter/chat history from EVENT_HISTORY for the current location
    location = ""
    if PLAYER_CONTEXT:
        env = PLAYER_CONTEXT.get("environment", {})
        location = env.get("town_name", "") if isinstance(env, dict) else ""

    for evt in reversed(EVENT_HISTORY):
        # Format: "[BANTER] Name (Faction) -> Nearby @ Location: Message"
        if (" [BANTER] " in evt or " [CHAT] " in evt):
            # Only include if it's in the same location (or location is unknown)
            if not location or f"@ {location}" in evt or "@" not in evt:
                if ": " in evt:
                    msg_part = evt.split(": ", 1)[1]
                    # Extract speaker
                    match = re.search(r'\]\s*(.*?)\s*(?:\(.*?\))?\s*->', evt)
                    if match:
                        speaker = match.group(1).strip()
                        all_history.append(f"{speaker}: {msg_part}")
                    else:
                        all_history.append(msg_part)
        if len(all_history) > 100: break

    unique_history = []
    seen_history = set()
    # Work backwards to get the most recent unique lines
    for line in reversed(all_history):
        if line not in seen_history:
            unique_history.append(line)
            seen_history.add(line)
    
    unique_history = list(reversed(unique_history))[-40:] # Take last 40 unique lines
    
    history_block = ""
    if unique_history:
        history_block = "\nRECENT LOCAL DIALOGUE (DO NOT REPEAT TOPICS OR JOKES FROM HERE):\n" + "\n".join(unique_history)

    dynamic_system_prompt = build_system_prompt(player_name)
    
    
    ambient_system_prompt = f"""{dynamic_system_prompt}

[RADIANT DIALOGUE SYSTEM - BANTER MODE]
You are generating a short, atmospheric back-and-forth conversation (banter) between NPCs in Kenshi.
Kenshi is a post-apocalyptic, harsh world. NPCs should sound cynical, weary, or suspicious.

NEARBY CHARACTERS:
{char_profiles}

{history_block}

INSTRUCTIONS:
1. Select 2 or 3 characters from the list to have a short conversation.
2. Each participant MUST speak AT LEAST TWICE (total 4-6 lines).
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
    
    content = call_llm(messages)
    if content:
        # Strip any stray [ACTION] tags that the LLM might hallucinated despite instructions
        content = re.sub(r'\[\s*[A-Z_]+(?::\s*[^\]]+)?\s*\]', '', content).strip()
        
        # Basic cleaning - remove quotes
        content = content.replace('"', '').strip()
        
        # Post-process to ensure IDs are present
        lines = []
        for line in content.split('\n'):
            line = line.strip()
            if not line: continue
            
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
            elif '|' in line and len(line) < 100: # Maybe just a name header LLM hallucinated
                continue
            else:
                # Append raw text if no colon, though prompt asks for colon
                if len(line) > 5: lines.append(line)
        
        final_text = "\n".join(lines)
        
        # 5. Optimized History Update (One save per NPC)
        # Pre-load character memories for the nearby group (only those in npc_limit)
        memories = {}
        for npc_obj in npc_limit:
            name = npc_obj.get('name') if isinstance(npc_obj, dict) else npc_obj
            # Use skip_generate=True here just in case, though they should be generated by now
            memories[name] = get_character_data(name, context=json.dumps(npc_obj) if isinstance(npc_obj, dict) else "", skip_generate=True)

        # Append all new lines to the relevant memories
        for line in lines:
            if ':' in line:
                header, msg = line.split(':', 1)
                speaker_name = header.split('|')[0].strip()
                time_prefix = get_current_time_prefix()
                processed_msg = f"{time_prefix}{speaker_name}: {msg.strip()}"
                
                for name, d in memories.items():
                    d["ConversationHistory"].append(processed_msg)
                    # Trimming removed (was 50 line cap)
                
                # Also log to global history for narrative synthesis
                speaker_faction = memories.get(speaker_name, {}).get("Faction", "None")
                record_event_to_history("BANTER", speaker_name, "Nearby", msg.strip(), actor_faction=speaker_faction)

        # Batch save everything
        for name, d in memories.items():
            storage_id = d.get("ID", name)
            save_character_data(storage_id, d)

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

@app.route('/chat', methods=['POST'])
def chat():
    global CURRENT_MODEL_KEY
    data = request.json
    debug_logger.debug(f"ROUTE: /chat [POST] (Request details omitted for security)")
    if not data: return jsonify({"text": "Error: No JSON data provided"}), 400
    
    # Parse comma-separated NPC names and stabilize IDs
    raw_npc = data.get('npc', 'Someone')
    raw_npcs = data.get('npcs', [])
    
    # Stabilize name-to-id mapping for resolution accuracy
    name_to_id = {}
    
    def register(raw):
        if not raw: return ""
        clean = raw.split('|')[0] if '|' in raw else raw
        name_to_id[clean] = raw
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
            name = n.get('name')
            sid = n.get('storage_id') or n.get('id')
            if name:
                # Store full context including ID, Race, Faction for this NPC
                LIVE_CONTEXTS[name] = {
                    "id": f"{name}|{sid}" if sid else name,
                    "race": n.get('race', 'Unknown'),
                    "faction": n.get('faction', 'Unknown'),
                    "gender": n.get('gender', 'Unknown'),
                    "nearby": [x for x in nearby if x.get('name') != name],
                    "player_dist": n.get('dist', 999.0)
                }
                # Also store self in nearby list of primary if we are primary
                if name == primary_npc:
                    LIVE_CONTEXTS[primary_npc]["id"] = f"{name}|{sid}" if sid else name
    
    # Filter player out of available NPCs to avoid hallucinated PC responses
    npcs = [n for n in npcs if n != player_name]
    if primary_npc == player_name and len(npcs) > 0:
        primary_npc = npcs[0]
        
    player_message = data.get('message', '')
    
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
            
        if cmd == "attack": test_action = "[ATTACK]"
        elif cmd == "follow": test_action = "[ACTION: FOLLOW_PLAYER]"
        elif cmd == "idle": test_action = "[ACTION: IDLE]"
        elif cmd == "patrol": test_action = "[ACTION: PATROL_TOWN]"
        elif cmd == "join": test_action = "[ACTION: JOIN_PARTY]"
        elif cmd == "leave": test_action = "[ACTION: LEAVE]"
        elif cmd == "free": test_action = "[ACTION: FREE_PLAYER]"
        elif cmd == "breakout": test_action = "[ACTION: BREAKOUT_PLAYER]"
        elif cmd == "move": test_action = "[ACTION: MOVE_ON_FREE_WILL]"
        elif cmd == "movefast": test_action = "[ACTION: MOVE_ON_FREE_WILL_FAST]"
        elif cmd == "home": test_action = "[ACTION: GO_HOMEBUILDING]"
        elif cmd == "shop": test_action = "[ACTION: STAND_AT_SHOPKEEPER_NODE]"
        elif cmd == "raid": test_action = f"[ACTION: RAID_TOWN: {args}]"
        elif cmd == "travel": test_action = f"[ACTION: TRAVEL_TO_TARGET_TOWN: {args}]"
        elif cmd == "medic": test_action = "[ACTION: JOB_MEDIC]"
        elif cmd == "rescue": test_action = "[ACTION: FIND_AND_RESCUE]"
        elif cmd == "repair": test_action = "[ACTION: JOB_REPAIR_ROBOT]"
        elif cmd == "notify": test_action = f"[ACTION: NOTIFY: {args}]"
        elif cmd == "give_cats": test_action = f"[ACTION: GIVE_CATS: {args}]"
        elif cmd == "take_cats": test_action = f"[ACTION: TAKE_CATS: {args}]"
        elif cmd == "take_item": test_action = f"[ACTION: TAKE_ITEM: {args}]"
        elif cmd == "take":
            inv = PLAYER_CONTEXT.get("inventory", [])
            if inv:
                item_name = inv[0].get("name", "Unknown Item")
                test_action = f"[ACTION: TAKE_ITEM: {item_name}]"
            else:
                return jsonify({"text": "[DEBUG] Error: Player inventory is empty or unknown. Call /context to refresh.", "actions": []}), 200
        elif cmd == "drop": test_action = f"[ACTION: DROP_ITEM: {args}]"
        elif cmd == "spawn": test_action = f"[ACTION: SPAWN_ITEM: {args}]"
        elif cmd == "relations":
            rparts = args.rsplit(' ', 1)
            if len(rparts) == 2:
                test_action = f"[ACTION: FACTION_RELATIONS: {rparts[0].strip()}: {rparts[1].strip()}]"
        elif cmd == "task": test_action = f"[TASK: {args.upper()}]"
        
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
        return jsonify({"text": "...", "actions": []}), 200
    
    # Handle Ambient Flavor (NPC to NPC chat)
    is_ambient = event == "ambient_flavor"
    if is_ambient:
        player_message = "[AMBIENT CONVERSATION TRIGGERED]"
        
    context = data.get('context', '')
    primary_id = extract_id_from_context(context)

    # 3.1 Register Primary NPC with LIVE_CONTEXTS (critical for batch generation)
    if primary_npc and context:
        try:
            ctx_dict = json.loads(context) if isinstance(context, str) else context
            if ctx_dict:
                # Merge with existing context to preserve "nearby" list and other tracking
                if primary_npc not in LIVE_CONTEXTS:
                    LIVE_CONTEXTS[primary_npc] = {}
                
                target = LIVE_CONTEXTS[primary_npc]
                target["id"] = primary_id if primary_id else (ctx_dict.get('id') or target.get('id', primary_npc))
                if ctx_dict.get('storage_id'): target["storage_id"] = ctx_dict.get('storage_id')
                if ctx_dict.get('race'): target["race"] = ctx_dict.get('race')
                if ctx_dict.get('faction'): target["faction"] = ctx_dict.get('faction')
                if ctx_dict.get('origin_faction'): target["origin_faction"] = ctx_dict.get('origin_faction')
                
                # DLL context often includes its own nearby list — PRESERVE IT
                if "nearby" in ctx_dict:
                    target["nearby"] = ctx_dict["nearby"]
                
                if "dist" in ctx_dict:
                    target["player_dist"] = ctx_dict["dist"]
        except Exception as e:
            logging.error(f"Error registering primary context: {e}")
    
    # radii
    whisper_radius, talk_radius, yell_radius = get_config_radii()
    
    npcs_in_radius = []
    # USE THE ROOT NEARBY LIST FOR ACCURATE PROXIMITY DETECTION
    nearby_data = data.get('nearby', [])
    for n in nearby_data:
        name = n.get("name")
        if not name or name == player_name or name == primary_npc:
            continue
            
        dist = n.get("dist", 999.0)
        # Check if they are in radius based on communication mode
        if mode == "whisper":
            # Whisper is one-on-one, no one eavesdrops in this mode now
            continue 
        elif mode == "talk":
            if dist <= talk_radius: npcs_in_radius.append(name)
        elif mode == "yell":
            if dist <= yell_radius: npcs_in_radius.append(name)

    # 4. History Update (Overhearing)
    
    def get_local_context_and_id(target_name):
        # Clean target_name for comparison
        clean_target = target_name.split('|')[0] if '|' in target_name else target_name
        
        if clean_target == primary_npc:
            return context, primary_id
            
        # Check current request's nearby data first (highest accuracy)
        nearby_data = data.get('nearby', [])
        for n in nearby_data:
            n_name = n.get("name", "")
            clean_n = n_name.split('|')[0] if '|' in n_name else n_name
            if clean_n == clean_target:
                return json.dumps(n), (n.get("storage_id") or n.get("id"))
                
        # Fallback to LIVE_CONTEXTS cache
        if clean_target in LIVE_CONTEXTS:
            c = LIVE_CONTEXTS[clean_target]
            return json.dumps(c), (c.get("storage_id") or c.get("id"))
            
        return "", None

    # Determine listeners (everyone in radius)
    # Ensure listeners are clean names for logic processing
    raw_listeners = list(set([primary_npc] + npcs_in_radius))
    listeners = []
    for l in raw_listeners:
        clean_l = l.split('|')[0] if '|' in l else l
        if clean_l not in listeners: listeners.append(clean_l)

    # 5. Determine who the LLM actually responds as
    if mode == 'yell':
        npcs = listeners
    else:
        npcs = [primary_npc]

    if not primary_id and live_ctx:
        primary_id = live_ctx.get("id")

    # BATCH GENERATION: Pre-emptively generate profiles for anyone (participants or overhearers) missing one
    missing_for_batch = []
    checked_ids = set()
    for name in listeners:
        cid = primary_id if name == primary_npc else None
        npc_ctx, local_cid = get_local_context_and_id(name)
        sid = cid if cid else local_cid
        
        # Determine the storage ID to check disk (STRICT NAME-ONLY)
        storage_id = name
        if '|' in str(storage_id): storage_id = str(storage_id).split('|')[0]
        
        if storage_id in checked_ids: continue
        checked_ids.add(storage_id)
        
        safe_fn = "".join([c for c in str(storage_id) if c.isalnum() or c in (' ', '_', '-')]).strip()
        path = os.path.join(CHARACTERS_DIR, f"{safe_fn}.json")
        
        if not os.path.exists(path):
            # Atomic check to avoid redundant generation for the same NPC
            with PROGRESS_LOCK:
                if storage_id in PROFILES_IN_PROGRESS:
                    continue
                PROFILES_IN_PROGRESS.add(storage_id)

            # Get data for batch
            ctx_dict = {}
            if npc_ctx:
                try: ctx_dict = json.loads(npc_ctx) if isinstance(npc_ctx, str) else npc_ctx
                except: pass
            
            if not ctx_dict:
                live = LIVE_CONTEXTS.get(name, {})
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
        try:
            generate_batch_profiles(missing_for_batch)
        finally:
            with PROGRESS_LOCK:
                for ctx in missing_for_batch:
                    sid = ctx.get("storage_id")
                    if sid in PROFILES_IN_PROGRESS:
                        PROFILES_IN_PROGRESS.remove(sid)

    char_datas = {}
    threads = []
    def fetch_npc_thread(name, cid, delay):
        if delay > 0:
            time.sleep(delay)
        try:
            npc_context, local_cid = get_local_context_and_id(name)
            thread_cid = cid if cid else local_cid
            char_datas[name] = get_character_data(name, npc_context, char_id=thread_cid)
        except Exception as e:
            logging.error(f"Thread Error fetching {name}: {e}")

    delay_counter = 0
    for name in listeners:
        cid = primary_id if name == primary_npc else None
        
        # Check if background already exists to avoid unnecessary delays (STRICT NAME-ONLY)
        storage_id = name
        if '|' in str(storage_id): storage_id = str(storage_id).split('|')[0]
            
        safe_filename = "".join([c for c in str(storage_id) if c.isalnum() or c in (' ', '_', '-')]).strip()
        path = os.path.join(CHARACTERS_DIR, f"{safe_filename}.json")
        
        delay = 0
        if not os.path.exists(path):
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
            char_datas[name] = {"Name": name, "Personality": "A generic NPC.", "Backstory": "Unknown", "ConversationHistory": []}
    
    # TALK mode now allows fall-through to prompt only the primary NPC
    # while others overheard via history updates above.

    logging.info(f"Prompting LLM for {mode} communication with {primary_npc} (Total participants: {len(npcs)})...")
    # Context building similar to Fallout 2 mod...
    primary_data = char_datas[primary_npc]
    
    # Simple history append for now
    history_str = "\n".join(primary_data["ConversationHistory"][-20:])

    npc_profiles = ""
    for name in npcs:
        d = char_datas[name]
        npc_profiles += f"\nCHARACTER: {name}\n"
        npc_profiles += f"RACE: {d.get('Race')}\n"
        npc_profiles += f"ORIGIN FACTION: {get_faction_info(d.get('OriginFaction', 'Unknown'))}\n"
        npc_profiles += f"CURRENT FACTION: {get_faction_info(d.get('Faction'))}\n"
        npc_profiles += f"JOB: {d.get('Job', 'None')}\n"
        npc_profiles += f"PERSONALITY: {d.get('Personality')}\n"
        npc_profiles += f"BACKSTORY: {d.get('Backstory')}\n"
        npc_profiles += f"PERSONAL RELATION TO PLAYER: {d.get('Relation', 0)} (Scale: -100 to 100)\n"
        
        # Add live context (stats, health, etc.)
        live_context = build_detailed_context_string(name, char_data=d)
        if live_context:
            npc_profiles += f"{live_context}\n"

    primary_race = primary_data.get('Race', 'Unknown')
    is_animal = any(kw.lower() in primary_race.lower() for kw in ANIMAL_RACES)

    if is_animal:
        dynamic_system_prompt = f"CRITICAL: {primary_npc} is an ANIMAL ({primary_race}). Animals in Kenshi CANNOT speak human languages. They do not use words, symbols, or telegram-style speech. They ONLY react with brief physical actions, sounds, or gestures described within asterisks."
        final_instruction = f"Respond as {primary_npc} (the animal). Provide a single, BRIEF action description or sound in asterisks (e.g. *Growls*, *Tilts head*, *Nuzzles hand*). DO NOT USE WORDS OR SPEECH. Keep it under 6 words."
    else:
        dynamic_system_prompt = build_system_prompt(player_name)
        
        if mode == 'yell':
            volume_status = "The player is addressing everyone nearby at a clear, projected volume."
            yell_instruction = f"\nCRITICAL: {volume_status} This can be heard by everyone nearby ({', '.join(npcs)}). This is a public address or talking to a crowd; it is NOT yelling or shouting aggressively. DO NOT tell the player to quiet down or react with annoyance to the volume. You SHOULD respond as multiple characters from the list to create a realistic crowd reaction. Every speaker MUST be on a new line started with 'Name: ' (e.g., 'Beep: Hey!').\nACTION TAGS IN CROWD MODE: If a character decides to take an action (attack, flee, join, etc.), place the [ACTION: TAG] at the END of THAT CHARACTER'S OWN LINE, not at the end of the whole response. Example: 'Hobbs: I'm with you! [ACTION: JOIN_PARTY]'"
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
            dynamic_system_prompt += talk_instruction
            
        # Relation Judgment (All direct non-ambient interactions)
        if not is_ambient:
            dynamic_system_prompt += "\nJUDGMENT: At the end of your response, you MUST judge the player's tone and the quality of this interaction on a scale of -5 (extremely aggressive/hostile/insulting) to 5 (extremely friendly/helpful/respectful). 0 is neutral. Format this judgment as a tag like [JUDGMENT: n] at the very end."
        
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

    rich_prompt = template.format(
        system_prompt=dynamic_system_prompt,
        primary_npc=primary_npc,
        npc_profiles=npc_profiles,
        history_str=history_str,
        final_instruction=final_instruction,
        language_str=user_lang
    )
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
            f.write(f"\n{'='*50}\n")
            f.write(f"TIMESTAMP: {time.ctime()}\n")
            f.write(f"REQUEST FOR: {primary_npc} (Mode: {mode})\n")
            f.write(f"PROMPT:\n{rich_prompt}\n")
            f.write(f"USER MESSAGE: {player_message}\n")
            f.write(f"{'-'*30}\n")
    except: pass

    logging.info(f"Calling main chat LLM...")
    content = call_llm(messages)
    
    # Debug Logging: Log the response
    if content:
        try:
            with open(DEBUG_LOG, "a", encoding="utf-8") as f:
                f.write(f"RAW LLM RESPONSE:\n{content}\n")
                f.write(f"{'='*50}\n")
        except: pass
    else:
        logging.error("LLM returned None for chat response.")
        try:
            with open(DEBUG_LOG, "a", encoding="utf-8") as f:
                f.write(f"LLM RESPONSE FAILED (None)\n")
                f.write(f"{'='*50}\n")
        except: pass
    
    if content:
        # 0. Per-speaker action parsing (for YELL/Group mode)
        # We must do this BEFORE global cleaning removes the tags.
        per_speaker_actions = []
        speaker_judgments = {} # speaker -> val
        if mode == 'yell':
            raw_lines = content.split('\n')
            for rline in raw_lines:
                rline = rline.strip()
                if not rline: continue
                # Look for "Name: ... [TAG]"
                match = re.match(r'^([^:]+):\s*(.*)$', rline)
                if match:
                    speaker = match.group(1).strip()
                    payload = match.group(2).strip()
                    # Extract ALL tags from this specific sub-line
                    speaker_tags = re.findall(r'\[\s*[^\]]+\s*\]', payload)
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
                                except: pass

        # Use a very generous regex to find anything that looks like a tag
        # Updated to handle one level of nested brackets (common in item names: Bolts [Toothpicks])
        all_bracketed = re.findall(r'\[\s*(?:[^\[\]]|\[[^\[\]]*\])+\s*\]', content)
        
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
                if clean == prev: break
            
            # 2. Extract Keyword and Args
            if ":" in clean:
                parts = clean.split(":", 1)
                kw = parts[0].strip().upper()
                args = parts[1].strip()
                
                # Recursive keyword fix: Handle [ACTION: TAKE_CATS: TAKE_CATS: 40]
                if args.upper().startswith(kw):
                     args = re.sub(rf'^{re.escape(kw)}\s*:?\s*', '', args, flags=re.IGNORECASE).strip()
            else:
                kw = clean.upper()
                args = ""

            # 3. Handle Judgment (Extract value for server logic)
            if kw == "JUDGMENT" or "JUDGMENT" in kw:
                j_val = args or re.search(r'-?\d+', kw)
                if j_val:
                    try:
                        j_str = j_val.group(0) if hasattr(j_val, 'group') else str(j_val)
                        global_judgment = max(-5, min(5, int(j_str)))
                        logging.info(f"RELATION: Interaction judged as {global_judgment}")
                    except: pass
                # Do NOT continue; let it be added to actions so it's 'passed' to C++ logs

            # 4. Handle Actions/Tasks
            # Fuzzy match the keyword against our known list
            matched_ka = None
            for formal in formal_map:
                if formal == kw or (formal in kw and len(kw) < len(formal) + 3):
                    matched_ka = formal_map[formal]
                    break
            
            if matched_ka:
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
                     if final_tag in last_hist: continue
                
                actions.append(final_tag)

        # 5. Apply judgment to NPC's personal relation score and faction relations
        if not is_ambient:
            # Aggregate all participants who judged
            judges = speaker_judgments if speaker_judgments else {primary_npc: global_judgment}
            
            for judge_name, j_val in judges.items():
                if j_val == 0: continue
                
                # Get data for this speaker (must have been loaded in char_datas)
                j_data = char_datas.get(judge_name)
                if not j_data: 
                    # If it's a yell participant we didn't fully load, skip
                    continue

                current_rel = j_data.get("Relation", 0)
                try: current_rel = int(current_rel)
                except: current_rel = 0
                
                new_rel = max(-100, min(100, current_rel + j_val))
                if new_rel != current_rel:
                    j_data["Relation"] = new_rel
                    logging.info(f"RELATION: {judge_name} personal relation updated {current_rel} -> {new_rel} (judgment={j_val})")

                # Faction relation impact (Only for significant judgments)
                f_delta = 0
                if j_val >= 5: f_delta = 2
                elif j_val >= 4: f_delta = 1
                elif j_val <= -5: f_delta = -2
                elif j_val <= -4: f_delta = -1
                
                if f_delta != 0:
                    npc_f = j_data.get("Faction", "None")
                    if npc_f and npc_f not in ["None", "Nameless", "No Faction"]:
                        f_tag = f"[ACTION: FACTION_RELATIONS: {npc_f}: {f_delta}]"
                        actions.append(f_tag)
                        logging.info(f"RELATION: Scheduled faction relation change via {judge_name} for {npc_f}: {f_delta}")

        # 6. Clean Dialogue Text - remove ALL bracketed tags from the dialogue
        content = re.sub(r'\[\s*(?:[^\[\]]|\[[^\[\]]*\])+\s*\]', '', content).strip()

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
            if not line: continue
            
            # Re-apply tag removal to individual lines just in case
            line = re.sub(r'\[\s*[^\]]+\s*\]', '', line).strip()
            if not line: continue

            # If in YELL mode, look for "Name: Response" format to split bubbles
            is_group_response = (mode == 'yell')
            if is_group_response:
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
        if len(content) > 500:
            content = content[:497] + "..."
        
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
                char_datas[name] = get_character_data(name, ctx, char_id=sid)
                
            char_datas[name]["ConversationHistory"].append(f"{time_prefix}{overheard_tag}{player_name}{mode_action}: {player_message}")
            
            # If multiple lines/speakers, append them all to history
            if "\n" in content:
                for line in content.split('\n'):
                    if not line.strip(): continue
                    
                    # Ensure the line has a speaker attribution in the history
                    history_line = line.strip()
                    if ':' not in history_line:
                         # Append primary name if LLM forgot the prefix in single-responder modes
                         history_line = f"{primary_npc}: {history_line}"
                    
                    # If this is the LAST line and there are actions, append them for history context
                    if line == filtered_lines[-1] and actions:
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
                if ':' not in history_line:
                     history_line = f"{primary_npc}: {history_line}"
                
                history_entry = f"{time_prefix}{overheard_tag}{history_line}"
                if actions:
                    history_entry += f" {' '.join(actions)}"
                char_datas[name]["ConversationHistory"].append(history_entry)
                
                primary_faction = char_datas.get(primary_npc, {}).get("Faction", "None")
                player_faction = PLAYER_CONTEXT.get("faction", "None")
                record_event_to_history("CHAT", primary_npc, player_name, content, actor_faction=primary_faction, target_faction=player_faction)

            # Limit history to 250 lines
            if len(char_datas[name]["ConversationHistory"]) > 250:
                char_datas[name]["ConversationHistory"] = char_datas[name]["ConversationHistory"][-250:]
                
            storage_id = char_datas[name].get("ID", name)
            # Relaxed transient check: if they have history, allow save even if technically transient
            has_history = len(char_datas[name].get("ConversationHistory", [])) > 0
            if char_datas[name].get("_transient") and not has_history:
                logging.warning(f"SKIP SAVE: {name} is using a transient fallback profile with no history. Blocking disk override.")
            elif should_save_profile(name, storage_id, char_datas[name]):
                save_character_data(storage_id, char_datas[name])

        logging.info(f"AI RESPONSE: {content} | ACTIONS: {actions}")
        return jsonify({"text": content, "actions": actions})
    return jsonify({"text": "...", "actions": []})


def record_event_to_history(etype, actor, target, msg, actor_faction="None", target_faction="None"):
    """Centralized helper to record events for both the log and narrative synthesis."""
    global EVENT_HISTORY, GLOBAL_EVENT_COUNTER, EVENT_THROTTLE, LAST_STATE_LOG
    if not msg: return
    
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
        if len(LAST_STATE_LOG) > 2000: LAST_STATE_LOG.clear()

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
        if not os.path.exists(log_dir): os.makedirs(log_dir)
        with open(os.path.join(log_dir, "global_events.log"), "a", encoding="utf-8") as f:
            f.write(f"{evt_str}\n")
            
        # Also copy to server.log so it shows up in both tabs if relevant
        logging.info(f"EVENT: {evt_str}")
    except:
        pass

    # Simple deduplication based on exact string for memory/synthesis
    # CRITICAL: Filter out "looting" events from the narrative history to prevent spam.
    if etype == "looting":
        return

    if evt_str not in EVENT_HISTORY:
        EVENT_HISTORY.append(evt_str)
        GLOBAL_EVENT_COUNTER += 1
        save_campaign_history()
            
    # Narrative check (OLD: based on counter)
    # Removed in favor of timed synthesis as per user request.
    # if GLOBAL_EVENT_COUNTER >= 100:
    #     logging.info(f"NARRATIVE: Threshold reached ({GLOBAL_EVENT_COUNTER}). Triggering synthesis.")
    #     threading.Thread(target=generate_global_narrative_thread, daemon=True).start()
    #     GLOBAL_EVENT_COUNTER = 0

    if len(EVENT_HISTORY) > 500:
        EVENT_HISTORY = EVENT_HISTORY[-500:]

def generate_global_narrative_thread():
    """Synthesizes the last 100 events into a global rumor for NPCs to overhear."""
    global EVENT_HISTORY
    # Lower threshold for manual trigger so small sessions can still synthesize
    min_needed = 5
    if len(EVENT_HISTORY) < min_needed:
        logging.warning(f"NARRATIVE: Not enough events to synthesize (have {len(EVENT_HISTORY)}, need {min_needed}).")
        return None
    
    settings = load_settings()
    ge_count = settings.get("global_events_count", 10)
    
    # Use ge_count * 5 as the synthesis sample to ensure variety and context,
    # but the prompt instructions will emphasize the 'global_events_count' recent actions.
    sample_size = min(len(EVENT_HISTORY), max(ge_count, 100))
    last_chunk = EVENT_HISTORY[-sample_size:]
    
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
            except: pass
        
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
                for line in f.readlines()[-20:]: # Scan last 20 lines
                    match = re.search(r'\[RUMOR:\s*(.*?)\]', line)
                    if match:
                        rumor_lines.append(f"- {match.group(1).strip()}")
                
                if rumor_lines:
                    past_rumors_block = "\nPREVIOUS RUMORS (Do NOT repeat these):\n" + "\n".join(rumor_lines[-5:])
        except: pass

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
    rumor_text = call_llm(messages)
    
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
                if os.path.exists(world_events_path):
                    with open(world_events_path, "a", encoding="utf-8") as f:
                        f.write(f"\n{rumor_tagged}\n")
                    logging.info(f"NARRATIVE: Generated and saved new global event: {rumor_tagged}")
                    # Notify player of the new rumor in-game
                    send_to_pipe(f"NOTIFY: [WORLD EVENT] {rumor_text}")
                    return rumor_tagged
                else:
                    logging.warning(f"Could not find world_events.txt at {world_events_path}")
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
                import textwrap
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
    if not data: return jsonify({"status": "error"}), 400
    
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
            LIVE_CONTEXTS[name] = data
            LAST_NPC_NAME = name
            # Force update LAST_STATE_LOG for immediate debugger visibility
            with STATE_LOCK:
                LAST_STATE_LOG["npc"] = data
    return jsonify({"status": "ok"})


@app.route('/context', methods=['GET'])
def get_context():
    """Returns the most recent player and NPC context for the debugger/UI."""
    # Try to grab the last active NPC from live contexts
    last_npc = None
    if LIVE_CONTEXTS:
        # Get the most recently updated context
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
            if p not in mbp: mbp[p] = []
            mbp[p].append(k)
        
        # Determine current provider
        curr_prov = MODELS_CONFIG.get(CURRENT_MODEL_KEY, {}).get("provider", "unknown")

        return jsonify({
            "status": "ok",
            "models": mbp,        # C++ dropdowns loop uses this
            "all_models": MODELS_CONFIG, # C++ initialization lookup
            "providers": list(PROVIDERS_CONFIG.keys()),
            "current": CURRENT_MODEL_KEY,
            "current_provider": curr_prov,
            "campaigns": campaigns,
            "current_campaign": ACTIVE_CAMPAIGN,
            "enable_ambient": settings.get("enable_ambient", True),
            "ambient_timer": settings.get("radiant_delay", 240),
            "synthesis_timer": settings.get("synthesis_interval_minutes", 15),
            "global_events_count": settings.get("global_events_count", 5),
            "dialogue_speed": settings.get("dialogue_speed_seconds", 5),
            "bubble_life": settings.get("bubble_life", 5),
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

    ambient_timer = data.get("ambient_timer")
    if ambient_timer is not None:
        val = int(ambient_timer)
        changes["radiant_delay"] = val
        send_to_pipe(f"SET_CONFIG: g_ambientIntervalSeconds: {val}")
        logging.info(f"Radiant delay set to: {val}")

    radii = data.get("radii")
    if radii:
        r = radii.get("radiant")
        t = radii.get("talk")
        y = radii.get("yell")
        if r is not None:
            send_to_pipe(f"SET_CONFIG: g_radiantRange: {r}")
        if t is not None:
            send_to_pipe(f"SET_CONFIG: g_proximityRadius: {t}")
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
        except: pass

    syn_timer = data.get("synthesis_timer")
    if syn_timer is not None:
        try:
            val = int(syn_timer)
            changes["synthesis_interval_minutes"] = val
            logging.info(f"Synthesis timer set to: {val} minutes")
        except: pass

    diag_speed = data.get("dialogue_speed")
    if diag_speed is not None:
        try:
            val = int(diag_speed)
            changes["dialogue_speed_seconds"] = val
            send_to_pipe(f"SET_CONFIG: g_dialogueSpeedSeconds: {val}")
            logging.info(f"Dialogue speed set to: {val} seconds")
        except: pass

    bubble_life = data.get("bubble_life")
    if bubble_life is not None:
        try:
            val = float(bubble_life)
            changes["bubble_life"] = val
            send_to_pipe(f"SET_CONFIG: g_speechBubbleLife: {val}")
            logging.info(f"Bubble life set to: {val} seconds")
        except: pass

    if changes:
        save_settings(changes)

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
    if not os.path.exists(d_dir): os.makedirs(d_dir)
        
    camps = [d for d in os.listdir(CAMPAIGNS_DIR) if os.path.isdir(os.path.join(CAMPAIGNS_DIR, d))]
    return jsonify({"status": "ok", "campaigns": camps, "current": ACTIVE_CAMPAIGN})

@app.route('/campaigns/create', methods=['POST'])
def create_campaign_route():
    logging.info("ROUTE: /campaigns/create [POST]")
    data = request.json
    name = data.get("name")
    if not name: return jsonify({"status": "error", "message": "Missing name"}), 400
    
    # Sanitize
    safe_name = "".join([c for c in name if c.isalnum() or c in (' ', '_', '-')]).strip()
    if not safe_name: return jsonify({"status": "error", "message": "Invalid name"}), 400
    
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
    if not name: return jsonify({"status": "error", "message": "Missing name"}), 400
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

    # 1. Cull NPC JSONs
    char_dir = os.path.join(cdir, "characters")
    if os.path.exists(char_dir):
        for f in os.listdir(char_dir):
            if f.endswith(".json"):
                fpath = os.path.join(char_dir, f)
                try:
                    with open(fpath, "r", encoding="utf-8") as fh:
                        cdata = json.load(fh)
                    
                    history = cdata.get("ConversationHistory", [])
                    new_history = [l for l in history if not is_future_timestamp(l, current_day, current_hour, current_min)]
                    
                    if len(new_history) != len(history):
                        cdata["ConversationHistory"] = new_history
                        with open(fpath, "w", encoding="utf-8") as fw:
                            json.dump(cdata, fw, indent=2)
                        logging.info(f"CULL: Culled {len(history) - len(new_history)} lines from {f}")
                except: pass

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
                global EVENT_HISTORY
                EVENT_HISTORY = new_ev_data
                logging.info(f"CULL: Culled {len(ev_data) - len(new_ev_data)} events from event_history.json")
        except: pass

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
        except: pass

    return jsonify({"status": "ok"})

def switch_campaign(name):
    global ACTIVE_CAMPAIGN, LIVE_CONTEXTS, EVENT_HISTORY
    cdir = os.path.join(CAMPAIGNS_DIR, name)
    if os.path.exists(cdir):
        ACTIVE_CAMPAIGN = name
        save_settings({"current_campaign": name})  # Persist across restarts
        # Clear volatile state
        LIVE_CONTEXTS.clear()
        EVENT_HISTORY = []
        load_campaign_config()
        update_world_index() # Re-scan save for new campaign context
        return True
    return False

@app.route('/regenerate_profile', methods=['POST'])
def regenerate_profile_route():
    logging.info("ROUTE: /regenerate_profile [POST]")
    data = request.json
    sid = data.get("sid")
    if not sid: return jsonify({"status": "error", "message": "Missing NPC ID (sid)"}), 400
    
    # 1. Resolve safe filename and load data
    safe_fn = "".join([c for c in str(sid) if c.isalnum() or c in (' ', '_', '-')]).strip()
    path = os.path.join(CHARACTERS_DIR, f"{safe_fn}.json")
    
    if not os.path.exists(path):
        logging.error(f"REGEN: Profile not found at {path}")
        return jsonify({"status": "error", "message": "Profile not found"}), 404
        
    try:
        with open(path, "r", encoding="utf-8") as f:
            char_data = json.load(f)
            
        history = char_data.get("ConversationHistory", [])
        if not history:
             logging.warning(f"REGEN: No history for {sid}, fallback to standard gen?")
             return jsonify({"status": "error", "message": "No conversation history to build from. Talk to the NPC first!"}), 400
             
        # 2. Build synthesis prompt
        name = char_data.get("Name", sid)
        race = char_data.get("Race", "Unknown")
        personality = char_data.get("Personality", "Unknown")
        backstory = char_data.get("Backstory", "Unknown")
        faction = char_data.get("Faction", "Unknown")
        
        # Use full history for best quality
        history_block = "\n".join(history)
        
        logging.info(f"REGEN: Evolving profile for {name} based on {len(history)} lines of memory...")
        
        system_msg = "You are an expert on Kenshi lore and character growth. You write NPC profiles in a grounded, cynical tone. You ALWAYS respond ONLY with a valid JSON object."
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

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ]
        response_text = call_llm(messages, max_tokens=1500, temperature=0.7)
        
        # Detect the empty-response placeholder returned by call_llm
        if not response_text or "Empty Response" in response_text:
            logging.error(f"REGEN: LLM returned empty/null response for {name}. This may be a token limit or content filter issue.")
            return jsonify({"status": "error", "message": f"LLM returned an empty response. The model may have run out of tokens. Try again or use an NPC with fewer memories."}), 500

        result = robust_json_parse(response_text)
        if result:
            # Update and preserve metadata
            char_data["Personality"] = result.get("Personality", personality)
            char_data["Backstory"] = result.get("Backstory", backstory)
            char_data["SpeechQuirks"] = result.get("SpeechQuirks", char_data.get("SpeechQuirks", ""))
            
            # Save
            with open(path, "w", encoding="utf-8") as f:
                json.dump(char_data, f, indent=2)
            
            logging.info(f"REGEN: Successfully evolved profile for {name}.")
            return jsonify({"status": "ok", "message": f"Successfully evolved {name}'s profile."})
        else:
            logging.error(f"REGEN: JSON parse failed for {name}. Raw response: {response_text[:300]}")
            return jsonify({"status": "error", "message": "LLM response was not valid JSON. Try again."}), 500
                
    except Exception as e:
        logging.error(f"REGEN: Failed for {sid}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
        
    return jsonify({"status": "error", "message": "Synthesis failed"}), 500


@app.route('/models', methods=['GET'])
def get_models():
    """Alias for GET /settings — used by the visual debugger."""
    load_configs()
    settings = load_settings()
    return jsonify({
        "status": "ok",
        "models": MODELS_CONFIG,
        "providers": list(PROVIDERS_CONFIG.keys()),
        "current": CURRENT_MODEL_KEY,
        "enable_ambient": settings.get("enable_ambient", True),
    })


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
    
    # DIRECT FILE LOAD
    char_data = None
    safe_fn = "".join([c for c in str(clean_npc_name) if c.isalnum() or c in (' ', '_', '-')]).strip()
    direct_path = os.path.join(CHARACTERS_DIR, f"{safe_fn}.json")
    logging.info(f"HISTORY: Trying direct load for {clean_npc_name} from: {direct_path}")
    
    if os.path.exists(direct_path):
        try:
            with open(direct_path, "r", encoding="utf-8") as f:
                char_data = json.load(f)
            logging.info(f"HISTORY: Direct load SUCCESS for {clean_npc_name}")
        except Exception as e:
            logging.error(f"HISTORY: Direct load failed for {clean_npc_name}: {e}")
            char_data = None
    
    # Fallback to standard resolution if direct load didn't work
    if not char_data:
        logging.info(f"HISTORY: Falling back to get_character_data for {clean_npc_name}")
        char_data = get_character_data(clean_npc_name, context)
    
    # Schema migration for legacy files
    if "ConversationHistory" not in char_data: char_data["ConversationHistory"] = []
    if "Race" not in char_data: char_data["Race"] = "Unknown"
    if "Faction" not in char_data: char_data["Faction"] = "Unknown"
    
    # Return full history as requested
    history = char_data.get('ConversationHistory', [])
    
    import textwrap
    def _wrap(text):
        if not text: return ""
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
    sort_mode = data.get("sort", "alphabetical") # alphabetical or latest
    
    settings = load_settings()
    favorites = settings.get("favorites", [])

    logging.info(f"Scanning for characters in: {CHARACTERS_DIR} (Sort: {sort_mode})")
    if not os.path.exists(CHARACTERS_DIR):
        return jsonify({"status": "ok", "characters": ""})
    
    npc_list = []
    for f in os.listdir(CHARACTERS_DIR):
        if not f.endswith('.json'):
            continue
        storage_id = f.replace('.json', '')
        try:
            fpath = os.path.join(CHARACTERS_DIR, f)
            mtime = os.path.getmtime(fpath)
            with open(fpath, "r", encoding="utf-8") as fh:
                cdata = json.load(fh)
            display = cdata.get('Name', storage_id)
            
            npc_list.append({
                "display": display,
                "sid": storage_id,
                "mtime": mtime,
                "is_fav": storage_id in favorites
            })
        except:
            npc_list.append({
                "display": storage_id,
                "sid": storage_id,
                "mtime": 0,
                "is_fav": storage_id in favorites
            })

    # Deduplicate by display name (keeping original logic preference for underscores)
    unique_npcs = {}
    for n in npc_list:
        name = n["display"]
        if name not in unique_npcs:
            unique_npcs[name] = n
        else:
            # If current has underscore, prefer it
            if '_' in n["sid"]:
                unique_npcs[name] = n

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
        LIVE_CONTEXTS.clear()
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
            interval = settings.get("synthesis_interval_minutes", 60)
            if interval < 1: interval = 1 # Safety
            
            SYNTHESIS_STATUS["interval"] = interval
            
            # If interval was shortened below current elapsed, trigger now
            if elapsed_minutes >= interval:
                logging.info(f"NARRATIVE: Interval shortened ({interval}m). Triggering synthesis.")
                generate_global_narrative_thread()
                elapsed_minutes = 0
                SYNTHESIS_STATUS["elapsed"] = 0
                continue

            # Sleep in smaller chunks to be responsive to game state changes
            for _ in range(6): # Check pulse 6 times per minute (every 10s)
                time.sleep(10)
                speed = PLAYER_CONTEXT.get("gamespeed", 1.0)
                is_paused = PLAYER_CONTEXT.get("is_paused", False)
            
            # After ~60s of total time, check if we progressed
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
                    base_url = provider_config.get("base_url").rstrip("/")
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
from flask import render_template, send_from_directory

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
        LIVE_CONTEXTS.clear()
        LAST_STATE_LOG.clear()
        EVENT_THROTTLE.clear()
        return jsonify({"status": "ok", "message": "Server state reset"})
    
    # Standard pipe relay
    send_to_pipe(cmd)
    logging.info(f"WEB_CMD: Relayed command: {cmd}")
    return jsonify({"status": "ok"})

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
