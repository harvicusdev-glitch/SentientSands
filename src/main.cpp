// 🚨 AGENT PROTOCOL: Before editing this file, you MUST read PROJECT_CONTEXT.md
// 🚨 This project has strict threading and memory safety rules.
#include <string>
#include <vector>
#include <windows.h>

#include "Comm.h"
#include "Context.h"
// 🚨 AGENT PROTOCOL: Before editing this file, you MUST read PROJECT_CONTEXT.md
// 🚨 Kenshi engine writes MUST occur on the main thread inside hooks.
#include "../RE_Kenshi_Source/KenshiLib/Include/core/Functions.h"
#include "CampaignsWindow.h"
#include "GameActions.h"
#include "Globals.h"
#include "ProfileEditorWindow.h"
#include "Utils.h"

#include "../RE_Kenshi_Source/KenshiLib/Include/kenshi/CharStats.h"
#include "../RE_Kenshi_Source/KenshiLib/Include/kenshi/Character.h"
#include "../RE_Kenshi_Source/KenshiLib/Include/kenshi/Dialogue.h"
#include "../RE_Kenshi_Source/KenshiLib/Include/kenshi/Faction.h"
#include "../RE_Kenshi_Source/KenshiLib/Include/kenshi/GameData.h"
#include "../RE_Kenshi_Source/KenshiLib/Include/kenshi/GameWorld.h"
#include "../RE_Kenshi_Source/KenshiLib/Include/kenshi/Inventory.h"
#include "../RE_Kenshi_Source/KenshiLib/Include/kenshi/Item.h"
#include "../RE_Kenshi_Source/KenshiLib/Include/kenshi/Kenshi.h"
#include "../RE_Kenshi_Source/KenshiLib/Include/kenshi/MedicalSystem.h"
#include "../RE_Kenshi_Source/KenshiLib/Include/kenshi/Platoon.h"
#include "../RE_Kenshi_Source/KenshiLib/Include/kenshi/PlayerInterface.h"
#include "../RE_Kenshi_Source/KenshiLib/Include/kenshi/util/hand.h"
#include <kenshi/Damages.h>

#include "../RE_Kenshi_Source/KenshiLib/Include/kenshi/FactionWarMgr.h"
#include "../RE_Kenshi_Source/KenshiLib/Include/kenshi/RaceData.h"
#include "../RE_Kenshi_Source/KenshiLib/Include/kenshi/RootObject.h"
#include "../RE_Kenshi_Source/KenshiLib/Include/kenshi/RootObjectBase.h"
#include "../RE_Kenshi_Source/KenshiLib/Include/kenshi/Town.h"
#include "../RE_Kenshi_Source/KenshiLib/Include/kenshi/WorldEventStateQuery.h"

// Helper to safely get faction names for logging
inline std::string SafeFaction(RootObjectBase *obj) {
  if (!obj || (uintptr_t)obj < 0x1000)
    return "None";
  try {
    Faction *f = obj->getFaction();
    if (f && (uintptr_t)f > 0x1000)
      return f->getName();
  } catch (...) {
  }
  return "None";
}

void (*playerUpdate_orig)(PlayerInterface *) = nullptr;
void (*attackingYou_orig)(Character *, Character *, bool, bool) = nullptr;
void (*applyDamage_orig)(MedicalSystem::HealthPartStatus *,
                         const Damages &) = nullptr;
bool (*applyFirstAid_orig)(MedicalSystem *, float, Item *, float,
                           Character *) = nullptr;
Item *(*buyItem_orig)(Inventory *, Item *, RootObject *) = nullptr;

// New World Event Hooks
void (*triggerCampaign_orig)(FactionWarMgr *, RootObjectBase *, GameData *,
                             float, float, TownBase *, bool,
                             Faction *) = nullptr;
void (*setFaction_orig)(TownBase *, Faction *, ActivePlatoon *) = nullptr;
void (*declareDead_orig)(Character *) = nullptr;
void (*setPrisonMode_orig)(Character *, bool, UseableStuff *) = nullptr;
void (*setProneState_orig)(Character *, ProneState) = nullptr;
bool (*isItOkForMeToLoot_orig)(Character *, RootObject *, Item *) = nullptr;
void (*setChainedMode_orig)(Character *, bool, const hand &) = nullptr;

#include <mygui/MyGUI_Button.h>
#include <mygui/MyGUI_ComboBox.h>
#include <mygui/MyGUI_Delegate.h>
#include <mygui/MyGUI_EditBox.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_InputManager.h>
#include <mygui/MyGUI_TextBox.h>
#include <mygui/MyGUI_Window.h>

#include "ChatUI.h"

// --- Main Hook Core ---
// List of generic name prefixes to detect and replace
static const char *GENERIC_NAME_PREFIXES[] = {"Hungry Bandit",
                                              "Dust Bandit",
                                              "Starving Vagrant",
                                              "Drifter",
                                              "Shop Guard",
                                              "Caravan Guard",
                                              "Slave Hunter",
                                              "Slaver",
                                              "Manhunter",
                                              "Escaped Slave",
                                              "Rebirth Slave",
                                              "Shek Warrior",
                                              "Hive Worker",
                                              "Hive Soldier",
                                              "Hive Prince",
                                              "Fogman",
                                              "Cannibal",
                                              "Outlaw",
                                              "Farmer",
                                              "Nomad",
                                              "Trader",
                                              "Gate Guard",
                                              "Unknown Entity",
                                              "Someone",
                                              "Samurai",
                                              "Holy Sentinel",
                                              "Holy Servant",
                                              "Swamper",
                                              "Tech Hunter",
                                              "Mercenary",
                                              "Citizen",
                                              "Soldier",
                                              "Heavy",
                                              "Captain",
                                              "Sentinel",
                                              "Servant",
                                              "Warrior",
                                              "Assassin",
                                              "Guard",
                                              "Bandit",
                                              "Vagrant",
                                              "Escaped",
                                              "Rebirth",
                                              "Outcast",
                                              "Wanderer",
                                              "Drift",
                                              "Settler",
                                              "Peasant",
                                              "Villager",
                                              "Towns",
                                              "Bowman",
                                              "Leader",
                                              "Elite",
                                              "Drifters",
                                              "Inquisitor",
                                              "Legionnaire",
                                              "Ronin",
                                              "Barman",
                                              "Pacifier",
                                              "Bar Thug",
                                              "Drifter",
                                              0};

