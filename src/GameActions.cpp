#include "GameActions.h"
#include "Context.h"
#include "Globals.h"
#include "Utils.h"
#include <algorithm>
#include <core/Functions.h>
#include <kenshi/Character.h>
#include <kenshi/CharStats.h>
#include <kenshi/Dialogue.h>
#include <kenshi/Faction.h>
#include <kenshi/FactionRelations.h>
#include <kenshi/GameData.h>
#include <kenshi/GameWorld.h>
#include <kenshi/Inventory.h>
#include <kenshi/Building/Building.h>
#include <kenshi/Item.h>
#include <kenshi/Platoon.h>
#include <kenshi/PlayerInterface.h>
#include <kenshi/RootObjectFactory.h>
#include <kenshi/SensoryData.h>
#include <kenshi/Town.h>
#include <kenshi/util/YesNoMaybe.h>
#include <kenshi/util/hand.h>
#include <ogre/OgreColourValue.h>
#include <vector>

// Forward-declared access to the chat player name stored by the UI layer
namespace SentientSands {
namespace UI {
extern std::string g_chatPlayerNameStr;
}
} // namespace SentientSands

void PerformLeaveSquad(Character *npc, GameWorld *world,
                       const std::string &originFaction) {
  if (!npc || !world)
    return;

  std::string factionPart = originFaction;
  std::string platoonPart = "";
  size_t pipePos = originFaction.find('|');
  if (pipePos != std::string::npos) {
    factionPart = originFaction.substr(0, pipePos);
    platoonPart = originFaction.substr(pipePos + 1);
  }

  Log("ACTION_EXEC: Dismissing " + npc->getName() + " (Target Faction: " +
      factionPart + ", Target Platoon: " + platoonPart + ")");

  if (world->player) {
    world->player->unselectPlayerCharacter(npc);
    lektor<Character *> &pc = world->player->playerCharacters;
    for (uint32_t i = 0; i < pc.size(); ++i) {
      if (pc.stuff[i] == npc) {
        for (uint32_t j = i; j < pc.size() - 1; ++j)
          pc.stuff[j] = pc.stuff[j + 1];
        pc.count--;
        Log("ACTION_EXEC: Removed " + npc->getName() +
            " from playerCharacters list.");
        break;
      }
    }
  }

  if (world->factionMgr) {
    FactionManager *fm = world->factionMgr;

    std::string targetFactionName = "Drifters";
    if (!factionPart.empty() && factionPart != "Unknown") {
      targetFactionName = factionPart;
    } else if (g_originFactions.count(npc->getHandle().serial)) {
      targetFactionName = g_originFactions[npc->getHandle().serial];
    }

    Faction *targetFaction = fm->getFactionByName(targetFactionName);

    // If Drifters requested or origin is missing, try to find the character's
    // original faction but exclude the player faction.
    if ((factionPart.empty() || factionPart == "Unknown" ||
         targetFactionName == "Drifters") &&
        npc->getGameData()) {
      GameData *characterData = npc->getGameData();
      // Try to find the original faction link in the character's template data
      const Ogre::vector<GameDataReference>::type *refs =
          characterData->getReferenceListIfExists("faction");
      if (refs && !refs->empty()) {
        Faction *refFaction = fm->getFactionByStringID(refs->at(0).sid);
        if (refFaction && !refFaction->isThePlayer()) {
          targetFaction = refFaction;
          targetFactionName = targetFaction->getName();
        }
      }
    }

    // Give fallback if origin doesn't exist (e.g. invalid string)
    if (!targetFaction || targetFaction->isThePlayer() ||
        targetFaction->isNotARealFaction()) {
      targetFactionName = "Drifters";
      targetFaction = fm->getFactionByName("Drifters");
    }

    if (!targetFaction || targetFaction->isThePlayer()) {
      targetFaction = NULL;
      const lektor<Faction *> *all = fm->getAllFactions();
      if (all) {
        for (uint32_t i = 0; i < all->count; ++i) {
          Faction *f = all->stuff[i];
          if (f && !f->isThePlayer() && !f->isNotARealFaction()) {
            targetFaction = f;
            if (f->getName() == targetFactionName)
              break;
          }
        }
      }
    }

    if (targetFaction) {
      Log("ACTION_EXEC: Moving character to target faction: " +
          targetFaction->getName());

      ActivePlatoon *ap = NULL;

      // Attempt to find existing platoon if requested
      if (!platoonPart.empty()) {
        const lektor<Platoon *> *activePlats =
            targetFaction->getActivePlatoons();
        if (activePlats) {
          for (uint32_t i = 0; i < activePlats->count; ++i) {
            Platoon *p = activePlats->stuff[i];
            if (p && (p->stringID == platoonPart ||
                      p->getPlatoonStringID() == platoonPart)) {
              ap = p->getActivePlatoon();
              if (ap) {
                Log("ACTION_EXEC: Found existing active platoon: " +
                    platoonPart);
                break;
              }
            }
          }
        }
      }

      // Fallback: Create a new platoon if no existing one found/active
      if (!ap) {
        Platoon *newPlat = targetFaction->createNewEmptyActivePlatoon(
            NULL, true, npc->getPosition());
        if (newPlat) {
          ap = newPlat->getActivePlatoon();
          Log("ACTION_EXEC: Created new platoon for dismissal.");
        }
      }

      if (ap) {
        npc->setFaction(targetFaction, ap);

        // Ensure the platoon has a leader if it was just created
        if (ap->getSquadSize() == 1 || !ap->getSquadLeader()) {
          ap->setSquadLeader(npc);
        }

        // --- RESTORE NPC DATA PACKAGES ---
        // Restore standard NPC AI systems (was using Player AI)
        npc->setupAI();
        npc->setupPlatoonAI();

        // Stabilize home town if currently in one (recruits often lose this)
        TownBase *currentTown = npc->getCurrentTownLocation();
        if (currentTown) {
          Ownerships *own = npc->getOwnerships();
          if (own)
            own->setHomeTown(currentTown, SQ_RESIDENT); // Use RESIDENT in town
        }

        npc->reThinkCurrentAIAction();
      } else {
        Log("ACTION_EXEC: ERROR: Could not create or find a platoon for "
            "dismissal!");
      }
    }
  }
}

