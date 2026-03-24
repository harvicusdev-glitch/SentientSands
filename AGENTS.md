# Sentient Sands - Development Instructions

AI coding agent instructions for the Sentient Sands Kenshi mod project.

> **For users**: See [`SentientSands/README.md`](../SentientSands/README.md) for installation and configuration.

## Project Overview

Sentient Sands is a Kenshi mod that brings NPCs to life using AI. It consists of:
- **C++ DLL Plugin** (`src/`) - Hooks into Kenshi engine, provides MyGUI-based UI
- **Python Flask Server** (`server/scripts/`) - LLM integration, world state management
- **Mod Assets** (`SentientSands_Mod/`) - Config files, templates, UI assets

## Build & Run Commands

### Python Server Setup
```powershell
# Install dependencies (automated)
.\Setup_Dependencies.bat

# Or manually
pip install -r server/requirements.txt
```

### Running the Mod
1. Launch Kenshi via `RE_Kenshi.exe` (NOT Steam/standard launcher)
2. Enable **Sentient Sands** and **KenshiLib** in mod launcher
3. C++ DLL injects automatically; Python server starts on `localhost:5000`

### C++ Build
- No CMake/Makefile in repo - uses Visual Studio project (not included)
- Requires KenshiLib SDK headers at `../RE_Kenshi_Source/KenshiLib/Include/`
- Requires MyGUI/OGRE headers (Kenshi engine dependencies)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    KENSHI GAME ENGINE                       │
│  RE_Kenshi (script extender) → loads SentientSands.dll      │
│                            ↓                                │
│  C++ DLL (src/)                                             │
│  • Hooks into Kenshi engine functions                       │
│  • MyGUI-based UI windows (Chat, Settings, Events, etc.)    │
│  • WinHTTP communication to Python server                   │
│  • Named pipe for bidirectional messaging                   │
└────────────────────────────────┬────────────────────────────┘
                                 │ HTTP POST (localhost:5000)
                                 ↓
