import configparser
import logging
import os

SCRIPT_PATH = os.path.abspath(__file__)
SCRIPT_DIR = os.path.dirname(SCRIPT_PATH)
KENSHI_SERVER_DIR = os.path.dirname(SCRIPT_DIR)
KENSHI_MOD_DIR = os.path.dirname(KENSHI_SERVER_DIR)
KENSHI_ROOT = os.path.dirname(os.path.dirname(KENSHI_MOD_DIR))

TEMPLATES_DIR = os.path.join(KENSHI_SERVER_DIR, "templates")
CAMPAIGNS_DIR = os.path.join(KENSHI_SERVER_DIR, "campaigns")
CHARACTERS_DIR = os.path.join(KENSHI_SERVER_DIR, "characters")


def resolve_mod_file(filename):
    """
    Helper to find a file in the mod directory.
    Normally files are in KENSHI_MOD_DIR (the root of the mod).
    During development they might be in a 'SentientSands_Mod' subdirectory.
    """
    path = os.path.join(KENSHI_MOD_DIR, filename)
    if os.path.exists(path):
        return path

    dev_path = os.path.join(KENSHI_MOD_DIR, "SentientSands_Mod", filename)
    if os.path.exists(dev_path):
        return dev_path

    alt_path = os.path.join(
        os.path.dirname(KENSHI_MOD_DIR), "SentientSands_Mod", filename
    )
    if os.path.exists(alt_path):
        return alt_path

    return path


INI_PATH = resolve_mod_file("SentientSands_Config.ini")
MODELS_PATH = os.path.join(KENSHI_SERVER_DIR, "config", "models.json")
PROVIDERS_PATH = os.path.join(KENSHI_SERVER_DIR, "config", "providers.json")
NAMES_PATH = os.path.join(KENSHI_SERVER_DIR, "config", "names.json")
GENERIC_NAMES_PATH = os.path.join(KENSHI_SERVER_DIR, "config", "generic_names.json")
LOCALIZATION_PATH = os.path.join(KENSHI_SERVER_DIR, "config", "localization.json")

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
    "language": "Language",
    "chat_hotkey": "ChatHotkey",
    "enable_renamer": "EnableRenamer",
    "enable_animal_renamer": "EnableAnimalRenamer",
}

_SETTINGS_CACHE = None
_SETTINGS_CACHE_MTIME = 0.0


def _save_settings_raw(settings):
    """Save settings to SentientSands_Config.ini."""
    try:
        config = configparser.ConfigParser()
        config.optionxform = lambda optionstr: optionstr
        if os.path.exists(INI_PATH):
            config.read(INI_PATH)

        if "Settings" not in config:
            config["Settings"] = {}

        for key, value in settings.items():
            ini_key = INI_KEY_MAP.get(key)
            if ini_key:
                if isinstance(value, list):
                    config["Settings"][ini_key] = ",".join(value)
                elif isinstance(value, bool):
                    config["Settings"][ini_key] = "1" if value else "0"
                else:
                    config["Settings"][ini_key] = str(value)

        with open(INI_PATH, "w") as handle:
            config.write(handle)
    except Exception as exc:
        logging.error(f"Error saving Settings to INI at {INI_PATH}: {exc}")


def load_settings():
    global _SETTINGS_CACHE, _SETTINGS_CACHE_MTIME

    if os.path.exists(INI_PATH):
        try:
            mtime = os.path.getmtime(INI_PATH)
            if _SETTINGS_CACHE is not None and mtime == _SETTINGS_CACHE_MTIME:
                return _SETTINGS_CACHE.copy()
        except Exception:
            pass

    defaults = {
        "current_model": "player2-default",
        "current_campaign": "Default",
        "enable_ambient": True,
        "radiant_delay": 240,
        "global_events_count": 7,
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
        "language": "English",
        "chat_hotkey": "\\",
        "enable_renamer": True,
        "enable_animal_renamer": True,
    }

    settings = defaults.copy()
    if os.path.exists(INI_PATH):
        try:
            config = configparser.ConfigParser()
            config.optionxform = lambda optionstr: optionstr
            config.read(INI_PATH)
            if "Settings" in config:
                for key in defaults.keys():
                    ini_key = INI_KEY_MAP.get(key)
                    if ini_key and ini_key in config["Settings"]:
                        value = config["Settings"][ini_key]
                        if isinstance(defaults[key], bool):
                            settings[key] = value == "1" or value.lower() == "true"
                        elif isinstance(defaults[key], int):
                            try:
                                settings[key] = int(value)
                            except Exception:
                                pass
                        elif isinstance(defaults[key], float):
                            try:
                                settings[key] = float(value)
                            except Exception:
                                pass
                        elif isinstance(defaults[key], list):
                            settings[key] = [
                                item.strip() for item in value.split(",") if item.strip()
                            ]
                        else:
                            settings[key] = value
        except Exception as exc:
            logging.error(f"Error loading settings from INI: {exc}")

    try:
        if os.path.exists(INI_PATH):
            _SETTINGS_CACHE = settings
            _SETTINGS_CACHE_MTIME = os.path.getmtime(INI_PATH)
    except Exception:
        pass

    return settings


def save_settings(new_settings):
    flat_changes = {}
    for key, value in new_settings.items():
        if key == "radii" and isinstance(value, dict):
            if "radiant" in value:
                flat_changes["radiant_range"] = value["radiant"]
            if "talk" in value:
                flat_changes["talk_radius"] = value["talk"]
            if "yell" in value:
                flat_changes["yell_radius"] = value["yell"]
        else:
            flat_changes[key] = value

    settings = load_settings()
    settings.update(flat_changes)
    _save_settings_raw(settings)


def persist_current_settings():
    """Write the effective settings (with missing defaults filled in) back to the INI file."""
    _save_settings_raw(load_settings())


def get_config_radii():
    settings = load_settings()
    radiant = float(settings.get("radiant_range", 100.0))
    talk = float(settings.get("talk_radius", 100.0))
    yell = float(settings.get("yell_radius", 200.0))
    return radiant, talk, yell
