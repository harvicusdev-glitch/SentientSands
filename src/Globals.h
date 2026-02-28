#include <deque>
#include <map>
#include <set>
#include <string>
#include <vector>
#include <windows.h>

// Forward declarations for Kenshi types
class GameWorld;
namespace Ogre {
class Vector3;
}
#include <kenshi/util/hand.h>

// Global communication state
extern GameWorld **ppWorld;
extern CRITICAL_SECTION g_LogMutex;
extern std::deque<std::string> g_messageQueue;
extern CRITICAL_SECTION g_msgMutex;
extern hand g_talkTargetHand;
extern DWORD g_mainThreadId;
extern DWORD g_lastAmbientTick;
extern DWORD g_lastDialogueTick;
extern std::map<unsigned int, std::string> g_originFactions;

// Configuration variables
extern float g_radiantRange;
extern float g_proximityRadius;
extern float g_yellRadius;
extern float g_visionRange;
extern int g_ambientIntervalSeconds;
extern bool g_enableAmbient;
extern bool g_triggerAmbient;
extern float g_minFactionRelation;
extern float g_maxFactionRelation;
extern int g_worldEventIntervalDays;
extern int g_dialogueSpeedSeconds;
extern float g_speechBubbleLife;

// State tracking for inventory/debugger
extern std::string g_activeInventoryJson;
extern hand g_lastInventoryHand;
extern std::string g_activeCharName;
extern hand g_lastSelectionHand;
extern std::string g_playerInventoryJson;
extern hand g_playerHand;
extern CRITICAL_SECTION g_stateMutex;
extern int g_chatHotkey;
extern std::string g_chatHotkeyStr;
extern std::string g_language;
extern std::map<std::string, std::string> g_uiTranslation;
std::string T(const std::string &key);

// UI Task queue (for thread-safe UI access)
enum ActionType {
  ACT_SAY,
  ACT_ATTACK,
  ACT_JOIN_PARTY,
  ACT_SET_TASK,
  ACT_NOTIFY,
  ACT_DROP_ITEM,
  ACT_GIVE_ITEM,
  ACT_LEAVE,
  ACT_GIVE_CATS,
  ACT_TAKE_CATS,
  ACT_FACTION_RELATIONS,
  ACT_SPAWN_ITEM,
  ACT_RELEASE,
  ACT_TAKE_ITEM
};

struct GameEvent {
  std::string type;
  std::string actor;
  std::string actorFaction;
  std::string target;
  std::string targetFaction;
  std::string message;
  DWORD timestamp;
};

extern std::deque<GameEvent> g_gameEvents;
extern CRITICAL_SECTION g_eventMutex;
void LogGameEvent(const std::string &type, const std::string &actor,
                  const std::string &actorFaction, const std::string &target,
                  const std::string &targetFaction, const std::string &message);

struct QueuedAction {
  ActionType type;
  hand actor;
  hand target;
  std::string message; // Item name, notification message, or Faction Name
  int taskValue;       // For ACT_SET_TASK, money amounts, or Relation Change
};

extern std::deque<QueuedAction> g_uiActionQueue;
extern CRITICAL_SECTION g_uiMutex;

// Background Name Assignment system
struct NameCheckItem {
  unsigned int serial;
  std::string name;
  std::string gender; // "Male" | "Female"
  std::string race;
};
extern std::deque<NameCheckItem> g_nameCheckQueue;
extern CRITICAL_SECTION g_nameCheckMutex;
extern std::set<unsigned int> g_renamedSerials;
extern DWORD g_lastContextPushTick;

// Centralized generic name lists (loaded from config)
extern std::vector<std::string> g_genericPrefixes;
extern std::vector<std::string> g_genericKeywords;