┌─────────────────────────────────────────────────────────────┐
│                  PYTHON FLASK SERVER                        │
│  server/scripts/kenshi_llm_server.py                        │
│  • Routes: /chat, /rename, /ambient, /context, /synthesize  │
│  • LLM Integration: OpenRouter, Ollama, LM Studio, etc.     │
│  • Debug log: server/debug.log (1MB rotating)               │
└─────────────────────────────────────────────────────────────┘
```

### Communication Pattern
- **C++ → Python**: WinHTTP POST to `localhost:5000` (fire-and-forget)
- **Python → C++**: Named pipe `\\.\pipe\SentientSands` (queued in `g_messageQueue`)

### Message Protocol (Python → C++)
Messages sent via named pipe use these formats:

| Type | Format | Purpose |
|------|--------|---------|
| `NPC_SAY:` | `NPC_SAY: Name\|serial: dialogue text` | Speech bubbles |
| `PLAYER_SAY:` | `PLAYER_SAY: PlayerName: dialogue` | Player dialogue display |
| `NPC_ACTION:` | `NPC_ACTION: Name\|serial: [ACTION_TAG]` | Game state changes |
| `NPC_RENAME:` | `NPC_RENAME: serial\|newName` | Assign NPC name |
| `CMD:` | `CMD: POPULATE_GENERIC\|data` | Configuration commands |
| `NOTIFY:` | `NOTIFY: message text` | UI notifications |

### Action Types (C++)
Actions queued from background threads, executed on main thread:
`ACT_SAY`, `ACT_ATTACK`, `ACT_JOIN_PARTY`, `ACT_LEAVE`, `ACT_SET_TASK`, `ACT_GIVE_ITEM`, `ACT_TAKE_ITEM`, `ACT_DROP_ITEM`, `ACT_GIVE_CATS`, `ACT_TAKE_CATS`, `ACT_FACTION_RELATIONS`, `ACT_SPAWN_ITEM`, `ACT_RELEASE`, `ACT_NOTIFY`

## Key Files

| File | Purpose |
|------|---------|
| `src/main.cpp` | C++ plugin entry point (`startPlugin()`), hook setup, generic name detection |
| `src/Comm.cpp` | HTTP communication via WinHTTP, named pipe server (`PipeThread`) |
| `src/llm_client.cpp` | Async LLM request queue with worker thread |
| `src/Context.cpp` | Character context extraction (items, faction, world position, nearby entities) |
| `src/ChatWindow.cpp` | Chat UI with NPC dialog, async LLM response handling |
| `src/GameActions.cpp` | Game action handlers (shackles, cages, recruitment, task assignment) |
| `src/Globals.cpp` | Global state variables (`g_messageQueue`, `g_radiantRange`, etc.) |
| `server/scripts/kenshi_llm_server.py` | Main Flask server (~5700 lines), routes for all AI features |
| `server/scripts/configuration.py` | Path resolution, INI settings, config caching |
| `server/scripts/personality_rules.py` | Faction metadata, race traits, weighted personality generation |
| `SentientSands_Mod/RE_Kenshi.json` | DLL load manifest for script extender |
| `SentientSands_Mod/SentientSands_Config.ini` | User runtime settings (model, ranges, language) |

## Configuration Files

| File | Description |
|------|-------------|
| `server/config/models.json` | Model definitions (friendly name → provider/model) |
| `server/config/providers.json` | API credentials and base URLs |
| `server/config/names.json` | Name pools by gender for NPC generation |
| `server/config/World_lore.json` | Tagged lore chunks for dynamic context injection |
| `server/templates/prompt_chat_template.txt` | Chat prompt structure for LLM |
| `server/templates/prompt_profile_generation.txt` | NPC profile generation prompt |

## Coding Conventions

### C++
- `CamelCase` for functions and classes
- `g_` prefix for global variables (e.g., `g_chatRadius`)
- `SentientSands::UI` namespace for UI components
- Use `SentientSands::Utils` for logging, JSON escape, string conversion

### Python
- `snake_case` for functions and variables
- `UPPER_CASE` for module constants
- Flask routes organized by feature in `kenshi_llm_server.py`

### JSON Config Keys
- Use `snake_case` for all JSON configuration keys

## Critical Constraints

### Kenshi Engine Threading
> ⚠️ **Kenshi engine writes MUST occur on the main thread inside hooks.**

Never attempt to modify game state from background threads. All engine modifications must use the hook system provided by RE_Kenshi and KenshiLib.

Pattern for threaded communication:
```cpp
// Background thread queues message
EnterCriticalSection(&g_msgMutex);
g_messageQueue.push_back(jsonData);
LeaveCriticalSection(&g_msgMutex);