static bool IsGenericName(const std::string &name) {
  // Check dynamic prefixes first
  if (!g_genericPrefixes.empty()) {
    for (size_t i = 0; i < g_genericPrefixes.size(); ++i) {
      if (name.find(g_genericPrefixes[i]) != std::string::npos)
        return true;
    }
  }

  // Check dynamic keywords (more aggressive, usually ends of names like
  // "Mercenary Captain")
  if (!g_genericKeywords.empty()) {
    // Basic case-insensitive search if needed, but for now simple find is often
    // enough
    for (size_t i = 0; i < g_genericKeywords.size(); ++i) {
      if (name.find(g_genericKeywords[i]) != std::string::npos)
        return true;
    }
  }

  // Fallback to legacy hardcoded list if dynamic lists are empty
  if (g_genericPrefixes.empty()) {
    for (int i = 0; GENERIC_NAME_PREFIXES[i] != 0; ++i) {
      if (name.find(GENERIC_NAME_PREFIXES[i]) != std::string::npos)
        return true;
    }
  }

  return false;
}

void ProcessMessageQueue(GameWorld *thisptr) {
  if (TryEnterCriticalSection(&g_msgMutex)) {
    while (!g_messageQueue.empty()) {
      std::string msg = g_messageQueue.front();
      g_messageQueue.pop_front();
      Log("HOOK_MSG_PROC: Processing: " + msg);

      bool isNPCAction = (msg.find("NPC_ACTION: ") == 0);
      bool isPlayerSay = (msg.find("PLAYER_SAY: ") == 0);
      bool isNPCSay = (msg.find("NPC_SAY: ") == 0);
      bool isNotify = (msg.find("NOTIFY:") == 0);
      bool isCmd = (msg.find("CMD:") == 0);
      bool isHistory = (msg.find("SHOW_HISTORY: ") == 0);
      bool isRename = (msg.find("NPC_RENAME: ") == 0);

      hand targetHand = g_talkTargetHand;
      // Do not fall back to selection yet; handles inside the branches

      if (isCmd) {
        size_t firstColon = msg.find(":", 4); // skip "CMD: "
        if (firstColon != std::string::npos) {
          std::string command = msg.substr(4, firstColon - 4);
          std::string data = msg.substr(firstColon + 1);

          // Trim command and data
          auto trim = [](std::string &s) {
            s.erase(0, s.find_first_not_of(" \t\r\n"));
            s.erase(s.find_last_not_of(" \t\r\n") + 1);
          };
          trim(command);
          // Do not trim data, it may contain multiline blocks we want to keep
          // exactly

          if (command == "TRIGGER_AMBIENT") {
            g_triggerAmbient = true;
          } else if (command == "POPULATE_WELCOME") {
            PopulateSettingsUI(data);
          } else if (command == "POPULATE_LIBRARY") {
            PopulateLibraryUI(data);
          } else if (command == "SET_LIBRARY_TEXT") {
            SetLibraryText(data);
          } else if (command == "SET_EVENTS_TEXT") {
            SetEventsText(data);
          } else if (command == "SET_CONFIG") {
            size_t colon = data.find(":");
            if (colon != std::string::npos) {
              std::string var = data.substr(0, colon);
              std::string val = data.substr(colon + 1);

              // Trim var and val
              auto trimInternal = [](std::string &s) {
                s.erase(0, s.find_first_not_of(" \t\r\n"));
                s.erase(s.find_last_not_of(" \t\r\n") + 1);
              };
              trimInternal(var);
              trimInternal(val);

              if (var == "g_enableAmbient") {
                g_enableAmbient = (val == "1");
                g_lastAmbientTick = GetTickCount(); // Reset timer on toggle
              } else if (var == "g_ambientIntervalSeconds") {
                g_ambientIntervalSeconds = atoi(val.c_str());
                g_lastAmbientTick =
                    GetTickCount(); // Reset timer on frequency change
              } else if (var == "g_proximityRadius")
                g_proximityRadius = (float)atof(val.c_str());
              else if (var == "g_radiantRange")
                g_radiantRange = (float)atof(val.c_str());
              else if (var == "g_yellRadius")
                g_yellRadius = (float)atof(val.c_str());
              else if (var == "g_minFactionRelation")
                g_minFactionRelation = (float)atof(val.c_str());
              else if (var == "g_maxFactionRelation")
                g_maxFactionRelation = (float)atof(val.c_str());
              else if (var == "g_dialogueSpeedSeconds") {
                g_dialogueSpeedSeconds = atoi(val.c_str());
                g_lastDialogueTick =
                    GetTickCount(); // Reset timer on speed change
              } else if (var == "g_speechBubbleLife") {
                g_speechBubbleLife = (float)atof(val.c_str());
              }
            }
          } else if (command == "POPULATE_SETTINGS") {
            PopulateSettingsUI(data);
          } else if (command == "POPULATE_CAMPAIGNS") {
            PopulateCampaignsUI(data);
          } else if (command == "POPULATE_EVENTS") {
            PopulateEventsUI(data);
          } else if (command == "POPULATE_PROFILE") {
            PopulateProfileEditorUI(data);
          } else if (command == "POPULATE_GENERIC") {
            // Format: "prefix1,prefix2|keyword1,keyword2"
            size_t pipe = data.find("|");
            if (pipe != std::string::npos) {
              std::string pList = data.substr(0, pipe);
              std::string kList = data.substr(pipe + 1);

              g_genericPrefixes.clear();
              g_genericKeywords.clear();

              // Parse prefixes
              size_t cur = 0, next;
              while ((next = pList.find(",", cur)) != std::string::npos) {
                g_genericPrefixes.push_back(pList.substr(cur, next - cur));
                cur = next + 1;
              }
              if (cur < pList.length())
                g_genericPrefixes.push_back(pList.substr(cur));

              // Parse keywords
              cur = 0;
              while ((next = kList.find(",", cur)) != std::string::npos) {
                g_genericKeywords.push_back(kList.substr(cur, next - cur));
                cur = next + 1;
              }
              if (cur < kList.length())
                g_genericKeywords.push_back(kList.substr(cur));

              Log("GENERIC_NAMES: Populated " +
                  ToString((int)g_genericPrefixes.size()) + " prefixes and " +
                  ToString((int)g_genericKeywords.size()) + " keywords.");
            }
          }
        }
      } else if (isRename) {
        // Format: "NPC_RENAME: <serial>|<newName>"
        std::string payload = msg.substr(12); // skip "NPC_RENAME: "
        size_t sep = payload.find('|');
        if (sep != std::string::npos) {
          unsigned int serial =
              (unsigned int)strtoul(payload.substr(0, sep).c_str(), NULL, 10);
          std::string newName = payload.substr(sep + 1);
          if (serial > 0 && !newName.empty() && thisptr) {
            const ogre_unordered_set<Character *>::type &chars =
                thisptr->getCharacterUpdateList();
            for (auto it = chars.begin(); it != chars.end(); ++it) {
              if (*it && (uintptr_t)*it > 0x1000 &&
                  (*it)->getHandle().serial == serial) {
                std::string oldName = (*it)->getName();
                (*it)->setName(newName);
                Log("NAME_ASSIGN: Renamed '" + oldName + "' -> '" + newName +
                    "' (serial " + ToString(serial) + ")");
                break;
              }
            }
          }
        }
      } else if (isHistory) {
        size_t pipePos = msg.find("| ");
        if (pipePos != std::string::npos) {
          std::string name = msg.substr(14, pipePos - 14);
          std::string content = msg.substr(pipePos + 2);
          CreateHistoryUI(name, content);
        }
      } else if (isNotify) {
        std::string text = msg.substr(7);
        EnterCriticalSection(&g_uiMutex);
        QueuedAction act;
        act.type = ACT_NOTIFY;
        act.actor = hand();
        act.target = hand();
        act.message = text;
        act.taskValue = 0;
        g_uiActionQueue.push_back(act);
        LeaveCriticalSection(&g_uiMutex);
      } else if (isPlayerSay || isNPCAction || isNPCSay) {
        g_lastAmbientTick = GetTickCount();

        // 🚨 FIX: For PLAYER_SAY, ensure the bubble appears over the player,
        // not the target NPC.
        if (isPlayerSay) {
          if (thisptr->player && thisptr->player->playerCharacters.size() > 0) {
            targetHand = thisptr->player->playerCharacters[0]->getHandle();
          }
        } else if (!targetHand.isValid()) {
          targetHand = g_lastSelectionHand;
        }

        std::string content = "";
        bool found = false;
        bool header_processed = false;

        if (isNPCSay || isNPCAction) {
          // AI responses should try to resolve the specific speaker if
          // possible, but if no header is found, we fall back to the current
          // talk target.
          hand fallbackHand = targetHand;
          // targetHand = hand(); // 🚨 BUG: Resetting here kills bubbles for
          // single-target talk.

          size_t startPos = isNPCSay ? 9 : 12;
          std::string remainder = msg.substr(startPos);
          size_t colon = remainder.find(':');

          std::string name = "";
          unsigned int tSerial = 0;

          if (colon != std::string::npos && colon < 64 && remainder[0] != '[') {
            header_processed = true;
            std::string header = remainder.substr(0, colon);
            name = header;
            size_t piper = header.find("|");
            if (piper != std::string::npos) {
              name = header.substr(0, piper);
              std::string sStr = header.substr(piper + 1);
              size_t endS = sStr.find_first_not_of("0123456789");
              if (endS != std::string::npos)
                sStr = sStr.substr(0, endS);
              tSerial = (unsigned int)strtoul(sStr.c_str(), NULL, 10);
            }

            std::string nLow = name;
            std::transform(nLow.begin(), nLow.end(), nLow.begin(), ::tolower);

            Character *bestMatch = nullptr;
            int bestScore = 0;

            const ogre_unordered_set<Character *>::type &chars =
                thisptr->getCharacterUpdateList();
            for (auto it = chars.begin(); it != chars.end(); ++it) {
              Character *c = *it;
              if (!c || (uintptr_t)c < 0x1000)
                continue;

              int score = 0;
              if (tSerial > 0 && c->getHandle().serial == tSerial)
                score = 1000;
              else {
                std::string cName = c->getName();
                if (cName == name)
                  score = 500;
                else {
                  std::string cLow = cName;
                  std::transform(cLow.begin(), cLow.end(), cLow.begin(),
                                 ::tolower);
                  if (cLow == nLow)
                    score = 400;
                  else if (cLow.find(nLow) == 0)
                    score =
                        200; // Prefix match (e.g. "Mu" -> "Mu the Wanderer")
                  else if (cLow.find(nLow) != std::string::npos)
                    score = 100; // Substring match (e.g. "Mu" -> "Murphy")
                }
              }

              if (score > bestScore) {
                bestScore = score;
                bestMatch = c;
                if (score == 1000)
                  break; // Serial match is absolute
              }
            }

            if (bestMatch && bestScore > 0) {
              targetHand = bestMatch->getHandle();
              found = true;
            }

            // Fallback sphere check if not found in update list or Score too
            // low
            if (!found && thisptr->player &&
                thisptr->player->playerCharacters.size() > 0) {
              Character *p = thisptr->player->playerCharacters[0];
              lektor<RootObject *> results;
              thisptr->getCharactersWithinSphere(
                  results, p->getPosition(), 2500.0f, 0.0f, 0.0f, 0x10, 0, p);
              for (uint32_t i = 0; i < results.size(); ++i) {
                Character *c = (Character *)results.stuff[i];
                if (!c || (uintptr_t)c < 0x1000)
                  continue;

                int score = 0;
                if (tSerial > 0 && c->getHandle().serial == tSerial)
                  score = 1000;
                else {
                  std::string cName = c->getName();
                  if (cName == name)
                    score = 500;
                  else {
                    std::string cLow = cName;
                    std::transform(cLow.begin(), cLow.end(), cLow.begin(),
                                   ::tolower);
                    if (cLow == nLow)
                      score = 400;
                    else if (cLow.find(nLow) == 0)
                      score = 200;
                    else if (cLow.find(nLow) != std::string::npos)
                      score = 100;
                  }
                }

                if (score > bestScore) {
                  bestScore = score;
                  bestMatch = c;
                  if (score == 1000)
                    break;
                }
              }
              if (bestMatch && bestScore > 0) {
                targetHand = bestMatch->getHandle();
                found = true;
              }
            }

            // Final fallback: If name matches current talk target or is empty,
            // use it
            if (!found && fallbackHand.isValid()) {
              Character *fc = fallbackHand.getCharacter();
              if (fc && (uintptr_t)fc > 0x1000) {
                std::string fcName = fc->getName();
                std::transform(fcName.begin(), fcName.end(), fcName.begin(),
                               ::tolower);
                std::string nLow = name;
                std::transform(nLow.begin(), nLow.end(), nLow.begin(),
                               ::tolower);

                if (name.empty() || fcName == nLow ||
                    fcName.find(nLow) != std::string::npos) {
                  targetHand = fallbackHand;
                  found = true;
                }
              }
            }
          }

          // Strip header if we found the NPC (or if we have a fallback and it's
          // 1-on-1 talk)
          if (found || (header_processed && !found && fallbackHand.isValid())) {
            msg = (isNPCSay ? "NPC_SAY: " : "NPC_ACTION: ") +
                  remainder.substr(colon + 1);
            if (msg.length() > startPos && msg[startPos] == ' ')
              msg.erase(startPos, 1);

            // If we didn't find specific NPC but stripped header, use fallback
            if (!found && fallbackHand.isValid()) {
              targetHand = fallbackHand;
            }
          } else {
            Log("HOOK_MSG_PROC: WARNING: speaker not found: " + name);
          }
        }
      }

      if (isNPCAction) {
        size_t pos = msg.find("[ACTION:");
        if (pos == std::string::npos)
          pos = msg.find("[ACTION: "); // Compatibility

        if (pos != std::string::npos) {
          std::string actStr = msg.substr(pos);
          size_t endp = actStr.find("]");
          if (endp != std::string::npos)
            actStr = actStr.substr(0, endp + 1);

          // Helpful lambda to skip "ACTION:" or other prefixes and trim
          auto getPayload = [](const std::string &str,
                               const std::string &prefix) -> std::string {
            size_t p = str.find(prefix);
            if (p == std::string::npos)
              return "";
            std::string res = str.substr(p + prefix.length());
            if (res.length() > 0 && res.back() == ']')
              res.pop_back();
            // Basic trim
            size_t f = res.find_first_not_of(" ");
            if (f != std::string::npos)
              res.erase(0, f);
            size_t l = res.find_last_not_of(" ");
            if (l != std::string::npos)
              res.erase(l + 1);
            return res;
          };

          if (actStr.find("JOIN_PARTY") != std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_JOIN_PARTY;
            act.actor = targetHand;
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("ATTACK") != std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_ATTACK;
            act.actor = targetHand;
            if (thisptr->player && thisptr->player->playerCharacters.size() > 0)
              act.target = thisptr->player->playerCharacters[0]->getHandle();
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("GIVE_ITEM:") != std::string::npos) {
            std::string iName = getPayload(actStr, "GIVE_ITEM:");
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_GIVE_ITEM;
            act.actor = targetHand;
            act.message = iName;
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("TAKE_ITEM:") != std::string::npos) {
            std::string iName = getPayload(actStr, "TAKE_ITEM:");
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_TAKE_ITEM;
            act.actor = targetHand;
            act.message = iName;
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("DROP_ITEM:") != std::string::npos) {
            std::string iName = getPayload(actStr, "DROP_ITEM:");
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_DROP_ITEM;
            act.actor = targetHand;
            act.message = iName;
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("TAKE_CATS:") != std::string::npos) {
            std::string amtStr = getPayload(actStr, "TAKE_CATS:");
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_TAKE_CATS;
            act.actor = targetHand;
            act.taskValue = atoi(amtStr.c_str());
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("GIVE_CATS:") != std::string::npos) {
            std::string amtStr = getPayload(actStr, "GIVE_CATS:");
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_GIVE_CATS;
            act.actor = targetHand;
            act.taskValue = atoi(amtStr.c_str());
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("LEAVE") != std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_LEAVE;
            act.actor = targetHand;
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("FACTION_RELATIONS:") != std::string::npos) {
            std::string payload = getPayload(actStr, "FACTION_RELATIONS:");
            size_t colon = payload.find(':');
            if (colon != std::string::npos) {
              std::string fName = payload.substr(0, colon);
              // Trim fName
              size_t f = fName.find_first_not_of(" ");
              if (f != std::string::npos)
                fName.erase(0, f);
              size_t l = fName.find_last_not_of(" ");
              if (l != std::string::npos)
                fName.erase(l + 1);

              int amount = atoi(payload.substr(colon + 1).c_str());
              EnterCriticalSection(&g_uiMutex);
              QueuedAction act;
              act.type = ACT_FACTION_RELATIONS;
              act.actor = targetHand;
              act.message = fName;
              act.taskValue = amount;
              g_uiActionQueue.push_back(act);
              LeaveCriticalSection(&g_uiMutex);
            }
          } else if (actStr.find("SPAWN_ITEM:") != std::string::npos) {
            size_t spos = actStr.find("SPAWN_ITEM:");
            std::string payload = actStr.substr(spos + 11);
            if (payload.find("]") != std::string::npos)
              payload = payload.substr(0, payload.find("]"));
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SPAWN_ITEM;
            act.actor = targetHand;
            act.message = payload;
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("FOLLOW_PLAYER") != std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SET_TASK;
            act.actor = targetHand;
            if (thisptr->player && thisptr->player->playerCharacters.size() > 0)
              act.target = thisptr->player->playerCharacters[0]->getHandle();
            act.taskValue = 44; // FOLLOW_PLAYER_ORDER
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("IDLE") != std::string::npos &&
                     actStr.find("TASK:") == std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SET_TASK;
            act.actor = targetHand;
            act.taskValue = 14; // IDLE
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("PATROL_TOWN") != std::string::npos &&
                     actStr.find("TASK:") == std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SET_TASK;
            act.actor = targetHand;
            act.taskValue = 36; // PATROL_TOWN
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("RELEASE_PLAYER") != std::string::npos ||
                     actStr.find("RELEASE_PRISONER") != std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_RELEASE;
            act.actor = targetHand;
            if (thisptr->player && thisptr->player->playerCharacters.size() > 0)
              act.target = thisptr->player->playerCharacters[0]->getHandle();
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("TASK:") != std::string::npos) {
            std::string tName = getPayload(actStr, "TASK:");
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SET_TASK;
            act.actor = targetHand;

            // Set default target to player for player-given orders
            if (thisptr->player && thisptr->player->playerCharacters.size() > 0)
              act.target = thisptr->player->playerCharacters[0]->getHandle();

            // Correct mapping for TaskType (NULL_TASK = 0)
            act.taskValue = 24; // Default to WANDERER
            if (tName == "IDLE")
              act.taskValue = 14;
            else if (tName == "PATROL_TOWN")
              act.taskValue = 36;
            else if (tName == "RUN_AWAY")
              act.taskValue = 35;
            else if (tName == "FOLLOW_PLAYER_ORDER")
              act.taskValue = 44;
            else if (tName == "CHASE")
              act.taskValue = 46;
            else if (tName == "MOVE_ON_FREE_WILL")
              act.taskValue = 1;
            else if (tName == "MELEE_ATTACK") {
              act.taskValue = 4;
            } else if (tName == "RELEASE_PRISONER") {
              act.taskValue = 110;
            }

            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          }
        }
      } else {
        // Normal dialogue bubble
        std::string bubbleContent =
            isPlayerSay ? msg.substr(12) : (isNPCSay ? msg.substr(9) : "");

        // Suppress bubbles for test commands
        if (!bubbleContent.empty()) {
          if (isPlayerSay && bubbleContent[0] == '/')
            bubbleContent = "";
          else if (isNPCSay && bubbleContent.find("[DEBUG]") == 0)
            bubbleContent = "";
        }

        if (!bubbleContent.empty() && targetHand.isValid()) {
          Character *tc = targetHand.getCharacter();
          Log("HOOK_MSG_PROC: Queuing SAY for " +
              (tc ? tc->getName() : "Unknown") + ": " + bubbleContent);
          EnterCriticalSection(&g_uiMutex);
          QueuedAction act;
          act.type = ACT_SAY;
          act.actor = targetHand;
          act.target = targetHand;
          act.message = bubbleContent;
          g_uiActionQueue.push_back(act);
          LeaveCriticalSection(&g_uiMutex);
        }
      }
    }
    LeaveCriticalSection(&g_msgMutex);
  }
}

