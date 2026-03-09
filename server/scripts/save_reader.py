import os
import re
import struct
import logging

def get_latest_save():
    local_app_data = os.environ.get('LOCALAPPDATA')
    if not local_app_data:
        return None
    save_path = os.path.join(local_app_data, 'kenshi', 'save')
    if not os.path.exists(save_path):
        return None
    
    saves = [os.path.join(save_path, d) for d in os.listdir(save_path) if os.path.isdir(os.path.join(save_path, d))]
    if not saves:
        return None
        
    # Sort by modification time
    saves.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    return saves[0]

def scan_platoon_for_characters(platoon_path):
    """
    Scans a .platoon file for character names and serials.
    Kenshi .platoon format is complex, but we can extract names and nearby IDs.
    """
    try:
        with open(platoon_path, 'rb') as f:
            data = f.read()
            
        # This is a heuristic scan. In Kenshi, names are often followed by their IDs or types.
        # We look for common character types: CHARACTER, HUMAN_CHARACTER, ANIMAL_CHARACTER (Type IDs 1, 81, 82)
        # But for now, let's just find all alphanumeric strings that look like names.
        # Strict regex: Start with Upper, follow with 2-15 lowercase letters
        matches = re.findall(b'([A-Z][a-z]{2,15})', data)
        names = []
        for m in matches:
            name = m.decode('utf-8')
            # Filter out common junk words
            if name in ['The', 'And', 'But', 'For', 'With', 'From', 'This']: continue
            names.append(name)
        return list(set(names))
    except Exception as e:
        logging.error(f"Error scanning {platoon_path}: {e}")
        return []

def build_world_index():
    latest = get_latest_save()
    if not latest:
        logging.warning("No Kenshi saves found.")
        return {}
        
    logging.info(f"Scanning save: {latest}")
    platoon_dir = os.path.join(latest, 'platoon')
    if not os.path.exists(platoon_dir):
        return {}
        
    # Determine mod directory relative to this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # script_dir is server/scripts, so mod_dir is root
    mod_dir = os.path.dirname(os.path.dirname(script_dir))
    
    # Check for active campaign if possible, otherwise use root (legacy)
    # Since save_reader doesn't know about campaigns, we'll try to find SentientSands_Mod first
    registry_dir = os.path.join(mod_dir, "sentient_sands_registry")
    
    # Dev environment support
    if not os.path.exists(registry_dir):
        dev_reg = os.path.join(mod_dir, "SentientSands_Mod", "sentient_sands_registry")
        if os.path.exists(dev_reg):
            registry_dir = dev_reg
    
    if not os.path.exists(registry_dir):
        os.makedirs(registry_dir)

    index = {}
    for f in os.listdir(platoon_dir):
        if f.endswith('.platoon'):
            chars = scan_platoon_for_characters(os.path.join(platoon_dir, f))
            for name in chars:
                if name not in index:
                    index[name] = []
                index[name].append(f)
                
                # Fulfill requirement: "Attach a file during initialization"
                # For characters found in save, create their registry entry
                clean_name = re.sub(r'[^\w\s-]', '', name).strip()
                if not clean_name: continue
                reg_file = os.path.join(registry_dir, f"{clean_name.replace(' ', '_')}_init.txt")
                if not os.path.exists(reg_file):
                    with open(reg_file, "w") as rf:
                        rf.write(f"Registry: {name} initialized from save persistence ({f}).\n")

    return index

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    idx = build_world_index()
    for name, files in list(idx.items())[:10]:
        print(f"{name}: {files}")