// Main thread hook processes queue
void processMessages() {
  EnterCriticalSection(&g_msgMutex);
  auto queue = g_messageQueue;
  g_messageQueue.clear();
  LeaveCriticalSection(&g_msgMutex);
  // Now safe to modify game state
}
```

### Critical Sections
| Mutex | Protects |
|-------|----------|
| `g_msgMutex` | Message queue between threads |
| `g_stateMutex` | Global state (selection, inventory tracking) |
| `g_LogMutex` | Log file writes |
| `g_uiMutex` | UI action queue |
| `g_eventMutex` | Game event logging |
| `g_nameCheckMutex` | NPC renaming queue |

### Pointer Validation
Always validate pointers before use:
```cpp
if (!npc || (uintptr_t)npc < 0x1000) return;
try {
  // Engine calls protected by try-catch
} catch (...) {
  // Handle partially loaded entities
}
```

### Known Engine Quirks
| Issue | Solution |
|-------|----------|
| `endDialogue(true)` clears AI state | Don't call after setting tasks or speech bubbles disappear |
| `hand::getCharacter()` can return stale pointers | Always validate with `uintptr_t > 0x1000` |
| Game speed affects timers | Use `getFrameSpeedMultiplier()` for time-based logic |
| MyGUI not available before first `playerUpdate` | Gate UI creation with `g_welcomeShown` |

### Communication Pattern
- **C++ → Python**: WinHTTP POST to `localhost:5000`
- **Python → C++**: Named pipe `\\.\pipe\SentientSands`

### Launch Requirement
Users MUST launch via `RE_Kenshi.exe`. Standard Kenshi launcher or Steam will not load the mod.

## API Format

The Python server uses OpenAI-compatible API format. Any provider supporting this format works:
- OpenRouter
- Local Ollama servers
- LM Studio
- NanoGPT, Player2

## Python Server Architecture

### ID Resolution Priority
NPCs are identified using this priority order:
1. `persistent_id` (strong UID format: `"1-304443360-1-2050292992-1"`)
2. `runtime_id` (session-specific)
3. `storage_id` (name_faction derived)
4. `name` (fallback)

### Context Management
- **Live Contexts**: `LIVE_CONTEXTS` dict holds volatile runtime state (health, location, nearby NPCs)
- **Character Cache**: LRU cache of loaded profiles (max 200 entries)
- **Context Window**: ~11,000 token budget; older history dropped when exceeded
- **Token Estimation**: `len(text) * 2 // 7` (≈ chars ÷ 3.5)

### Lore Injection Budgets
World lore is dynamically injected based on NPC tags with token budgets:
| Type | Budget |
|------|--------|
| global | 650 |
| race | 400 |
| faction | 1100 |
| theology | 400 |
| region | 500 |

### Throttling & Cooldowns
| Constant | Seconds |
|----------|---------|
| `AMBIENT_DIRECT_CHAT_COOLDOWN` | 180 |
| `AMBIENT_SPEAKER_COOLDOWN` | 180 |
| `DIRECT_CHAT_GRACE_SECONDS` | 2 |

## Debugging

### Log Files
- **Python server**: `server/debug.log` - 1MB rotating log with all server activity
- **C++ DLL**: Uses `OutputDebugStringA` - view with DebugView or Visual Studio debugger

### Common Issues
| Issue | Cause | Solution |
|-------|-------|----------|
| Mod doesn't load | Wrong launcher | Launch via `RE_Kenshi.exe`, not Steam |
| Python server unreachable | Server not started | Check `localhost:5000` is responding |
| C++ build fails | Missing headers | Ensure KenshiLib SDK at `../RE_Kenshi_Source/KenshiLib/Include/` |
| NPC actions not applying | Threading violation | Engine writes must be on main thread via hooks |

### Testing Python Server
```powershell
# Test server is running
curl http://localhost:5000/health

# View live logs
Get-Content server\debug.log -Wait
```

## Dependencies

### Required (Users)
- Kenshi game (Steam/GOG)
- [RE_Kenshi](https://github.com/BFrizzleFoShizzle/RE_Kenshi/releases) - Script extender
- [KenshiLib](https://github.com/KenshiReclaimer/KenshiLib/releases) - Generic Kenshi library

### Required (Python Server)
- Python 3.10+
- `flask`, `requests`, `dack` (see `server/requirements.txt`)

### Required (C++ Development)
- Visual Studio (Windows C++ compiler)
- KenshiLib SDK headers
- MyGUI, OGRE headers (Kenshi engine dependencies)

## Mod Structure

```
Kenshi/mods/SentientSands/
├── SentientSands.mod          # Mod definition
├── SentientSands.dll          # Compiled C++ plugin
├── RE_Kenshi.json             # Plugin manifest
├── SentientSands_Config.ini    # User settings
├── server/                    # Python backend
│   ├── scripts/               # Flask server and modules
│   ├── config/                # JSON configuration
│   └── templates/             # Prompt templates
└── gui/images/                # UI assets
```