void attackingYou_hook(Character *npc, Character *attacker, bool so,
                       bool doAwarenessCheck) {
  if (attacker && npc) {
    LogGameEvent("combat", attacker->getName(), SafeFaction(attacker),
                 npc->getName(), SafeFaction(npc), "Initiated attack");
  }
  if (attackingYou_orig)
    attackingYou_orig(npc, attacker, so, doAwarenessCheck);
}

void applyDamage_hook(MedicalSystem::HealthPartStatus *part,
                      const Damages &damage) {
  if (part && part->me && damage.total() > 15.0f) {
    LogGameEvent("combat", "Unknown", "None", part->me->getName(),
                 SafeFaction(part->me),
                 "Took substantial damage: " + ToString((int)damage.total()));
  }
  if (applyDamage_orig)
    applyDamage_orig(part, damage);
}

bool applyFirstAid_hook(MedicalSystem *med, float skill, Item *equipment,
                        float frameTIME, Character *who) {
  bool res = false;
  if (applyFirstAid_orig)
    res = applyFirstAid_orig(med, skill, equipment, frameTIME, who);
  if (res && med && med->me && who) {
    LogGameEvent("healing", who->getName(), SafeFaction(who),
                 med->me->getName(), SafeFaction(med->me),
                 "Applying first aid");
  }
  return res;
}

