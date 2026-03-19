#include "Globals.h"

// Global Definitions
GameWorld **ppWorld = nullptr;
CRITICAL_SECTION g_LogMutex;
std::deque<std::string> g_messageQueue;
CRITICAL_SECTION g_msgMutex;
hand g_talkTargetHand;
DWORD g_mainThreadId = 0;
DWORD g_lastAmbientTick = 0;
DWORD g_lastDialogueTick = 0;
std::map<unsigned int, std::string> g_originFactions;
std::map<unsigned int, OriginState> g_originJobs;
std::string g_modRoot = "";
HMODULE g_hModule = nullptr;

float g_radiantRange = 100.0f;
float g_proximityRadius = 100.0f;
float g_yellRadius = 200.0f;
float g_visionRange = 100.0f;
int g_ambientIntervalSeconds = 240;
bool g_enableAmbient = true;
bool g_enableRenamer = true;
bool g_enableAnimalRenamer = true;
bool g_triggerAmbient = false;
float g_minFactionRelation = -100.0f;
float g_maxFactionRelation = 100.0f;
int g_worldEventIntervalDays = 10;
int g_dialogueSpeedSeconds = 8;
float g_speechBubbleLife = 15.0f;

std::string g_activeInventoryJson = "[]";
hand g_lastInventoryHand;
std::string g_activeCharName = "";
hand g_lastSelectionHand;
hand g_lastChattingPlayerHand;
std::string g_playerInventoryJson = "[]";
hand g_playerHand;
MyGUI::ImageBox *g_loadingIcon = nullptr;
CRITICAL_SECTION g_stateMutex;

std::deque<GameEvent> g_gameEvents;
CRITICAL_SECTION g_eventMutex;

std::deque<QueuedAction> g_uiActionQueue;
CRITICAL_SECTION g_uiMutex;

int g_chatHotkey = VK_OEM_5; // '\' by default
std::string g_chatHotkeyStr = "\\";
std::string g_language = "English";
std::map<std::string, std::string> g_uiTranslation;

std::string T(const std::string &key) {
  auto it = g_uiTranslation.find(key);
  if (it != g_uiTranslation.end())
    return it->second;
  return key;
}

// Background Name Assignment system
std::deque<NameCheckItem> g_nameCheckQueue;
CRITICAL_SECTION g_nameCheckMutex;
std::set<unsigned int> g_renamedSerials;

std::vector<std::string> g_genericPrefixes;
std::vector<std::string> g_genericKeywords;
DWORD g_lastContextPushTick = 0;