// Helper to convert internal TaskType enums to human-readable strings for
// UI/Logging
std::string GetTaskName(TaskType tt) {
  switch ((int)tt) {
  case 1:
    return "MOVE_ON_FREE_WILL";
  case 4:
    return "MELEE_ATTACK";
  case 14:
    return "IDLE";
  case 15:
    return "WANDER_TOWN";
  case 18:
    return "RAID_TOWN";
  case 19:
    return "GO_HOMEBUILDING";
  case 20:
    return "STAND_AT_SHOPKEEPER_NODE";
  case 23:
    return "ATTACK_TOWN";
  case 24:
    return "WANDERER";
  case 35:
    return "RUN_AWAY";
  case 36:
    return "PATROL_TOWN";
  case 44:
    return "FOLLOW_PLAYER_ORDER";
  case 46:
    return "CHASE";
  case 53:
    return "TRAVEL_TO_TARGET_TOWN";
  case 55:
    return "BODYGUARD";
  case 57:
    return "JOB_REPAIR_ROBOT";
  case 58:
    return "JOB_MEDIC";
  case 67:
    return "MOVE_ON_FREE_WILL_FAST";
  case 105:
    return "FIND_AND_RESCUE";
  case 110:
    return "RELEASE_PRISONER";
  case 111:
    return "BREAKOUT_PRISONER";
  case 185:
    return "CUT_SHACKLES";
  case 201:
    return "PICK_LOCK_ON_SHACKLES";
  default:
    return "TASK_" + ToString((int)tt);
  }
}