Item *buyItem_hook(Inventory *inv, Item *itemToBuy, RootObject *sendingTo) {
  if (inv && itemToBuy && sendingTo) {
    LogGameEvent("trade", ((Character *)sendingTo)->getName(),
                 SafeFaction((Character *)sendingTo), inv->owner->getName(),
                 SafeFaction(inv->owner), "Bought " + itemToBuy->getName());
  }
  if (buyItem_orig)
    return buyItem_orig(inv, itemToBuy, sendingTo);
  return nullptr;
}

void triggerCampaign_hook(FactionWarMgr *mgr, RootObjectBase *target,
                          GameData *data, float minTime, float maxTime,
                          TownBase *home, bool forceDuplicate,
                          Faction *triggeringFaction) {
  if (mgr && mgr->me && target) {
    std::string factionName = mgr->me->getName();
    LogGameEvent("raid", factionName, factionName, target->getName(),
                 SafeFaction(target), "Triggered campaign");
  }
  if (triggerCampaign_orig)
    triggerCampaign_orig(mgr, target, data, minTime, maxTime, home,
                         forceDuplicate, triggeringFaction);
}

void setFaction_hook(TownBase *town, Faction *faction, ActivePlatoon *_a2) {
  if (town && faction) {
    Faction *old = town->getFaction();
    std::string oldName = old ? old->getName() : "None";
    std::string newName = faction->getName();

    // Only log if the faction actually changed
    if (oldName != newName) {
      LogGameEvent("city_transfer", oldName, oldName, newName, newName,
                   "Town " + town->getName() + " changed ownership");
    }
  }
  if (setFaction_orig)
    setFaction_orig(town, faction, _a2);
}

