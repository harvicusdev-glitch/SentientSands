# Sentient Sands (Kenshi AI Mod)

Welcome to Sentient Sands, a mod that brings the world of Kenshi to life using AI! This mod allows you to interact dynamically with NPCs, generating unscripted, highly contextual encounters based on the world state, character backgrounds, and your actions.

## 🛠️ Requirements

Before installing Sentient Sands, you must have the following dependencies installed:

1. **[RE_Kenshi](https://github.com/BFrizzleFoShizzle/RE_Kenshi/releases)**: The core script extender required to inject custom C++ code into the Kenshi engine.
2. **[KenshiLib](https://github.com/KenshiReclaimer/KenshiLib/releases)**: A generic library for Kenshi required by our C++ hooks. 

---

## 🚀 Installation Guide

### Step 1: Install RE_Kenshi
1. Download the latest release of `RE_Kenshi`.
2. Extract the contents (`RE_Kenshi.exe`, `RE_Kenshi.dll`, etc.) directly into your **root Kenshi folder** (the one containing `kenshi_x64.exe`).

### Step 2: Install KenshiLib
1. Download the latest release of `KenshiLib`.
2. Extract the `KenshiLib` folder into your **root Kenshi folder**.
   *(Expected path: `...\Kenshi\mods\KenshiLib\KenshiLib.mod`)*

### Step 3: Install Sentient Sands
1. Download the Sentient Sands release package.
2. Copy the entire `SentientSands` folder into your `Kenshi/mods/` directory.
   *(Expected path: `...\Kenshi\mods\SentientSands\SentientSands.mod`)*
3. Ensure that `SentientSands.dll` is present in your `Kenshi\mods\SentientSands\` directory. Our `RE_Kenshi.json` file will automatically instruct RE_Kenshi to load it from here.

### Step 4: Launching the Game
🚨 **CRITICAL REQUIREMENT** 🚨
You **MUST** launch the game using **`RE_Kenshi.exe`**. If you launch the game using the standard Kenshi launcher or through Steam directly (without pointing it to RE_Kenshi), the mod will fail to load, and the AI server will not start.

Ensure **Sentient Sands** and **KenshiLib** are both checked in the Kenshi mod launcher.

---

## ⚙️ Configuring AI Providers & Models

Sentient Sands connects to an embedded Python server running alongside your game. It supports any API that uses the standard OpenAI-compatible format (OpenRouter, local Ollama servers, LM Studio, etc.).

You can add your own custom providers and models without modifying any code. Both configuration files are located in the mod folder at:
`Kenshi/mods/SentientSands/server/config/`

### Adding a New Provider
Edit `providers.json`. A provider strictly requires an `api_key` and a `base_url`.

**Example `providers.json`:**
```json
{
    "openrouter": {
        "api_key": "sk-or-your-api-key-here",
        "base_url": "https://openrouter.ai/api/v1"
    },
    "ollama_local": {
        "api_key": "ollama",
        "base_url": "http://localhost:11434/v1"
    }
}
```

### Adding a New Model
Edit `models.json`. This file links a user-friendly name (which appears in the game's UI) to the exact model string the provider expects.

**Example `models.json`:**
```json
{
    "Llama-3-8B-Instruct": {
        "provider": "ollama_local",
        "model": "llama3"
    },
    "Claude-3.5-Sonnet": {
        "provider": "openrouter",
        "model": "anthropic/claude-3.5-sonnet"
    }
}
```

1. **Top-level key** (e.g., `"Claude-3.5-Sonnet"`): The name you will select in the in-game Settings menu.
2. **`provider`**: Must perfectly match a top-level key from your `providers.json`.
3. **`model`**: The exact model identifier required by the provider.

### Selecting Your Model In-Game
Once you have added models to your config, launch the game, open the Sentient Sands **Settings Window**, and select your desired model from the dropdown menu!