void ExecuteQueuedActions(GameWorld *thisptr, int &inventoryTimer) {
  std::deque<QueuedAction> localQueue;
  if (TryEnterCriticalSection(&g_uiMutex)) {
    localQueue = g_uiActionQueue;
    g_uiActionQueue.clear();
    LeaveCriticalSection(&g_uiMutex);
  }

  bool transactionFailed = false;
  std::string failureReason = "";

  for (size_t actIdx = 0; actIdx < localQueue.size(); ++actIdx) {
    try {
      const QueuedAction &act = localQueue[actIdx];
      Character *npc = act.actor.getCharacter();
      Character *target = act.target.getCharacter();

      if (act.type == ACT_NOTIFY) {
        thisptr->showPlayerAMessage_withLog(act.message, true);
      } else if (act.type == ACT_SAY && npc) {
        bool isPC = npc->isPlayerCharacter();
        Log("ACTION_EXEC: SAY [" + npc->getName() + "]: " + act.message +
            (isPC ? " (PC)" : " (NPC)"));
        try {
          // 🚨 FIX: Removed endDialogue(true) and setInDialog(false).
          // Calling these resets the character's AI state and clears goals.
          // Since actions now fire before speech, calling this would
          // immediately cancel the task the NPC just received (e.g., Follow
          // Player). sayALine handles its own visual state.

          // Primary method: sayALine (supports multiple lines/delays)
          npc->sayALine(act.message, true);

          // 🚨 FIX: Speech bubbles disappear too fast at high game speeds.
          // Scale the timer by game speed to keep it visible for ~5s real-time.
          // We set both timers to ensure the engine honors our duration.
          if (npc->dialogue && (uintptr_t)npc->dialogue > 0x1000) {
            float speed = thisptr->getFrameSpeedMultiplier();
            if (speed < 1.0f)
              speed = 1.0f;
            float duration = g_speechBubbleLife * speed;
            npc->dialogue->speechTextTimer = duration;
            npc->dialogue->speechTextTimer_forced = duration;
          } else {
            // Secondary fallback: say (force floating text bubble)
            // ONLY if dialogue system failed to initialize for this character
            npc->say(act.message);
          }

        } catch (...) {
          Log("ACTION_EXEC: SAY (ERROR): Exception during sayALine/say");
        }
      } else if (npc) {
        if (act.type == ACT_ATTACK && target) {
          if (npc->getFaction() && npc->getFaction()->isThePlayer()) {
            PerformLeaveSquad(npc, thisptr, "");
            npc->clearAllAIGoals();
          }
          npc->attackTarget(target);
          npc->addGoal(MELEE_ATTACK, (RootObjectBase *)target);
          npc->reThinkCurrentAIAction();
          thisptr->showPlayerAMessage(npc->getName() + " is attacking!", false);
        } else if (act.type == ACT_JOIN_PARTY && thisptr->player) {
          // 🚨 STORE PREVIOUS JOBS AND HOME BEFORE RECRUITMENT
          // This allows them to go back to their original behavior upon
          // dismissal.
          unsigned int serial = npc->getHandle().serial;
          OriginState state;

          // Store Home context if available
          Ownerships *own = npc->getOwnerships();
          if (own) {
            state.homeTown =
                own->_homeTown ? own->_homeTown->getHandle() : hand();
            state.homeBuilding = own->_homeBuilding;
          }

          int jobCount = npc->getPermajobCount();
          for (int i = 0; i < jobCount; ++i) {
            OriginJob oj;
            oj.type = npc->getPermajob(i);
            // Default to null, we rely on home building for specific tasks
            oj.target = hand();
            oj.location = npc->getPosition();
            state.jobs.push_back(oj);
          }
          g_originJobs[serial] = state;

          thisptr->player->recruit(npc, false);
          thisptr->playNotification("ui_cat_change");
          thisptr->showPlayerAMessage_withLog(
              npc->getName() + " joined your squad.", true);
        } else if (act.type == ACT_LEAVE) {
          npc->clearPermajobs();
          npc->clearAllAIGoals();
          PerformLeaveSquad(npc, thisptr, act.message);

          // Restore stored original jobs if they exist
          unsigned int serial = npc->getHandle().serial;
          if (g_originJobs.count(serial)) {
            const OriginState &state = g_originJobs[serial];

            // Restore Home context
            Ownerships *own = npc->getOwnerships();
            if (own) {
              TownBase *town = state.homeTown.getTown();
              if (town)
                own->setHomeTown(town, npc->getPlatoon()->me->squadType);
              if (state.homeBuilding.isValid())
                own->setHomeBuilding(state.homeBuilding,
                                     npc->getPlatoon()->me->squadType);
            }

            for (size_t i = 0; i < state.jobs.size(); ++i) {
              RootObject *subject = state.jobs[i].target.getRootObject();

              // Special case for shopkeepers: use home building as subject if
              // target is missing
              if (!subject && state.jobs[i].type == STAND_AT_SHOPKEEPER_NODE) {
                subject = (RootObject *)state.homeBuilding.getBuilding();
              }

              npc->addJob(state.jobs[i].type, subject, false, true,
                          state.jobs[i].location);
            }
          }

          // Clear limiting orders (Passive/Hold) that might prevent movement
          npc->setStandingOrder((MessageForB::StandingOrder)13 /* PASSIVE */,
                                false);
          npc->setStandingOrder((MessageForB::StandingOrder)12 /* HOLD */,
                                false);

          if (npc->getPermajobCount() == 0) {
            TownBase *town = npc->getCurrentTownLocation();
            if (town) {
              npc->addJob(WANDER_TOWN, (RootObject *)town, false, false,
                          npc->getPosition());
              npc->addGoal(WANDER_TOWN, (RootObjectBase *)town);
            } else {
              npc->addJob(WANDERER, NULL, false, false, npc->getPosition());
              npc->addGoal(WANDERER, NULL);
            }
          }
          npc->reThinkCurrentAIAction();
          thisptr->showPlayerAMessage_withLog(
              npc->getName() + " left your squad.", true);

        } else if (act.type == ACT_SET_TASK) {
          Log("ACTION_EXEC: Setting task for " + npc->getName() + ": " +
              ToString(act.taskValue) +
              (target ? " (Target: " + target->getName() + ")" : ""));

          // 🚨 DO NOT call endDialogue here — it kills the speech bubble that
          // the NPC just displayed. The dialogue system will clear naturally.

          // Clear limiting orders (Passive/Hold) that might prevent task
          // execution Matches enum values in MessageForB::StandingOrder
          npc->setStandingOrder((MessageForB::StandingOrder)13 /* PASSIVE */,
                                false);
          npc->setStandingOrder((MessageForB::StandingOrder)12 /* HOLD */,
                                false);

          npc->clearAllAIGoals();

          TaskType tt = (TaskType)act.taskValue;
          RootObject *taskTarget = (RootObject *)target;

          // SPECIAL HANDLING: If told to travel or raid a specific town
          if ((tt == TRAVEL_TO_TARGET_TOWN || tt == ATTACK_TOWN ||
               (int)tt == 18) &&
              !act.message.empty()) {
            std::string tName = act.message;
            // Cleanup quotes and whitespace
            size_t fnot = tName.find_first_not_of(" \t\n\r\"'");
            if (fnot != std::string::npos) {
              tName.erase(0, fnot);
              size_t lnot = tName.find_last_not_of(" \t\n\r\"'");
              if (lnot != std::string::npos)
                tName.erase(lnot + 1);
            }

            Log("ACTION_EXEC: Resolving town target for " + ToString(tt) +
                ": '" + tName + "'");

            std::string tLow = tName;
            std::transform(tLow.begin(), tLow.end(), tLow.begin(), ::tolower);

            lektor<RootObject *> resultTowns;
            (*ppWorld)->getObjectsWithinSphere(resultTowns, npc->getPosition(),
                                               10000000.0f, TOWN, 500, NULL);
            for (uint32_t i = 0; i < resultTowns.size(); ++i) {
              TownBase *tb = (TownBase *)resultTowns[i];
              if (tb) {
                std::string tbName = ((RootObjectBase *)tb)->getName();
                std::transform(tbName.begin(), tbName.end(), tbName.begin(),
                               ::tolower);

                // Try exact match or contains
                if (tbName == tLow || tbName.find(tLow) != std::string::npos) {
                  taskTarget = (RootObject *)tb;
                  Log("ACTION_EXEC: Found town match: " +
                      ((RootObjectBase *)tb)->getName());
                  break;
                }
              }
            }
            if (!taskTarget) {
              Log("ACTION_EXEC: WARNING: Town '" + tName +
                  "' not found in 10M units!");
            }
          }

          // SPECIAL HANDLING: If told to patrol/wander/attack town, ensure use
          // town target not player target (only if we didn't just find a
          // specific one above)
          if ((tt == PATROL_TOWN || tt == WANDER_TOWN || tt == ATTACK_TOWN ||
               tt == GO_HOMEBUILDING || tt == STAND_AT_SHOPKEEPER_NODE) &&
              !taskTarget) {
            TownBase *town = npc->getCurrentTownLocation();
            if (town)
              taskTarget = (RootObject *)town;
          } else if (tt == IDLE || tt == WANDERER || tt == RUN_AWAY ||
                     tt == MOVE_ON_FREE_WILL || tt == MOVE_ON_FREE_WILL_FAST) {
            // These tasks shouldn't have the player as a target or they walk
            // into the player. Medic/Rescue should have a target to follow.
            taskTarget = NULL;
          }

          bool isPermanent =
              (tt == TRAVEL_TO_TARGET_TOWN || tt == ATTACK_TOWN ||
               (int)tt == 18 || // RAID_TOWN
               tt == PATROL_TOWN || tt == WANDER_TOWN ||
               tt == GO_HOMEBUILDING || tt == STAND_AT_SHOPKEEPER_NODE ||
               tt == JOB_MEDIC || tt == JOB_REPAIR_ROBOT ||
               tt == FIND_AND_RESCUE || tt == FOLLOW_PLAYER_ORDER ||
               tt == BODYGUARD);

          Log("ACTION_EXEC: Final Dispatch -> Task: " + ToString((int)tt) +
              " (" + GetTaskName(tt) + "), Target: " +
              (taskTarget ? ((RootObjectBase *)taskTarget)->getName()
                          : "NULL") +
              ", Permanent: " + (isPermanent ? "YES" : "NO"));

          if (tt == JOB_MEDIC || tt == FIND_AND_RESCUE ||
              tt == JOB_REPAIR_ROBOT) {
            // Bundle caregiver tasks: Rescue (lower priority) then Medic
            // (higher priority) Using shift=false with addJob prepends, so the
            // LAST one added becomes the current top priority.
            npc->addJob(FIND_AND_RESCUE, taskTarget, false, true,
                        npc->getPosition());
            npc->addJob(JOB_MEDIC, taskTarget, false, true, npc->getPosition());
            if (tt == JOB_REPAIR_ROBOT) {
              npc->addJob(JOB_REPAIR_ROBOT, taskTarget, false, true,
                          npc->getPosition());
            }
            thisptr->showPlayerAMessage(
                npc->getName() + " is now in caregiver mode (Medic & Rescue).",
                false);
          } else {
            npc->addJob(tt, taskTarget, false, isPermanent, npc->getPosition());
            thisptr->showPlayerAMessage(
                npc->getName() + " is now executing: " + GetTaskName(tt),
                false);
          }

          npc->addGoal(tt, (RootObjectBase *)taskTarget);
          npc->reThinkCurrentAIAction();
        } else if (act.type == ACT_DROP_ITEM) {
          std::vector<Item *> items;
          GetAllCharacterItems(npc, items);
          std::string targetName = act.message;
          // Cleanup quotes and whitespace
          size_t fnot = targetName.find_first_not_of(" \t\n\r\"'");
          if (fnot != std::string::npos) {
            targetName.erase(0, fnot);
            size_t lnot = targetName.find_last_not_of(" \t\n\r\"'");
            if (lnot != std::string::npos)
              targetName.erase(lnot + 1);
          }
          std::transform(targetName.begin(), targetName.end(),
                         targetName.begin(), ::tolower);

          for (uint32_t i = 0; i < items.size(); ++i) {
            std::string itemName = items[i]->getName();
            std::transform(itemName.begin(), itemName.end(), itemName.begin(),
                           ::tolower);
            if (itemName.find(targetName) != std::string::npos) {
              Log("ACTION_EXEC: Dropping item: " + items[i]->getName());
              npc->dropItem(items[i]);
              thisptr->showPlayerAMessage_withLog(
                  npc->getName() + " dropped " + items[i]->getName(), true);
              npc->reThinkCurrentAIAction();
              break;
            }
          }
        } else if (act.type == ACT_TAKE_ITEM) {
          Character *player = act.target.isValid() ? act.target.getCharacter() : nullptr;
          if (!player || (uintptr_t)player < 0x1000) {
            player = (thisptr->player && thisptr->player->playerCharacters.size() > 0)
                         ? thisptr->player->playerCharacters[0]
                         : nullptr;
          }
          if (player) {
            std::string targetName = act.message;
            size_t fnot = targetName.find_first_not_of(" \t\n\r\"'");
            if (fnot != std::string::npos) {
              targetName.erase(0, fnot);
              size_t lnot = targetName.find_last_not_of(" \t\n\r\"'");
              if (lnot != std::string::npos)
                targetName.erase(lnot + 1);
            }
            std::string lowerTarget = targetName;
            std::transform(lowerTarget.begin(), lowerTarget.end(),
                           lowerTarget.begin(), ::tolower);

            int count = act.taskValue;
            if (count < 1)
              count = 1;
            int taken = 0;

            Log("ACTION_EXEC: NPC " + npc->getName() + " attempting to take " +
                ToString(count) + "x '" + targetName + "'");

            while (taken < count) {
              std::vector<Item *> pItems;
              GetAllCharacterItems(player, pItems);
              Item *found = nullptr;

              for (uint32_t i = 0; i < pItems.size(); ++i) {
                Item *it = pItems[i];
                if (!it)
                  continue;
                std::string itemName = it->getName();
                std::transform(itemName.begin(), itemName.end(),
                               itemName.begin(), ::tolower);
                if (itemName.find(lowerTarget) != std::string::npos) {
                  found = it;
                  break;
                }
              }

              if (found) {
                int toTake = std::min(found->quantity, (int)(count - taken));
                Log("ACTION_EXEC: Taking item (" + ToString(taken + toTake) + "/" +
                    ToString(count) + "): " + found->getName() + " (Qty: " + ToString(toTake) + ")");
                
                if (found->isEquipped)
                  player->unequipItem(found->inventorySection, found);

                Inventory *inv = found->getInventory();
                if (!inv)
                  inv = player->getInventory();

                Item *detached = inv ? inv->removeItemDontDestroy_returnsItem(
                                           found, toTake, false)
                                     : nullptr;
                
                if (detached) {
                  int actualQty = detached->quantity;
                  bool success = npc->giveItem(detached, true, false);
                  if (success) {
                    taken += actualQty;
                  } else {
                    // SHOP UPGRADE: Try to put it in a shop counter if they are a trader
                    bool putInCounter = false;
                    try {
                      if (npc->isATrader()) {
                        const hand &bHandle = npc->isIndoors();
                        if (bHandle.isValid()) {
                          Building *b = bHandle.getBuilding();
                          if (b) {
                            lektor<Building *> counters;
                            b->findAllFurnitureWithFunction(counters, BF_SHOP);
                            for (uint32_t i = 0; i < counters.size(); ++i) {
                              if (counters[i] && counters[i]->getInventory()) {
                                if (counters[i]->getInventory()->addItem(
                                        detached, detached->quantity, false,
                                        false)) {
                                  putInCounter = true;
                                  break;
                                }
                              }
                            }
                          }
                        }
                      }
                    } catch (...) {
                    }

                    if (putInCounter) {
                      Log("ACTION_EXEC: NPC " + npc->getName() +
                          " inventory full. Put item " + detached->getName() +
                          " into shop counter.");
                      taken += actualQty;
                    } else {
                      Log("ACTION_EXEC: NPC " + npc->getName() +
                          " inventory full! Item " + detached->getName() +
                          " destroyed (confiscated).");
                      thisptr->destroy(detached, false, "confiscated");
                      taken += actualQty; // Count it as taken for UI messages
                      break; // Stop taking items if we hit a full inventory
                    }
                  }
                } else {
                  Log("ACTION_EXEC: ERROR: Failed to detach item " + found->getName() + " from player!");
                  break; 
                }
              } else {
                // No more items matching this name
                break;
              }
            }

            if (taken < count) {
              transactionFailed = true;
              failureReason = "Not enough items.";
              Log("ACTION_EXEC: TRANSACTION FAILED: " + npc->getName() + " wanted " + ToString(count) + " but only found " + ToString(taken));
            }

            if (taken > 0) {
              std::string msg = npc->getName() + " took " +
                                (taken > 1 ? ToString(taken) + "x " : "") +
                                targetName + " from you.";
              thisptr->showPlayerAMessage_withLog(msg, true);
              npc->reThinkCurrentAIAction();
              inventoryTimer = 999;
            } else {
              Log("ACTION_EXEC: NPC " + npc->getName() +
                  " found NO items matching '" + targetName + "' on player.");
            }
          }
        } else if (act.type == ACT_GIVE_ITEM) {
          if (transactionFailed) {
            Log("ACTION_EXEC: Skipping GIVE_ITEM due to previous transaction failure (" + failureReason + ")");
            continue;
          }
          std::vector<Item *> items;
          GetAllCharacterItems(npc, items);
          std::string targetName = act.message;
          size_t fnot = targetName.find_first_not_of(" \t\n\r\"'");
          if (fnot != std::string::npos) {
            targetName.erase(0, fnot);
            size_t lnot = targetName.find_last_not_of(" \t\n\r\"'");
            if (lnot != std::string::npos)
              targetName.erase(lnot + 1);
          }
          std::string originalTargetName = targetName;
          std::transform(targetName.begin(), targetName.end(),
                         targetName.begin(), ::tolower);

          int count = act.taskValue;
          if (count < 1)
            count = 1;
          int given = 0;

          Character *player = act.target.isValid() ? act.target.getCharacter() : nullptr;
          if (!player || (uintptr_t)player < 0x1000) {
            player = (thisptr->player && thisptr->player->playerCharacters.size() > 0)
                         ? thisptr->player->playerCharacters[0]
                         : nullptr;
          }

          if (player) {
            while (given < count) {
              std::vector<Item *> npcItems;
              GetAllCharacterItems(npc, npcItems);
              Item *found = nullptr;

              for (uint32_t i = 0; i < npcItems.size(); ++i) {
                std::string itemName = npcItems[i]->getName();
                std::transform(itemName.begin(), itemName.end(),
                               itemName.begin(), ::tolower);
                if (itemName.find(targetName) != std::string::npos) {
                  found = npcItems[i];
                  break;
                }
              }

              if (found) {
                int toGive = std::min(found->quantity, (int)(count - given));
                Log("ACTION_EXEC: Giving item (" + ToString(given + toGive) + "/" +
                    ToString(count) + "): " + found->getName() + " (Qty: " + ToString(toGive) + ")");
                
                if (found->isEquipped)
                  npc->unequipItem(found->inventorySection, found);
                
                Inventory *inv = found->getInventory();
                if (!inv)
                  inv = npc->getInventory();

                Item *detached = inv ? inv->removeItemDontDestroy_returnsItem(
                                           found, toGive, false)
                                     : nullptr;
                
                if (detached) {
                  int actualQty = detached->quantity;
                  bool success = player->giveItem(detached, true, false);
                  if (success) {
                    given += actualQty;
                  } else {
                    Log("ACTION_EXEC: Player inventory full! Returning item to NPC.");
                    npc->giveItem(detached, true, false);
                    break; // Stop giving items if player is full
                  }
                } else {
                  Log("ACTION_EXEC: ERROR: Failed to detach item " + found->getName() + " from NPC!");
                  break;
                }
              } else {
                // NPC has no more of this item
                break;
              }
            }

            if (given < count) {
              Log("ACTION_EXEC: NPC " + npc->getName() + " only had " +
                  ToString(given) + " of '" + originalTargetName +
                  "'. Fallback to SPAWN for remaining " +
                  ToString(count - given));
              itemType types[] = {ITEM,     WEAPON,    ARMOUR,
                                  CROSSBOW, BLUEPRINT, LIMB_REPLACEMENT,
                                  MAP_ITEM};
              GameData *gd = nullptr;
              for (int t = 0; t < 7; t++) {
                gd = thisptr->leveldata.getDataByName(originalTargetName,
                                                      types[t]);
                if (!gd)
                  gd = thisptr->gamedata.getDataByName(originalTargetName,
                                                       types[t]);
                if (gd)
                  break;
              }

              if (gd) {
                int toSpawn = count - given;
                for (int s = 0; s < toSpawn; s++) {
                  Item *spawned = thisptr->theFactory->createItem(
                      gd, hand(), NULL, NULL, 0, NULL);
                  if (spawned) {
                    spawned->quantity = 1;
                    spawned->setProperOwner(player->getHandle());
                    bool success = player->giveItem(spawned, true, false);
                    if (success)
                      given++;
                  }
                }
              }
            }

            if (given > 0) {
              std::string msg =
                  npc->getName() + " gave you " +
                  (given > 1 ? ToString(given) + "x " : "") +
                  (given > 1 ? originalTargetName : originalTargetName);
              thisptr->showPlayerAMessage_withLog(msg, true);
              npc->reThinkCurrentAIAction();
              inventoryTimer = 999;
            }
          }
        } else if (act.type == ACT_GIVE_CATS) {
          if (transactionFailed) {
            Log("ACTION_EXEC: Skipping GIVE_CATS due to previous transaction failure (" + failureReason + ")");
            continue;
          }
          Character *player = act.target.isValid() ? act.target.getCharacter() : nullptr;
          if (!player || (uintptr_t)player < 0x1000) {
            player = (thisptr->player && thisptr->player->playerCharacters.size() > 0)
                         ? thisptr->player->playerCharacters[0]
                         : nullptr;
          }
          if (npc && player) {
            int amt = act.taskValue;
            if (amt > 0) {
              player->takeMoney(-amt);

              // Avoid no-op transfers to characters already in player faction
              bool alreadyPlayer =
                  (npc && npc->getFaction() && npc->getFaction()->isThePlayer());
              if (npc && !alreadyPlayer)
                npc->takeMoney(amt);

              thisptr->showPlayerAMessage_withLog(
                  "Gained " + ToString(amt) + " cats.", true);
            }
          }
        } else if (act.type == ACT_TAKE_CATS) {
          Character *p = act.target.isValid() ? act.target.getCharacter() : nullptr;
          if (!p || (uintptr_t)p < 0x1000) {
            p = (thisptr->player && thisptr->player->playerCharacters.size() > 0)
                    ? thisptr->player->playerCharacters[0]
                    : nullptr;
          }
          if (p) {
            int targetAmt = act.taskValue;
            int pMoney = p->getMoney();
            if (pMoney <= 0 && p->getOwnerships())
              pMoney = p->getOwnerships()->getMoney();

            int amt = targetAmt;
            if (amt > pMoney) {
              amt = pMoney;
              transactionFailed = true;
              failureReason = "Not enough cats.";
            }
            if (amt < 1) {
              amt = 0;
            }

            Log("ACTION_EXEC: Taking " + ToString(amt) + " cats from " +
                p->getName() + " (Requested: " + ToString(targetAmt) +
                ", Bank: " + ToString(pMoney) + ")");
            p->takeMoney(amt);

            // 🚨 RECRUITMENT FEE PROTECTION
            // If the NPC is also being recruited in this same batch, do NOT
            // give the refund to their new player pocket.
            bool beingRecruited = false;
            for (size_t i = 0; i < localQueue.size(); ++i) {
              if (localQueue[i].type == ACT_JOIN_PARTY &&
                  localQueue[i].actor == act.actor) {
                beingRecruited = true;
                break;
              }
            }

            bool alreadyPlayer =
                (npc && npc->getFaction() && npc->getFaction()->isThePlayer());

            if (npc && !beingRecruited && !alreadyPlayer) {
              npc->takeMoney(-amt);
            } else {
              Log("ACTION_EXEC: Recruitment fee or sign-on bonus. Money spent "
                  "but not given to recruit pocket.");
            }

            thisptr->showPlayerAMessage_withLog(
                "Lost " + ToString(amt) + " cats.", true);

            if (transactionFailed) {
              thisptr->showPlayerAMessage(
                  npc->getName() +
                      " looks annoyed. \"That's not what we agreed on!\"",
                  true);
            }
          }
        } else if (act.type == ACT_RELEASE && npc && target) {
          // IN_PRISON is enum value 2
          bool inCage = (target->inSomething == 2);
          bool shackled = target->isChained || target->isChainedMode();
          float dist = npc->getPosition().distance(target->getPosition());

          Log("ACTION_EXEC: Release/Breakout by " + npc->getName() + " on " +
              target->getName() + ". InCage: " + ToString(inCage) +
              ", Shackled: " + ToString(shackled) +
              ", Dist: " + ToString(dist));

          // FORCE EXECUTION IF CLOSE
          // This bypasses the engine task clearing (crouch & clear) for
          // recruits/friends.
          if (dist < 4.0f && (inCage || shackled)) {
            Log("ACTION_EXEC: Proximity force-release triggered.");
            if (shackled) {
              target->setChainedMode(false, hand());
              target->isChained = false;
            }
            if (inCage) {
              target->setPrisonMode(false, nullptr);
              // Manually clear the enclosure state if setPrisonMode isn't
              // enough
              target->inSomething = (UseStuffState)0; // IN_NOTHING
            }
            thisptr->showPlayerAMessage("You have been freed!", true);
          }

          bool didSomething = false;

          // 1. Handle Carrying (Drop first)
          if (npc->isCarryingSomething &&
              npc->carryingObject == target->getHandle()) {
            Log("ACTION_EXEC: NPC is carrying target. Dropping.");
            npc->dropCarriedObject(false, false);
            didSomething = true;
          }

          // 2. Handle Imprisonment (Cage/Shackles)
          if (inCage || shackled) {
            // Identify the best task
            TaskType tt = RELEASE_PRISONER; // Default 110
            if (act.taskValue == 111) {
              tt = BREAKOUT_PRISONER; // 111
              if (shackled && !inCage)
                tt = (TaskType)201; // PICK_LOCK_ON_SHACKLES
            } else if (shackled && !inCage) {
              tt = RELEASE_PRISONER; // Usually handles legal unshackling
            }

            Log("ACTION_EXEC: Assigning task: " + GetTaskName(tt) + " (" +
                ToString((int)tt) + ")");

            // Use addOrder (immediate override) instead of addJob
            // The clear=true flag stops background AI like "Staying home"
            npc->clearAllAIGoals();
            npc->addOrder(nullptr, tt, (RootObject *)target, false, true,
                          target->getPosition());
            npc->reThinkCurrentAIAction();

            thisptr->showPlayerAMessage(npc->getName() +
                                            (act.taskValue == 111
                                                 ? " is breaking out "
                                                 : " is releasing ") +
                                            target->getName() + "!",
                                        false);
            didSomething = true;
          }

          if (!didSomething && !npc->isPlayerCharacter()) {
            Log("ACTION_EXEC: Target already free. Clearing NPC goals.");
            npc->clearAllAIGoals();
            npc->reThinkCurrentAIAction();
          }
        } else if (act.type == ACT_FACTION_RELATIONS) {
          if (thisptr->factionMgr) {
            Faction *targetFaction =
                thisptr->factionMgr->getFactionByStringID(act.message);
            if (!targetFaction)
              targetFaction =
                  thisptr->factionMgr->getFactionByName(act.message);
            Faction *playerFaction =
                thisptr->player ? thisptr->player->getFaction() : nullptr;
            if (!playerFaction)
              playerFaction =
                  thisptr->factionMgr->getFactionByStringID("Nameless_0");

            if (targetFaction && playerFaction) {
              Log("ACTION_EXEC: Direct Faction Relation change: " +
                  act.message + " (" + ToString(act.taskValue) + ")");
              if (playerFaction->relations)
                playerFaction->relations->affectRelations(
                    targetFaction, (float)act.taskValue, 1.0f);
              if (targetFaction->relations)
                targetFaction->relations->affectRelations(
                    playerFaction, (float)act.taskValue, 1.0f);
              thisptr->showPlayerAMessage_withLog(
                  "Political clout shift: Relationship with " +
                      targetFaction->getName() + " modified.",
                  true);
            }
          }
        } else if (act.type == ACT_SPAWN_ITEM) {
          // 🚨 NOTE: ACT_SPAWN_ITEM does NOT require npc to be valid.
          // It only needs thisptr (GameWorld). This block is intentionally
          // at this level, not nested inside 'else if (npc)'.
          std::string payload = act.message;

          // 🚨 SAFETY: Some LLM responses or test commands might double-up the
          // prefix. Strip redundant "SPAWN_ITEM:" from the payload if present.
          if (payload.find("SPAWN_ITEM:") == 0) {
            payload = payload.substr(11);
            size_t first = payload.find_first_not_of(" \t\r\n");
            if (first != std::string::npos)
              payload = payload.substr(first);
          }

          std::string templateName, itemName, itemDesc;
          size_t pipe1 = payload.find('|');
          if (pipe1 != std::string::npos) {
            templateName = payload.substr(0, pipe1);
            size_t pipe2 = payload.find('|', pipe1 + 1);
            if (pipe2 != std::string::npos) {
              itemName = payload.substr(pipe1 + 1, pipe2 - pipe1 - 1);
              itemDesc = payload.substr(pipe2 + 1);
            } else {
              itemName = payload.substr(pipe1 + 1);
            }
          } else {
            templateName = payload;
          }

          auto trim = [](std::string &s) {
            size_t first = s.find_first_not_of(" \t\n\r\"'");
            if (first == std::string::npos) {
              s = "";
              return;
            }
            s.erase(0, first);
            size_t last = s.find_last_not_of(" \t\n\r\"'");
            if (last != std::string::npos)
              s.erase(last + 1);

            // Normalize internal whitespace (e.g. \n or multiple spaces) to a
            // single space
            for (size_t i = 0; i < s.length(); ++i) {
              if (s[i] == '\r' || s[i] == '\n' || s[i] == '\t')
                s[i] = ' ';
            }
            // Collapse multiple spaces
            size_t p = s.find("  ");
            while (p != std::string::npos) {
              s.erase(p, 1);
              p = s.find("  ");
            }
          };
          trim(templateName);
          trim(itemName);
          trim(itemDesc);

          // --- ROBUST LOOKUP ---
          // Try direct, then plural, then substring
          itemType types[] = {ITEM,      WEAPON,           ARMOUR,  CROSSBOW,
                              BLUEPRINT, LIMB_REPLACEMENT, MAP_ITEM};
          GameData *gd = nullptr;

          auto findInSource = [&](GameDataManager &dm,
                                  const std::string &name) -> GameData * {
            for (int i = 0; i < 7; i++) {
              GameData *found = dm.getDataByName(name, types[i]);
              if (found)
                return found;
            }
            // Case-insensitive fallback pass
            std::string lowerName = name;
            std::transform(lowerName.begin(), lowerName.end(),
                           lowerName.begin(), ::tolower);
            boost::unordered::unordered_map<std::string, GameData *>::iterator
                it;
            for (it = dm.gamedataSID.begin(); it != dm.gamedataSID.end();
                 ++it) {
              GameData *check = it->second;
              if (check && !check->name.empty()) {
                std::string lowerCheck = check->name;
                std::transform(lowerCheck.begin(), lowerCheck.end(),
                               lowerCheck.begin(), ::tolower);
                if (lowerCheck == lowerName) {
                  for (int t = 0; t < 7; t++) {
                    if (check->type == types[t])
                      return check;
                  }
                }
              }
            }
            return (GameData *)nullptr;
          };

          gd = findInSource(thisptr->leveldata, templateName);
          if (!gd)
            gd = findInSource(thisptr->gamedata, templateName);

          if (!gd) {
            // Try plural
            std::string plural = templateName + "s";
            gd = findInSource(thisptr->leveldata, plural);
            if (!gd)
              gd = findInSource(thisptr->gamedata, plural);
          }

          if (!gd) {
            // Substring search (slow fallback)
            std::string lowerTemplate = templateName;
            std::transform(lowerTemplate.begin(), lowerTemplate.end(),
                           lowerTemplate.begin(), ::tolower);
            boost::unordered::unordered_map<std::string, GameData *>::iterator
                it;
            for (it = thisptr->gamedata.gamedataSID.begin();
                 it != thisptr->gamedata.gamedataSID.end(); ++it) {
              GameData *check = it->second;
              if (check && !check->name.empty()) {
                std::string lowerName = check->name;
                std::transform(lowerName.begin(), lowerName.end(),
                               lowerName.begin(), ::tolower);
                if (lowerName.find(lowerTemplate) != std::string::npos) {
                  // Ensure it's an item type
                  for (int t = 0; t < 7; t++) {
                    if (check->type == types[t]) {
                      gd = check;
                      break;
                    }
                  }
                  if (gd)
                    break;
                }
              }
            }
          }

          if (gd) {
            Log("ACTION_EXEC: Resolved " + templateName + " to " + gd->name +
                " (Type: " + ToString(gd->type) + ")");

            Character *p = act.target.getCharacter();
            if (!p || (uintptr_t)p < 0x1000) {
              if (thisptr->player &&
                  thisptr->player->playerCharacters.size() > 0)
                p = thisptr->player->playerCharacters[0];
            }

            if (p) {
              int count = act.taskValue;
              if (count < 1)
                count = 1;
              int spawnedCount = 0;

              for (int c = 0; c < count; c++) {
                Log("ACTION_EXEC: Spawning " + gd->name + " (" +
                    ToString(c + 1) + "/" + ToString(count) + ") for " +
                    p->getName());

                // 🛠️ FIX: Weapons, Armor, and Crossbows need specific
                // manufacturer/material data.
                GameData *meshData = nullptr;
                GameData *materialData = nullptr;

                if (gd->type == WEAPON || gd->type == ARMOUR ||
                    gd->type == CROSSBOW || gd->type == LIMB_REPLACEMENT) {
                  // 1. Try to find references in the item template itself
                  auto getRef = [&](const std::string &refName) -> GameData * {
                    const Ogre::vector<GameDataReference>::type *refs =
                        gd->getReferenceListIfExists(refName);
                    if (refs && !refs->empty()) {
                      GameData *r = thisptr->gamedata.getData(refs->at(0).sid);
                      if (r) {
                        Log("ACTION_EXEC: Found " + refName + " ref: " +
                            r->name + " (Type: " + ToString(r->type) + ")");
                      }
                      return r;
                    }
                    return nullptr;
                  };

                  int requiredMeshType = 0;
                  if (gd->type == WEAPON)
                    requiredMeshType = MATERIAL_SPECS_WEAPON;
                  else if (gd->type == ARMOUR)
                    requiredMeshType = MATERIAL_SPECS_CLOTHING;
                  else if (gd->type == LIMB_REPLACEMENT || gd->type == CROSSBOW)
                    requiredMeshType = MATERIAL_SPEC; // Both limbs and crossbows often use MATERIAL_SPEC or similar for grades

                  // 🛠️ FIX: Weapons use "material" for the grade/quality,
                  // while "mesh" is visual. The factory's 3rd arg expects the
                  // grade data (MATERIAL_SPECS_WEAPON or CLOTHING).
                  meshData = getRef("material");
                  if (!meshData ||
                      (requiredMeshType && meshData->type != requiredMeshType))
                    meshData = getRef("model");
                  if (!meshData ||
                      (requiredMeshType && meshData->type != requiredMeshType))
                    meshData = getRef("mesh");

                  materialData = getRef("manufacturer");

                  // 2. Fallback: Search global gamedata for "Standard" versions
                  // if template lacks them OR if the resolved ref is the wrong
                  // type.
                  bool needsMesh =
                      !meshData ||
                      (requiredMeshType && meshData->type != requiredMeshType);
                  bool needsMat = !materialData ||
                                  (materialData->type != WEAPON_MANUFACTURER);

                  if (needsMesh || needsMat) {
                    // 🛠️ FIX: Scale spawned item quality by NPC's skill.
                    // This prevents "Prototype" quality gear from late-game NPCs.
                    int npcSkill = 30;
                    if (npc && (uintptr_t)npc > 0x1000 && npc->getStats()) {
                      auto s = npc->getStats();
                      int s1 = (int)s->getStat(STAT_MELEE_ATTACK, false);
                      int s2 = (int)s->getStat(STAT_SMITHING_WEAPON, false);
                      int s3 = (int)s->getStat(STAT_SMITHING_ARMOUR, false);
                      int s4 = (int)s->getStat(STAT_SCIENCE, false);
                      int s5 = (int)s->getStat(STAT_ROBOTICS, false);
                      npcSkill = s1;
                      if (s2 > npcSkill) npcSkill = s2;
                      if (s3 > npcSkill) npcSkill = s3;
                      if (s4 > npcSkill) npcSkill = s4;
                      if (s5 > npcSkill) npcSkill = s5;
                      if (npcSkill < 30 && npc->isATrader())
                        npcSkill = 40; // Traders should at least provide standard gear
                    }

                    std::string targetGrade = "Standard";
                    std::string targetMana = "Skeleton Smiths";

                    if (npcSkill > 80) {
                      targetGrade =
                          (gd->type == WEAPON) ? "Edge Type 3" : "Masterwork";
                      targetMana = "Cross";
                    } else if (npcSkill > 60) {
                      targetGrade =
                          (gd->type == WEAPON) ? "Edge Type 1" : "Specialist";
                      targetMana = "Skeleton Smiths";
                    } else if (npcSkill > 40) {
                      targetGrade = (gd->type == WEAPON) ? "Mk I" : "High Grade";
                      targetMana = "Skeleton Smiths";
                    } else if (npcSkill < 15) {
                      targetGrade = (gd->type == WEAPON) ? "Rusted Junk" : "Prototype";
                      targetMana = "Unknown";
                    }

                    Log("ACTION_EXEC: Skill " + ToString(npcSkill) +
                        " -> Target Grade: " + targetGrade);

                    GameData *firstMesh = nullptr;
                    GameData *firstMat = nullptr;
                    int bestMeshScore = 0;
                    int bestMatScore = 0;

                    boost::unordered::unordered_map<std::string,
                                                    GameData *>::iterator it;

                    for (it = thisptr->gamedata.gamedataSID.begin();
                         it != thisptr->gamedata.gamedataSID.end(); ++it) {
                      GameData *check = it->second;
                      if (!check)
                        continue;

                      if (needsMesh && (!requiredMeshType ||
                                        check->type == requiredMeshType)) {
                        if (!firstMesh)
                          firstMesh = check;
                        if (check->name.find(targetGrade) != std::string::npos) {
                          meshData = check;
                          bestMeshScore = 2;
                        } else if (bestMeshScore < 1 &&
                                   (check->name.find("Standard") !=
                                        std::string::npos ||
                                    check->name.find("Catun") !=
                                        std::string::npos)) {
                          meshData = check;
                          bestMeshScore = 1;
                        }
                      }

                      if (needsMat && check->type == WEAPON_MANUFACTURER) {
                        if (!firstMat)
                          firstMat = check;
                        if (check->name.find(targetMana) != std::string::npos) {
                          materialData = check;
                          bestMatScore = 2;
                        } else if (bestMatScore < 1 &&
                                   (check->name.find("Skeleton Smiths") !=
                                        std::string::npos ||
                                    check->name.find("Standard") !=
                                        std::string::npos)) {
                          materialData = check;
                          bestMatScore = 1;
                        }
                      }

                      bool meshDone = !needsMesh || bestMeshScore == 2;
                      bool matDone = !needsMat || bestMatScore == 2;
                      if (meshDone && matDone)
                        break;
                    }

                    // Final Fail-safe: If preferred name not found, take the
                    // first one
                    if (needsMesh && !meshData)
                      meshData = firstMesh;
                    if (needsMat && !materialData)
                      materialData = firstMat;
                  }
                }

                Item *item = thisptr->theFactory->createItem(
                    gd, hand(), meshData, materialData, 0, NULL);
                if (item) {
                  item->quantity = 1;
                  item->quality = 1.0f;
                  // Ensure food is full
                  item->chargesLeft = item->originalFullChargeAmount;
                  if (item->chargesLeft <= 0.0f)
                    item->chargesLeft = 1.0f;

                  item->setProperOwner(p->getHandle());
                  item->visible = true;
                  item->isTradeItem = true;

                  if (!item->container && p->container) {
                    item->container = p->container;
                    p->container->addActiveObject(item);
                  }

                  bool success = p->giveItem(item, true, false);
                  if (success) {
                    spawnedCount++;
                    Log("ACTION_EXEC: Successfully spawned and gave " +
                        gd->name + " to " + p->getName());
                  } else {
                    Log("ACTION_EXEC: WARNING: Resolved " + gd->name +
                        " but giveItem failed (inventory full?) for " +
                        p->getName());
                  }
                } else {
                  Log("ACTION_EXEC: ERROR: Resolved " + gd->name +
                      " but Factory failed to createItem! (Mesh: " +
                      (meshData ? meshData->name : "NULL") + ", Mat: " +
                      (materialData ? materialData->name : "NULL") + ")");
                }
              }

              if (spawnedCount > 0) {
                if (p->getInventory()) {
                  p->getInventory()->autoArrange();
                  p->getInventory()->refreshGui();
                }
                thisptr->addPortraitUpdate(p->getHandle());
                thisptr->showPlayerAMessage_withLog(
                    "Received " +
                        (spawnedCount > 1 ? ToString(spawnedCount) + "x "
                                          : "") +
                        (itemName.empty() ? gd->name : itemName),
                    true);
                inventoryTimer = 999;
              }
            } else {
              Log("ACTION_EXEC: No character found to give item to.");
              // No player found — drop item at NPC position as fallback
              Ogre::Vector3 dropPos = (npc && (uintptr_t)npc > 0x1000)
                                          ? npc->getPosition()
                                          : Ogre::Vector3::ZERO;
              dropPos.y += 2.0f; // Raise drop height

              Log("ACTION_EXEC: No player character found, dropping item at "
                  "NPC/Origin.");

              Item *item = thisptr->theFactory->createItem(gd, hand(), NULL,
                                                           NULL, 1, NULL);
              if (item) {
                item->quantity = 1;
                item->activate(true, dropPos, Ogre::Quaternion::IDENTITY, false,
                               YesNoMaybe::NO, true);
                thisptr->showPlayerAMessage_withLog(
                    "Item dropped nearby: " + templateName, true);
              }
            }
          } else {
            Log("ACTION_EXEC: Could not find template for: " + templateName);
            thisptr->showPlayerAMessage(
                "Error: Item template '" + templateName + "' not found.", true);
          }
        }
      }
    } catch (...) {
      Log("ACTION_EXEC: CRITICAL EXCEPTION during action index " +
          ToString((int)actIdx));
    }
  }
}