void declareDead_hook(Character *npc) {
  if (npc) {
    LogGameEvent("death", npc->getName(), SafeFaction(npc), "None", "None",
                 "Has perished");
  }
  if (declareDead_orig)
    declareDead_orig(npc);
}

void setPrisonMode_hook(Character *npc, bool on, UseableStuff *h) {
  if (npc) {
    std::string msg = on ? "Was imprisoned" : "Was released from prison";
    LogGameEvent("imprisonment", npc->getName(), SafeFaction(npc), "None",
                 "None", msg);
  }
  if (setPrisonMode_orig)
    setPrisonMode_orig(npc, on, h);
}

void setProneState_hook(Character *npc, ProneState p) {
  if (npc && p == PS_KO) {
    LogGameEvent("knockout", "Unknown", "None", npc->getName(),
                 SafeFaction(npc), "Was knocked unconscious");
  }
  if (setProneState_orig)
    setProneState_orig(npc, p);
}

bool isItOkForMeToLoot_hook(Character *npc, RootObject *victim, Item *item) {
  if (npc && victim && item) {
    LogGameEvent("looting", npc->getName(), SafeFaction(npc), victim->getName(),
                 SafeFaction(victim), "Looted " + item->getName());
  }
  if (isItOkForMeToLoot_orig)
    return isItOkForMeToLoot_orig(npc, victim, item);
  return false;
}

void setChainedMode_hook(Character *npc, bool on, const hand &owner) {
  if (npc) {
    std::string msg = on ? "Was forced into slavery" : "Was freed from slavery";
    LogGameEvent("slavery", npc->getName(), SafeFaction(npc), "None", "None",
                 msg);
  }
  if (setChainedMode_orig)
    setChainedMode_orig(npc, on, owner);
}

