// Sentient Sands - Kenshi AI Mod
// Copyright (C) 2026 Sentient Sands Team
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
//
// You should have received a copy of the GNU General Public License
// along with this program.  If not, see <https://www.gnu.org/licenses/>.

// 🚨 AGENT PROTOCOL: Before editing this file, you MUST read PROJECT_CONTEXT.md
// 🚨 This project has strict threading and memory safety rules.

#ifdef _WIN64
// Linker aliases to cover all common entry point names for Kenshi mod loaders.
// ?startPlugin@@YAXXZ is the C++ mangled name for void startPlugin(void)
#pragma comment(linker, "/export:?startPlugin@@YAXXZ=startPlugin")
#pragma comment(linker, "/export:Init=startPlugin")
#pragma comment(linker, "/export:DllInstall=startPlugin")
#endif

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

static bool IsGenericName(Character *npc, const std::string &name) {
  if (!npc || (uintptr_t)npc < 0x1000)
    return true;

  // 1. Safety check: Never rename unique NPCs
  if (npc->isUnique())
    return false;

  // 2. Multi-language/Default coverage: Check if name matches template name
  // Template names are often what's used for generic NPCs (e.g., "Hungry
  // Bandit") and this works regardless of the game language.
  if (npc->getGameData() && !npc->getGameData()->name.empty()) {
    if (name == npc->getGameData()->name)
      return true;
  }

  // 3. Prefix/Keyword fallbacks (useful for custom mods or variants)
  // We expect g_genericPrefixes/Keywords to be pre-lowercased in
  // POPULATE_GENERIC
  if (!g_genericPrefixes.empty() || !g_genericKeywords.empty()) {
    std::string lowerName = name;
    std::transform(lowerName.begin(), lowerName.end(), lowerName.begin(),
                   ::tolower);

    for (size_t i = 0; i < g_genericPrefixes.size(); ++i) {
      if (lowerName.find(g_genericPrefixes[i]) != std::string::npos)
        return true;
    }

    for (size_t i = 0; i < g_genericKeywords.size(); ++i) {
      if (lowerName.find(g_genericKeywords[i]) != std::string::npos)
        return true;
    }
  }

  // 4. Legacy hardcoded list as a final safety net
  std::string lowerName = name;
  std::transform(lowerName.begin(), lowerName.end(), lowerName.begin(),
                 ::tolower);
  for (int i = 0; GENERIC_NAME_PREFIXES[i] != 0; ++i) {
    std::string lowP = GENERIC_NAME_PREFIXES[i];
    std::transform(lowP.begin(), lowP.end(), lowP.begin(), ::tolower);
    if (lowerName.find(lowP) != std::string::npos)
      return true;
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
      hand speakerHand = hand(); // Used specifically for player SAY bubbles

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
          } else if (command == "RESET_RENAMER") {
            EnterCriticalSection(&g_nameCheckMutex);
            g_renamedSerials.clear();
            LeaveCriticalSection(&g_nameCheckMutex);
            Log("HOOK_MSG_PROC: Renamer cache cleared.");
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
          } else if (command == "ENABLE_REGEN_BTN") {
            if (g_libraryRegenBtn)
              g_libraryRegenBtn->setEnabled(true);
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
                std::string p = pList.substr(cur, next - cur);
                std::transform(p.begin(), p.end(), p.begin(), ::tolower);
                g_genericPrefixes.push_back(p);
                cur = next + 1;
              }
              if (cur < pList.length()) {
                std::string p = pList.substr(cur);
                std::transform(p.begin(), p.end(), p.begin(), ::tolower);
                g_genericPrefixes.push_back(p);
              }

              // Parse keywords
              cur = 0;
              while ((next = kList.find(",", cur)) != std::string::npos) {
                std::string k = kList.substr(cur, next - cur);
                std::transform(k.begin(), k.end(), k.begin(), ::tolower);
                g_genericKeywords.push_back(k);
                cur = next + 1;
              }
              if (cur < kList.length()) {
                std::string k = kList.substr(cur);
                std::transform(k.begin(), k.end(), k.begin(), ::tolower);
                g_genericKeywords.push_back(k);
              }

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
        // The original `isPlayerSay` is derived from `msg.find("PLAYER_SAY:
        // ")`. The user's snippet seems to be for a different message format or
        // a different part of the message processing. Assuming the user wants
        // to replace the existing player-say logic with the new one, and that
        // `type` and `sender` are derived from `msg` in a preceding step not
        // shown. For now, I'll integrate the logic assuming `isPlayerSay` (from
        // `msg`) is the trigger, and the `sender` and `type` variables would
        // need to be parsed from `msg` if this new logic is to be fully
        // functional. Given the instruction "Track the last chatting player", I
        // will adapt the provided snippet to use the existing `isPlayerSay`
        // flag and parse the player name from the message if it's a PLAYER_SAY.

        // Use the global speakerHand for SAY bubbles

        if (isPlayerSay) {
          if (thisptr->player && thisptr->player->playerCharacters.size() > 0) {

            // Unconditionally use the first player character as the speaker
            speakerHand = thisptr->player->playerCharacters[0]->getHandle();
            g_lastChattingPlayerHand = speakerHand;

            // Check if there's a specific name tag to strip
            size_t nameStart = 12; // length of "PLAYER_SAY: "
            size_t nameEnd = msg.find(":", nameStart);
            if (nameEnd != std::string::npos && nameEnd < 64) {
              std::string pName = msg.substr(nameStart, nameEnd - nameStart);
              pName.erase(0, pName.find_first_not_of(" \t\r\n"));
              pName.erase(pName.find_last_not_of(" \t\r\n") + 1);

              bool nameMatched = false;
              for (size_t ci = 0; ci < thisptr->player->playerCharacters.size();
                   ++ci) {
                Character *c = thisptr->player->playerCharacters[ci];
                if (c && c->getName() == pName) {
                  speakerHand = c->getHandle();
                  g_lastChattingPlayerHand = speakerHand;
                  nameMatched = true;
                  break;
                }
              }

              if (nameMatched) {
                std::string textOnly = msg.substr(nameEnd + 1);
                textOnly.erase(0, textOnly.find_first_not_of(" \t\r\n"));
                msg = "PLAYER_SAY: " + textOnly;
              }
            }
          }
        }

        // Ensure targetHand continues to point to the NPC or default target
        if (!targetHand.isValid()) {
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

      if (isNPCAction || isNPCSay) {
        size_t searchPos = 0;
        while (true) {
          size_t startBracket = msg.find("[", searchPos);
          if (startBracket == std::string::npos)
            break;

          size_t endBracket = std::string::npos;
          int depth = 0;
          for (size_t i = startBracket; i < msg.length(); ++i) {
            if (msg[i] == '[')
              depth++;
            else if (msg[i] == ']') {
              depth--;
              if (depth == 0) {
                endBracket = i;
                break;
              }
            }
          }

          if (endBracket == std::string::npos)
            break;

          std::string fullTag =
              msg.substr(startBracket, endBracket - startBracket + 1);
          searchPos = endBracket + 1;

          // Process this specific tag
          std::string actStr = fullTag;

          // Helpful lambda to skip "ACTION:" or other prefixes and trim
          auto getPayload = [](const std::string &str,
                               const std::string &prefix) -> std::string {
            size_t p = str.find(prefix);
            if (p == std::string::npos)
              return "";
            std::string res = str.substr(p + prefix.length());
            // Trim all trailing whitespace and the final closing bracket of the
            // tag
            size_t lnot = res.find_last_not_of(" \t\n\r");
            if (lnot != std::string::npos) {
              res.erase(lnot + 1);
              if (!res.empty() && res.back() == ']')
                res.pop_back();
            }
            // Now do a full trim
            size_t f = res.find_first_not_of(" \t\n\r");
            if (f != std::string::npos)
              res.erase(0, f);
            lnot = res.find_last_not_of(" \t\n\r");
            if (lnot != std::string::npos)
              res.erase(lnot + 1);
            return res;
          };

          if (actStr.find("JOIN_PARTY") != std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_JOIN_PARTY;
            act.actor = targetHand;
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("ATTACK") != std::string::npos &&
                     actStr.find("TOWN") == std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_ATTACK;
            act.actor = targetHand;
            if (thisptr->player && thisptr->player->playerCharacters.size() > 0)
              act.target = thisptr->player->playerCharacters[0]->getHandle();
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("GIVE_ITEM:") != std::string::npos) {
            std::string payload = getPayload(actStr, "GIVE_ITEM:");
            int count = 1;
            // Find colon for count, skipping anything inside brackets
            size_t colon = std::string::npos;
            int depth = 0;
            for (int i = (int)payload.length() - 1; i >= 0; --i) {
              if (payload[i] == ']')
                depth++;
              else if (payload[i] == '[')
                depth--;
              else if (payload[i] == ':' && depth == 0) {
                colon = i;
                break;
              }
            }

            if (colon != std::string::npos) {
              std::string cStr = payload.substr(colon + 1);
              cStr.erase(0, cStr.find_first_not_of(" "));
              cStr.erase(cStr.find_last_not_of(" ") + 1);
              if (!cStr.empty() && isdigit(cStr[0])) {
                count = atoi(cStr.c_str());
                payload = payload.substr(0, colon);
                payload.erase(payload.find_last_not_of(" ") + 1);
              }
            }
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_GIVE_ITEM;
            act.actor = targetHand;
            act.target = g_lastChattingPlayerHand;
            act.message = payload;
            act.taskValue = count;
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("TAKE_ITEM:") != std::string::npos) {
            std::string payload = getPayload(actStr, "TAKE_ITEM:");
            int count = 1;
            // Find colon for count, skipping anything inside brackets
            size_t colon = std::string::npos;
            int depth = 0;
            for (int i = (int)payload.length() - 1; i >= 0; --i) {
              if (payload[i] == ']')
                depth++;
              else if (payload[i] == '[')
                depth--;
              else if (payload[i] == ':' && depth == 0) {
                colon = i;
                break;
              }
            }

            if (colon != std::string::npos) {
              std::string cStr = payload.substr(colon + 1);
              cStr.erase(0, cStr.find_first_not_of(" "));
              cStr.erase(cStr.find_last_not_of(" ") + 1);
              if (!cStr.empty() && isdigit(cStr[0])) {
                count = atoi(cStr.c_str());
                payload = payload.substr(0, colon);
                payload.erase(payload.find_last_not_of(" ") + 1);
              }
            }
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_TAKE_ITEM;
            act.actor = targetHand;
            act.target = g_lastChattingPlayerHand;
            act.message = payload;
            act.taskValue = count;
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
            act.target = g_lastChattingPlayerHand;
            act.taskValue = atoi(amtStr.c_str());
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("GIVE_CATS:") != std::string::npos) {
            std::string amtStr = getPayload(actStr, "GIVE_CATS:");
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_GIVE_CATS;
            act.actor = targetHand;
            act.target = g_lastChattingPlayerHand;
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
            std::string payload = getPayload(actStr, "SPAWN_ITEM:");
            int count = 1;
            size_t pipePos = payload.find('|');
            std::string templateSegment = (pipePos != std::string::npos)
                                              ? payload.substr(0, pipePos)
                                              : payload;

            size_t colon = std::string::npos;
            int depth = 0;
            for (int i = (int)templateSegment.length() - 1; i >= 0; --i) {
              if (templateSegment[i] == ']')
                depth++;
              else if (templateSegment[i] == '[')
                depth--;
              else if (templateSegment[i] == ':' && depth == 0) {
                colon = i;
                break;
              }
            }

            if (colon != std::string::npos) {
              std::string cStr = templateSegment.substr(colon + 1);
              cStr.erase(0, cStr.find_first_not_of(" "));
              cStr.erase(cStr.find_last_not_of(" ") + 1);
              if (!cStr.empty() && isdigit(cStr[0])) {
                count = atoi(cStr.c_str());
                std::string baseTemplate = templateSegment.substr(0, colon);
                baseTemplate.erase(baseTemplate.find_last_not_of(" ") + 1);
                if (pipePos != std::string::npos) {
                  payload = baseTemplate + payload.substr(pipePos);
                } else {
                  payload = baseTemplate;
                }
              }
            }

            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SPAWN_ITEM;
            act.actor = targetHand;
            act.target = g_lastChattingPlayerHand;
            act.message = payload;
            act.taskValue = count;
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
                     actStr.find("RELEASE_PRISONER") != std::string::npos ||
                     actStr.find("FREE_PLAYER") != std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_RELEASE;
            act.actor = targetHand;
            act.taskValue = 110; // RELEASE_PRISONER
            if (thisptr->player && thisptr->player->playerCharacters.size() > 0)
              act.target = thisptr->player->playerCharacters[0]->getHandle();
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("BREAKOUT_PRISONER") != std::string::npos ||
                     actStr.find("BREAKOUT_PLAYER") != std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_RELEASE; // Unified type
            act.actor = targetHand;
            act.taskValue = 111; // BREAKOUT_PRISONER
            if (thisptr->player && thisptr->player->playerCharacters.size() > 0)
              act.target = thisptr->player->playerCharacters[0]->getHandle();
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("MOVE_ON_FREE_WILL_FAST") !=
                     std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SET_TASK;
            act.actor = targetHand;
            act.taskValue = 67; // MOVE_ON_FREE_WILL_FAST
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("MOVE_ON_FREE_WILL") != std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SET_TASK;
            act.actor = targetHand;
            act.taskValue = 1; // MOVE_ON_FREE_WILL
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("GO_HOMEBUILDING") != std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SET_TASK;
            act.actor = targetHand;
            act.taskValue = 19; // GO_HOMEBUILDING
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("STAND_AT_SHOPKEEPER_NODE") !=
                     std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SET_TASK;
            act.actor = targetHand;
            act.taskValue = 20; // STAND_AT_SHOPKEEPER_NODE
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("ATTACK_TOWN") != std::string::npos) {
            std::string tName = getPayload(actStr, "ATTACK_TOWN:");
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SET_TASK;
            act.actor = targetHand;
            act.taskValue = 23; // ATTACK_TOWN
            act.message = tName;
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("RAID_TOWN") != std::string::npos) {
            std::string tName = getPayload(actStr, "RAID_TOWN:");
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SET_TASK;
            act.actor = targetHand;
            act.taskValue = 18; // RAID_TOWN from Enums.h
            act.message = tName;
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("TRAVEL_TO_TARGET_TOWN") !=
                     std::string::npos) {
            std::string tName = getPayload(actStr, "TRAVEL_TO_TARGET_TOWN:");
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SET_TASK;
            act.actor = targetHand;
            act.message = tName; // Store town name for resolution
            act.taskValue = 53;  // TRAVEL_TO_TARGET_TOWN
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("JOB_MEDIC") != std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SET_TASK;
            act.actor = targetHand;
            act.taskValue = 58; // JOB_MEDIC
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("FIND_AND_RESCUE") != std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SET_TASK;
            act.actor = targetHand;
            act.taskValue = 105; // FIND_AND_RESCUE
            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          } else if (actStr.find("JOB_REPAIR_ROBOT") != std::string::npos) {
            EnterCriticalSection(&g_uiMutex);
            QueuedAction act;
            act.type = ACT_SET_TASK;
            act.actor = targetHand;
            act.taskValue = 57; // JOB_REPAIR_ROBOT
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
            } else if (tName == "BREAKOUT_PRISONER") {
              act.taskValue = 111;
            } else if (tName == "MOVE_ON_FREE_WILL") {
              act.taskValue = 1;
            } else if (tName == "MOVE_ON_FREE_WILL_FAST") {
              act.taskValue = 67;
            } else if (tName == "GO_HOMEBUILDING") {
              act.taskValue = 19;
            } else if (tName == "STAND_AT_SHOPKEEPER_NODE") {
              act.taskValue = 20;
            } else if (tName == "ATTACK_TOWN") {
              act.taskValue = 23;
            } else if (tName == "RAID_TOWN") {
              act.taskValue = 18;
            } else if (tName == "TRAVEL_TO_TARGET_TOWN") {
              act.taskValue = 53;
            } else if (tName == "JOB_MEDIC") {
              act.taskValue = 58;
            } else if (tName == "FIND_AND_RESCUE") {
              act.taskValue = 105;
            } else if (tName == "JOB_REPAIR_ROBOT") {
              act.taskValue = 57;
            }

            g_uiActionQueue.push_back(act);
            LeaveCriticalSection(&g_uiMutex);
          }
        }
      }

      // 🚨 FIX: Allow both ACTION and SAY to trigger from the same message.
      // This ensures dialogue bubbles appear even when an action is triggered.
      if (isPlayerSay || isNPCSay || isNPCAction) {
        // Normal dialogue bubble
        std::string bubbleContent =
            isPlayerSay ? msg.substr(12)
                        : (isNPCSay ? msg.substr(9)
                                    : (isNPCAction ? msg.substr(12) : ""));

        // Suppress bubbles for test commands
        if (!bubbleContent.empty()) {
          if (isPlayerSay && bubbleContent[0] == '/')
            bubbleContent = "";
          else if (isNPCSay && bubbleContent.find("[DEBUG]") == 0)
            bubbleContent = "";
        }

        // Clean up action tags from displayed text
        if (!bubbleContent.empty() && (isNPCSay || isNPCAction)) {
          size_t searchPos = 0;
          while (true) {
            size_t aPos = bubbleContent.find("[", searchPos);
            if (aPos == std::string::npos)
              break;

            size_t aEnd = std::string::npos;
            int depth = 0;
            for (size_t i = aPos; i < bubbleContent.length(); ++i) {
              if (bubbleContent[i] == '[')
                depth++;
              else if (bubbleContent[i] == ']') {
                depth--;
                if (depth == 0) {
                  aEnd = i;
                  break;
                }
              }
            }

            if (aEnd != std::string::npos) {
              bubbleContent.erase(aPos, aEnd - aPos + 1);
            } else {
              bubbleContent.erase(aPos);
              break;
            }
          }
          // Trim whitespace that might have been left around the tags
          size_t f = bubbleContent.find_first_not_of(" \t\r\n");
          if (f != std::string::npos)
            bubbleContent.erase(0, f);
          else
            bubbleContent = "";

          size_t l = bubbleContent.find_last_not_of(" \t\r\n");
          if (l != std::string::npos)
            bubbleContent.erase(l + 1);
        }

        // Pick the correct entity to anchor the bubble to
        hand bubbleAnchor = isPlayerSay ? speakerHand : targetHand;

        if (!bubbleContent.empty() && bubbleAnchor.isValid()) {
          Character *tc = bubbleAnchor.getCharacter();
          Log("HOOK_MSG_PROC: Queuing SAY for " +
              (tc ? tc->getName() : "Unknown") + ": " + bubbleContent);
          EnterCriticalSection(&g_uiMutex);
          QueuedAction act;
          act.type = ACT_SAY;
          act.actor = bubbleAnchor;
          act.target = targetHand; // Keep target as the NPC they are talking to
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
    static DWORD lastFrameTickForAmbient = GetTickCount(); // Initialize to current tick
    DWORD deltaTick = now >= lastFrameTickForAmbient ? (now - lastFrameTickForAmbient) : 0;
    lastFrameTickForAmbient = now;

    if (g_enableAmbient) {
      float currentSpeed = world->getFrameSpeedMultiplier();
      
      // If paused or game speed is basically 0, push the timer forward so we don't 
      // accumulate real-time while the user is paused in the menus.
      if (currentSpeed <= 0.1f || world->isPaused()) {
          g_lastAmbientTick += deltaTick;
      } else {
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

                  std::string o_job = "None";
                  if (other->data && !other->data->name.empty())
                    o_job = other->data->name;
                  else if (other->data && !other->data->stringID.empty())
                    o_job = other->data->stringID;

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
                  npcData += "\"job\":\"" + EscapeJSON(o_job) + "\",";
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
  if (world && world->player) {
    static DWORD lastNameScanTick = 0;
    if (GetTickCount() - lastNameScanTick > 2000) {
      lastNameScanTick = GetTickCount();

      // We gather characters from two sources to ensure we don't miss anyone:
      // 1. The active update list (characters currently 'thinking')
      // 2. A sphere search around ALL player-controlled characters
      std::vector<Character *> candidates;

      // Source 1: Update List
      const ogre_unordered_set<Character *>::type &upList =
          world->getCharacterUpdateList();
      for (auto it = upList.begin(); it != upList.end(); ++it) {
        if (*it && (uintptr_t)*it > 0x1000)
          candidates.push_back(*it);
      }

      // Source 2: Sphere Search (catch 'sleeping' NPCs near player)
      const lektor<Character *> &players =
          world->player->getAllPlayerCharacters();
      for (uint32_t pi = 0; pi < players.size(); ++pi) {
        Character *p = players[pi];
        if (!p)
          continue;
        lektor<RootObject *> results;
        world->getCharactersWithinSphere(results, p->getPosition(), 5000.0f,
                                         0.0f, 0.0f, 100, 0, p);
        for (uint32_t ri = 0; ri < results.size(); ++ri) {
          Character *c = (Character *)results.stuff[ri];
          if (c && (uintptr_t)c > 0x1000)
            candidates.push_back(c);
        }
      }

      // Remove duplicates using serials
      std::set<unsigned int> uniqueSerials;
      std::vector<Character *> uniqueCandidates;
      for (size_t ci = 0; ci < candidates.size(); ++ci) {
        Character *c = candidates[ci];
        unsigned int s = c->getHandle().serial;
        if (uniqueSerials.find(s) == uniqueSerials.end()) {
          uniqueSerials.insert(s);
          uniqueCandidates.push_back(c);
        }
      }

      for (size_t ui = 0; ui < uniqueCandidates.size(); ++ui) {
        Character *other = uniqueCandidates[ui];
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
        if (IsGenericName(other, oName)) {
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
          ncItem.is_generic =
              true; // If we're here, IsGenericName returned true

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
                 "\", \"race\": \"" + EscapeJSON(batch[i].race) +
                 "\", \"is_generic\": " +
                 std::string(batch[i].is_generic ? "true" : "false") + "}";
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

static bool g_pluginStarted = false;

extern "C" __declspec(dllexport) void startPlugin() {
  if (g_pluginStarted)
    return;
  g_pluginStarted = true;
  // Initialize mutexes first — Log() requires g_LogMutex to be ready.
  InitializeCriticalSection(&g_LogMutex);
  InitializeCriticalSection(&g_msgMutex);
  InitializeCriticalSection(&g_uiMutex);
  InitializeCriticalSection(&g_stateMutex);
  InitializeCriticalSection(&g_eventMutex);
  InitializeCriticalSection(&g_nameCheckMutex);
  g_mainThreadId = GetCurrentThreadId();

  // Resolve the mod root from the DLL's own location so this works for both
  // regular mods/ installs and Steam Workshop numeric-ID folders.
  if (g_modRoot.empty()) {
    char dllPath[MAX_PATH] = {};
    GetModuleFileNameA(g_hModule, dllPath, MAX_PATH);
    std::string p = dllPath;
    size_t slash = p.find_last_of("\\/");
    g_modRoot = (slash != std::string::npos) ? p.substr(0, slash) : p;
  }
  Log("SYSTEM: Mod root resolved to: " + g_modRoot);

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
  if (ul_reason_for_call == DLL_PROCESS_ATTACH)
    g_hModule = hModule;
  return TRUE;
}
