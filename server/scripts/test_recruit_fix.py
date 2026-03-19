import os
import requests
import time
import json
import hashlib

URL = "http://127.0.0.1:5000/chat"
CHAR_DIR = "G:/Dev/Kenshi-dev/Kenshi-AI/server/campaigns/Default/characters"

pre_payload = {
    "npc": "Masaru",
    "player": "Drifter",
    "message": "Who goes there?",
    "context": json.dumps({
        "name": "Masaru",
        "faction": "Tech Hunters",
        "race": "Shek",
        "gender": "Male",
        "job": "Wandering",
        "money": 500,
        "runtime_id": "99991"
    })
}

print("== Sending PRE-RECRUITMENT context (Tech Hunters) ==")
r1 = requests.post(URL, json=pre_payload)
print(r1.json())

print("Waiting 15 seconds for LLM batch thread to save the character...")
time.sleep(15)

s1 = hashlib.blake2s(b"Masaru_Tech_Hunters", digest_size=6).hexdigest()
f1 = os.path.join(CHAR_DIR, f"Masaru__{s1}.cfg")
if os.path.exists(f1):
    print("SUCCESS: PRE-RECRUIT file exists:", f1)
else:
    print("WARNING: PRE-RECRUIT file missing!", f1)

post_payload = {
    "npc": "Masaru",
    "player": "Drifter",
    "message": "I follow you now, boss.",
    "context": json.dumps({
        "name": "Masaru",
        "faction": "Nameless",
        "origin_faction": "Unknown",
        "race": "Shek",
        "gender": "Male",
        "job": "Following",
        "runtime_id": "14221"
    })
}

print("\n== Sending POST-RECRUITMENT context (Nameless) with NEW memory handle ==")
r2 = requests.post(URL, json=post_payload)
print(r2.json())

print("Waiting 10 seconds for save...")
time.sleep(10)

s2 = hashlib.blake2s(b"Masaru_Nameless", digest_size=6).hexdigest()
f2 = os.path.join(CHAR_DIR, f"Masaru__{s2}.cfg")

if os.path.exists(f2):
    print("FAILURE: System fragmented the identity and created", f2)
else:
    print("SUCCESS: The system properly anchored to the original config instead of fragmenting to", f2)

try:
    if os.path.exists(f1): os.remove(f1)
    if os.path.exists(f2): os.remove(f2)
    h1 = os.path.join(CHAR_DIR, f"history/Masaru__{s1}_History.txt")
    h2 = os.path.join(CHAR_DIR, f"history/Masaru__{s2}_History.txt")
    if os.path.exists(h1): os.remove(h1)
    if os.path.exists(h2): os.remove(h2)
except Exception:
    pass

print("Test complete.")