void playerUpdate_hook(PlayerInterface *thisptr) {
  if (playerUpdate_orig)
    playerUpdate_orig(thisptr);

  // Show Welcome UI once MyGUI is ready
  if (!g_welcomeShown && g_enableWelcome && MyGUI::Gui::getInstancePtr()) {
    CreateWelcomeUI();
    CreateLauncherUI();
    g_welcomeShown = true;
  }

  // 1. Core Selection Tracking
  Character *sel = nullptr;
  try {
    // Priority: target selected by the player
    sel = thisptr->selectedObject.getCharacter();
    if (!sel)
      sel = thisptr->selectedCharacter.getCharacter();
  } catch (...) {
  }

  // Detect Selection Change for Immediate Debugger Update
  EnterCriticalSection(&g_stateMutex);
  bool selectionChanged = false;
  if (sel && (uintptr_t)sel > 0x1000) {
    if (sel->getHandle() != g_lastSelectionHand) {
      g_activeCharName = sel->getName();
      g_lastSelectionHand = sel->getHandle();
      selectionChanged = true;
    }
  } else if (g_lastSelectionHand.isValid()) {
    g_activeCharName = "";
    g_lastSelectionHand = hand();
    selectionChanged = true;
  }
  LeaveCriticalSection(&g_stateMutex);

  // 2. Main System Update (Moved to playerUpdate for responsiveness while
  // paused)
  GameWorld *world = *ppWorld;
  if (world) {
    // Process incoming messages (chat bubbles/notifications) immediately
    ProcessMessageQueue(world);
    static int invTimer = 0;
    ExecuteQueuedActions(world, invTimer);

    // Periodic Context Push for Visual Debugger + Immediate on Selection Change
    static DWORD lastContextTick = 0;
    DWORD now = GetTickCount();
    if (selectionChanged || (now - lastContextTick > 1500)) {
      lastContextTick = now;
      g_lastContextPushTick = now;
      if (sel && (uintptr_t)sel > 0x1000) {
        AsyncPostToPython(L"/context", GetDetailedContext(sel));
      }
      if (world->player && world->player->playerCharacters.size() > 0) {
        Character *player = world->player->playerCharacters[0];
        if (player && (uintptr_t)player > 0x1000) {
          AsyncPostToPython(L"/context", GetDetailedContext(player, "player"));
        }
      }
    }

    // 3. Radiant Banter Trigger
    if (g_enableAmbient) {
      float currentSpeed = world->getFrameSpeedMultiplier();
      if (currentSpeed > 0.1f &&
          !world->isPaused()) { // Only progress timer if game is running and
                                // not paused
        if (g_triggerAmbient || (now - g_lastAmbientTick >
                                 (DWORD)(g_ambientIntervalSeconds * 1000))) {
          g_triggerAmbient = false;
          g_lastAmbientTick = now;

          if (world->player && world->player->playerCharacters.size() > 0) {
            Character *player = world->player->playerCharacters[0];
            lektor<RootObject *> results;
            world->getCharactersWithinSphere(results, player->getPosition(),
                                             g_radiantRange, 0.0f, 0.0f, 16, 0,
                                             player);

            if (results.size() >= 2) { // Need at least 2 NPCs for banter
              std::string npcData = "[";
              bool first = true;
              int count = 0;
              for (uint32_t i = 0; i < results.size() && count < 5; ++i) {
                Character *other = (Character *)results.stuff[i];
                if (other && (uintptr_t)other > 0x1000 && other != player) {
                  // Skip dead or unconscious — they cannot produce speech
                  // bubbles
                  try {
                    if (other->isDead() || other->isUnconcious())
                      continue;
                  } catch (...) {
                  }
                  if (!first)
                    npcData += ",";

                  // Improved extraction
                  RaceData *o_race =
                      other->getRace() ? other->getRace() : other->myRace;
                  std::string o_rn = "Unknown";
                  if (o_race && (uintptr_t)o_race > 0x1000) {
                    if (o_race->data && !o_race->data->name.empty())
                      o_rn = o_race->data->name;
                    else if (o_race->data && !o_race->data->stringID.empty())
                      o_rn = o_race->data->stringID;
                  }

                  std::string identityFaction = GetIdentityFaction(other);
                  npcData +=
                      "{\"name\":\"" + EscapeJSON(other->getName()) + "\",";
                  npcData +=
                      "\"id\":" + ToString((int)other->getHandle().serial) +
                      ",";
                  npcData += "\"race\":\"" + EscapeJSON(o_rn) + "\",";
                  npcData +=
                      "\"gender\":\"" +
                      std::string(other->isFemale() ? "female" : "male") +
                      "\",";
                  npcData +=
                      "\"faction\":\"" + EscapeJSON(identityFaction) + "\"}";
                  first = false;
                  count++;
                }
              }
              npcData += "]";

              int day = 0;
              int hour = 0;
              if (ppWorld && *ppWorld) {
                TimeOfDay tod = (*ppWorld)->getTimeStamp_inGameHours();
                day = (int)tod.getTotalDays();
                hour = (int)tod.getHoursPassed();
              }

              if (count >= 2) {
                std::string *pJson = new std::string(
                    "{\"npcs\": " + npcData + ", \"player\": \"" +
                    EscapeJSON(player->getName()) + "\", \"day\": " +
                    ToString(day) + ", \"hour\": " + ToString(hour) + "}");
                CreateThread(NULL, 0, AmbientPollThread, pJson, 0, NULL);
              }
            }
          }
        }
      }
    }
  }

  // 4. Periodic Generic-Name Scan -> populate g_nameCheckQueue for
  // NameAssignThread
  if (world) {
    static DWORD lastNameScanTick = 0;
    if (GetTickCount() - lastNameScanTick > 2000) {
      lastNameScanTick = GetTickCount();

      // Scan EVERY character in the active world list
      const ogre_unordered_set<Character *>::type &chars =
          world->getCharacterUpdateList();
      for (auto it = chars.begin(); it != chars.end(); ++it) {
        Character *other = *it;
        if (!other || (uintptr_t)other < 0x1000)
          continue;

        unsigned int s = other->getHandle().serial;

        // Skip if already processed
        EnterCriticalSection(&g_nameCheckMutex);
        bool alreadyDone = (g_renamedSerials.count(s) > 0);
        LeaveCriticalSection(&g_nameCheckMutex);

        if (alreadyDone)
          continue;

        std::string oName;
        try {
          oName = other->getName();
        } catch (...) {
          continue;
        }
        if (oName.empty())
          continue;

        // If generic, queue for renaming
        if (IsGenericName(oName)) {
          std::string oGender = other->isFemale() ? "Female" : "Male";
          RaceData *oRace = other->getRace() ? other->getRace() : other->myRace;
          std::string oRaceName = "Human";
          if (oRace && (uintptr_t)oRace > 0x1000 && oRace->data &&
              !oRace->data->name.empty())
            oRaceName = oRace->data->name;

          NameCheckItem ncItem;
          ncItem.serial = s;
          ncItem.name = oName;
          ncItem.gender = oGender;
          ncItem.race = oRaceName;

          EnterCriticalSection(&g_nameCheckMutex);
          bool alreadyQueued = false;
          for (uint32_t q = 0; q < g_nameCheckQueue.size(); ++q) {
            if (g_nameCheckQueue[q].serial == s) {
              alreadyQueued = true;
              break;
            }
          }
          if (!alreadyQueued)
            g_nameCheckQueue.push_back(ncItem);
          LeaveCriticalSection(&g_nameCheckMutex);
        } else {
          // Not generic, mark as done
          EnterCriticalSection(&g_nameCheckMutex);
          g_renamedSerials.insert(s);
          LeaveCriticalSection(&g_nameCheckMutex);
        }
      }
    }
  }

  // 3. Input Handling
  // Chat window hotkey
  if ((GetAsyncKeyState(g_chatHotkey) & 0x8000) && !g_chatWindow &&
      !g_historyWindow && !g_libraryWindow) {
    static DWORD lastTalkTick = 0;
    if (GetTickCount() - lastTalkTick > 500) {
      lastTalkTick = GetTickCount();
      if (sel && (uintptr_t)sel > 0x1000) {
        // Prevent talking to yourself (the main leader in Slot 1).
        // Squadmates (recruits) are now valid talking targets.
        bool isMainPlayer = false;
        const lektor<Character *> &pc = thisptr->getAllPlayerCharacters();
        if (pc.size() > 0 && pc[0] == sel) {
          isMainPlayer = true;
        }

        if (!isMainPlayer) {
          g_talkTargetHand = sel->getHandle();

          // Suppress vanilla dialogue state to prevent "double dialogue"
          if (sel->dialogue && (uintptr_t)sel->dialogue > 0x1000) {
            try {
              sel->dialogue->endDialogue(true);
              sel->dialogue->setInDialog(false);
            } catch (...) {
            }
          }

          std::string pName = (thisptr->playerCharacters.size() > 0)
                                  ? thisptr->playerCharacters[0]->getName()
                                  : "Drifter";
          CreateChatUI(sel->getName(), pName,
                       ToString((int)sel->getHandle().serial));
        }
      }
    }
  }

  // AI Hub Launcher (F8)
  if ((GetAsyncKeyState(VK_F8) & 0x8000)) {
    static DWORD lastLaunchTick = 0;
    if (GetTickCount() - lastLaunchTick > 500) {
      lastLaunchTick = GetTickCount();
      CreateLauncherUI();
    }
  }
}

// Redundant hooks removed since playerUpdate handles real-time needs now.

DWORD WINAPI NameAssignThread(LPVOID lpParam) {
  // Wait for server to be fully ready
  Sleep(8000);
  Log("NAME_ASSIGN: Background name-assignment thread started.");

  while (true) {
    std::vector<NameCheckItem> batch;
    {
      EnterCriticalSection(&g_nameCheckMutex);
      while (!g_nameCheckQueue.empty() && batch.size() < 100) {
        batch.push_back(g_nameCheckQueue.front());
        g_nameCheckQueue.pop_front();
      }
      LeaveCriticalSection(&g_nameCheckMutex);
    }

    if (batch.empty()) {
      Sleep(1000);
      continue;
    }

    // Build batch request JSON
    std::string reqJson = "[";
    for (size_t i = 0; i < batch.size(); ++i) {
      reqJson += "{\"serial\": " + ToString(batch[i].serial) +
                 ", \"name\": \"" + EscapeJSON(batch[i].name) +
                 "\", \"gender\": \"" + EscapeJSON(batch[i].gender) +
                 "\", \"race\": \"" + EscapeJSON(batch[i].race) + "\"}";
      if (i < batch.size() - 1)
        reqJson += ",";
    }
    reqJson += "]";

    std::string resp =
        PostToPythonWithResponse(L"/get_batch_identities", reqJson);
    if (resp.empty() || resp == "[]" || resp[0] != '[')
      continue;

    int assignedCount = 0;
    size_t pos = 0;
    while ((pos = resp.find("{", pos)) != std::string::npos) {
      size_t endPos = resp.find("}", pos);
      if (endPos == std::string::npos)
        break;
      std::string obj = resp.substr(pos, endPos - pos + 1);
      pos = endPos + 1;

      std::string sSerial = GetJsonValue(obj, "serial");
      std::string status = GetJsonValue(obj, "status");
      unsigned int serial = (unsigned int)strtoul(sSerial.c_str(), NULL, 10);

      if (status == "rename") {
        std::string newName = GetJsonValue(obj, "new_name");
        if (!newName.empty()) {
          std::string renameMsg = "NPC_RENAME: " + sSerial + "|" + newName;
          EnterCriticalSection(&g_msgMutex);
          g_messageQueue.push_back(renameMsg);
          LeaveCriticalSection(&g_msgMutex);
          assignedCount++;
        }
      }

      // Mark as done even if status is "ok"
      EnterCriticalSection(&g_nameCheckMutex);
      g_renamedSerials.insert(serial);
      LeaveCriticalSection(&g_nameCheckMutex);
    }

    /*
    if (assignedCount > 0) {
      EnterCriticalSection(&g_msgMutex);
      g_messageQueue.push_back("NOTIFY:Assigned " + ToString(assignedCount) +
                               " unique names to local NPCs.");
      LeaveCriticalSection(&g_msgMutex);
    }
    */
  }
  return 0;
}

DWORD WINAPI MainThread(LPVOID lpParam) {
  HMODULE hLib = GetModuleHandleA("KenshiLib.dll");
  while (!hLib) {
    Sleep(500);
    hLib = GetModuleHandleA("KenshiLib.dll");
  }
  ppWorld = (GameWorld **)GetProcAddress(hLib, "?ou@@3PEAVGameWorld@@EA");
  if (!ppWorld)
    return 1;
  CreateThread(NULL, 0, PipeThread, NULL, 0, NULL);
  CreateThread(NULL, 0, NameAssignThread, NULL, 0, NULL);
  LoadPluginConfig();
  StartPythonServer();
  while (true) {
    DWORD now = GetTickCount();
    if (now - g_lastContextPushTick > 5000) {
      if (ppWorld && *ppWorld && (*ppWorld)->player &&
          (*ppWorld)->player->playerCharacters.size() > 0) {
        Character *player = (*ppWorld)->player->playerCharacters[0];
        if (player && (uintptr_t)player > 0x1000) {
          AsyncPostToPython(L"/context", GetDetailedContext(player, "player"));
          g_lastContextPushTick = now;
        }
      }
    }
    Sleep(2000);
  }
  return 0;
}

__declspec(dllexport) void startPlugin() {
  InitializeCriticalSection(&g_LogMutex);
  InitializeCriticalSection(&g_msgMutex);
  InitializeCriticalSection(&g_uiMutex);
  InitializeCriticalSection(&g_stateMutex);
  InitializeCriticalSection(&g_eventMutex);
  InitializeCriticalSection(&g_nameCheckMutex);
  g_mainThreadId = GetCurrentThreadId();

  HMODULE hLib = GetModuleHandleA("KenshiLib.dll");
  // Hook Player Update for Input and Real-time State
  void *thunkPlayer =
      (void *)GetProcAddress(hLib, "?update@PlayerInterface@@QEAAXXZ");
  if (thunkPlayer)
    KenshiLib::AddHook((void *)KenshiLib::GetRealAddress(thunkPlayer),
                       (void *)playerUpdate_hook, (void **)&playerUpdate_orig);

  // Hook Combat, Healing, and Trade
  void *thunkAttack =
      (void *)GetProcAddress(hLib, "?attackingYou@Character@@QEAAXPEAV1@_N1@Z");
  if (thunkAttack)
    KenshiLib::AddHook((void *)KenshiLib::GetRealAddress(thunkAttack),
                       (void *)attackingYou_hook, (void **)&attackingYou_orig);

  void *thunkDamage = (void *)GetProcAddress(
      hLib,
      "?applyDamage@HealthPartStatus@MedicalSystem@@QEAAXAEBVDamages@@@Z");
  if (thunkDamage)
    KenshiLib::AddHook((void *)KenshiLib::GetRealAddress(thunkDamage),
                       (void *)applyDamage_hook, (void **)&applyDamage_orig);

  void *thunkHeal = (void *)GetProcAddress(
      hLib,
      "?applyFirstAid@MedicalSystem@@QEAA_NMAEAVItem@@MPEAVCharacter@@@Z");
  if (thunkHeal)
    KenshiLib::AddHook((void *)KenshiLib::GetRealAddress(thunkHeal),
                       (void *)applyFirstAid_hook,
                       (void **)&applyFirstAid_orig);

  void *thunkBuy = (void *)GetProcAddress(
      hLib, "?buyItem@Inventory@@QEAAPEAVItem@@PEAV2@PEAVRootObject@@@Z");
  if (thunkBuy)
    KenshiLib::AddHook((void *)KenshiLib::GetRealAddress(thunkBuy),
                       (void *)buyItem_hook, (void **)&buyItem_orig);

  // World Event Hooks (Using mangled names for stability across versions)
  void *thunkRaid = (void *)GetProcAddress(
      hLib,
      "?triggerCampaign@FactionWarMgr@@QEAAXPEAVRootObjectBase@@PEAVGameData"
      "@@MMPEAVTownBase@@_NPEAVFaction@@@Z");
  if (thunkRaid)
    KenshiLib::AddHook((void *)KenshiLib::GetRealAddress(thunkRaid),
                       (void *)triggerCampaign_hook,
                       (void **)&triggerCampaign_orig);

  void *thunkCity = (void *)GetProcAddress(
      hLib, "?setFaction@TownBase@@UEAAXPEAVFaction@@PEAVActivePlatoon@@@Z");
  if (thunkCity)
    KenshiLib::AddHook((void *)KenshiLib::GetRealAddress(thunkCity),
                       (void *)setFaction_hook, (void **)&setFaction_orig);

  void *thunkDeath =
      (void *)GetProcAddress(hLib, "?declareDead@Character@@QEAAXXZ");
  if (thunkDeath)
    KenshiLib::AddHook((void *)KenshiLib::GetRealAddress(thunkDeath),
                       (void *)declareDead_hook, (void **)&declareDead_orig);

  void *thunkPrison = (void *)GetProcAddress(
      hLib, "?setPrisonMode@Character@@QEAAX_NPEAVUseableStuff@@@Z");
  if (thunkPrison)
    KenshiLib::AddHook((void *)KenshiLib::GetRealAddress(thunkPrison),
                       (void *)setPrisonMode_hook,
                       (void **)&setPrisonMode_orig);

  void *thunkKO = (void *)GetProcAddress(
      hLib, "?setProneState@Character@@UEAAXW4ProneState@@@Z");
  if (thunkKO)
    KenshiLib::AddHook((void *)KenshiLib::GetRealAddress(thunkKO),
                       (void *)setProneState_hook,
                       (void **)&setProneState_orig);

  void *thunkLoot = (void *)GetProcAddress(
      hLib, "?isItOkForMeToLoot@Character@@UEAA_NPEAVRootObject@@PEAVItem@@@Z");
  if (thunkLoot)
    KenshiLib::AddHook((void *)KenshiLib::GetRealAddress(thunkLoot),
                       (void *)isItOkForMeToLoot_hook,
                       (void **)&isItOkForMeToLoot_orig);

  void *thunkSlave = (void *)GetProcAddress(
      hLib, "?setChainedMode@Character@@QEAAX_NAEBVhand@@@Z");
  if (thunkSlave)
    KenshiLib::AddHook((void *)KenshiLib::GetRealAddress(thunkSlave),
                       (void *)setChainedMode_hook,
                       (void **)&setChainedMode_orig);

  CreateThread(NULL, 0, MainThread, NULL, 0, NULL);
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD ul_reason_for_call,
                      LPVOID lpReserved) {
  return TRUE;
}
