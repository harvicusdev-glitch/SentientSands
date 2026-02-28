#include "GameActions.h"
#include "Context.h"
#include "Globals.h"
#include "Utils.h"
#include <algorithm>
#include <core/Functions.h>
#include <kenshi/Character.h>
#include <kenshi/Dialogue.h>
#include <kenshi/Faction.h>
#include <kenshi/FactionRelations.h>
#include <kenshi/GameData.h>
#include <kenshi/GameWorld.h>
#include <kenshi/Inventory.h>
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

void ExecuteQueuedActions(GameWorld *thisptr, int &inventoryTimer) {
  if (TryEnterCriticalSection(&g_uiMutex)) {
    while (!g_uiActionQueue.empty()) {
      QueuedAction act = g_uiActionQueue.front();
      g_uiActionQueue.pop_front();
      LeaveCriticalSection(&g_uiMutex);

      Character *npc = act.actor.getCharacter();
      Character *target = act.target.getCharacter();

      if (act.type == ACT_NOTIFY) {
        thisptr->showPlayerAMessage_withLog(act.message, true);
      } else if (act.type == ACT_SAY && target) {
        bool isPC = target->isPlayerCharacter();
        Log("ACTION_EXEC: SAY [" + target->getName() + "]: " + act.message +
            (isPC ? " (PC)" : " (NPC)"));
        try {
          // If npc is in vanilla dialogue state, bubbles are often suppressed.
          // Force a reset if they seem stuck.
          if (target->dialogue && (uintptr_t)target->dialogue > 0x1000) {
            target->dialogue->endDialogue(true);
            target->dialogue->setInDialog(false);
          }

          // Primary method: sayALine (supports multiple lines/delays)
          target->sayALine(act.message, true);

          // 🚨 FIX: Speech bubbles disappear too fast at high game speeds.
          // Scale the timer by game speed to keep it visible for ~5s real-time.
          // We set both timers to ensure the engine honors our duration.
          if (target->dialogue && (uintptr_t)target->dialogue > 0x1000) {
            float speed = thisptr->getFrameSpeedMultiplier();
            if (speed < 1.0f)
              speed = 1.0f;
            float duration = g_speechBubbleLife * speed;
            target->dialogue->speechTextTimer = duration;
            target->dialogue->speechTextTimer_forced = duration;
          } else {
            // Secondary fallback: say (force floating text bubble)
            // ONLY if dialogue system failed to initialize for this character
            target->say(act.message);
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
          thisptr->player->recruit(npc, false);
          thisptr->playNotification("ui_cat_change");
          thisptr->showPlayerAMessage_withLog(
              npc->getName() + " joined your squad.", true);
        } else if (act.type == ACT_LEAVE) {
          // Clear dialogue state to ensure they don't stay frozen
          if (npc->dialogue && (uintptr_t)npc->dialogue > 0x1000) {
            npc->dialogue->endDialogue(true);
            npc->dialogue->setInDialog(false);
          }

          npc->clearPermajobs();
          npc->clearAllAIGoals();
          PerformLeaveSquad(npc, thisptr, act.message);

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

          // Force end dialogue if they were talking
          if (npc->dialogue && (uintptr_t)npc->dialogue > 0x1000) {
            npc->dialogue->endDialogue(true);
            npc->dialogue->setInDialog(false);
          }

          // Clear limiting orders (Passive/Hold) that might prevent task
          // execution Matches enum values in MessageForB::StandingOrder
          npc->setStandingOrder((MessageForB::StandingOrder)13 /* PASSIVE */,
                                false);
          npc->setStandingOrder((MessageForB::StandingOrder)12 /* HOLD */,
                                false);

          npc->clearAllAIGoals();

          TaskType tt = (TaskType)act.taskValue;
          RootObject *taskTarget = (RootObject *)target;

          // SPECIAL HANDLING: If told to patrol/wander town, ensure use town
          // target not player target
          if (tt == PATROL_TOWN || tt == WANDER_TOWN) {
            TownBase *town = npc->getCurrentTownLocation();
            if (town)
              taskTarget = (RootObject *)town;
          } else if (tt == IDLE || tt == WANDERER || tt == RUN_AWAY) {
            // These tasks shouldn't have the player as a target or they walk
            // into the player
            taskTarget = NULL;
          }

          npc->addJob(tt, taskTarget, true, false, npc->getPosition());
          npc->addGoal(tt, (RootObjectBase *)taskTarget);
          npc->reThinkCurrentAIAction();
          thisptr->showPlayerAMessage(npc->getName() + " updated their goal.",
                                      false);
          thisptr->showPlayerAMessage(npc->getName() + " updated their goal.",
                                      false);
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
          Character *player =
              (thisptr->player && thisptr->player->playerCharacters.size() > 0)
                  ? thisptr->player->playerCharacters[0]
                  : nullptr;
          if (player) {
            std::vector<Item *> pItems;
            GetAllCharacterItems(player, pItems);
            std::string targetName = act.message;
            size_t fnot = targetName.find_first_not_of(" \t\n\r\"'");
            if (fnot != std::string::npos) {
              targetName.erase(0, fnot);
              size_t lnot = targetName.find_last_not_of(" \t\n\r\"'");
              if (lnot != std::string::npos)
                targetName.erase(lnot + 1);
            }
            std::transform(targetName.begin(), targetName.end(),
                           targetName.begin(), ::tolower);

            for (uint32_t i = 0; i < pItems.size(); ++i) {
              std::string itemName = pItems[i]->getName();
              std::transform(itemName.begin(), itemName.end(), itemName.begin(),
                             ::tolower);
              if (itemName.find(targetName) != std::string::npos) {
                Log("ACTION_EXEC: Taking item: " + pItems[i]->getName());
                if (pItems[i]->isEquipped)
                  player->unequipItem(pItems[i]->inventorySection, pItems[i]);
                Inventory *inv = pItems[i]->getInventory();
                if (!inv)
                  inv = player->getInventory();
                Item *detached =
                    inv ? inv->removeItemDontDestroy_returnsItem(
                              pItems[i], pItems[i]->quantity, false)
                        : nullptr;
                npc->giveItem(detached ? detached : pItems[i], true, false);
                thisptr->showPlayerAMessage_withLog(npc->getName() + " took " +
                                                        pItems[i]->getName() +
                                                        " from you.",
                                                    true);
                npc->reThinkCurrentAIAction();
                inventoryTimer = 999;
                break;
              }
            }
          }
        } else if (act.type == ACT_GIVE_ITEM) {
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
          std::transform(targetName.begin(), targetName.end(),
                         targetName.begin(), ::tolower);

          Character *player =
              (thisptr->player && thisptr->player->playerCharacters.size() > 0)
                  ? thisptr->player->playerCharacters[0]
                  : nullptr;
          if (player) {
            for (uint32_t i = 0; i < items.size(); ++i) {
              std::string itemName = items[i]->getName();
              std::transform(itemName.begin(), itemName.end(), itemName.begin(),
                             ::tolower);
              if (itemName.find(targetName) != std::string::npos) {
                Log("ACTION_EXEC: Giving item: " + items[i]->getName());
                if (items[i]->isEquipped)
                  npc->unequipItem(items[i]->inventorySection, items[i]);
                Inventory *inv = items[i]->getInventory();
                if (!inv)
                  inv = npc->getInventory();
                Item *detached = inv ? inv->removeItemDontDestroy_returnsItem(
                                           items[i], items[i]->quantity, false)
                                     : nullptr;
                player->giveItem(detached ? detached : items[i], true, false);
                thisptr->showPlayerAMessage_withLog(
                    npc->getName() + " gave you " + items[i]->getName(), true);
                npc->reThinkCurrentAIAction();
                inventoryTimer = 999;
                break;
              }
            }
          }
        } else if (act.type == ACT_GIVE_CATS && thisptr->player &&
                   thisptr->player->playerCharacters.size() > 0) {
          int npcMoney = npc->getMoney();
          if (npcMoney <= 0 && npc->getOwnerships())
            npcMoney = npc->getOwnerships()->getMoney();
          int amt = (act.taskValue > npcMoney) ? npcMoney : act.taskValue;
          if (amt > 0) {
            thisptr->player->playerCharacters[0]->takeMoney(-amt);
            npc->takeMoney(amt);
            thisptr->showPlayerAMessage_withLog(
                "Gained " + ToString(amt) + " cats.", true);
          }
        } else if (act.type == ACT_TAKE_CATS && thisptr->player &&
                   thisptr->player->playerCharacters.size() > 0) {
          Character *p = thisptr->player->playerCharacters[0];
          int pMoney = p->getMoney();
          int amt = (act.taskValue > pMoney) ? pMoney : act.taskValue;
          if (amt > 0) {
            Log("ACTION_EXEC: Taking " + ToString(amt) + " cats from " +
                p->getName());
            p->takeMoney(amt);
            npc->takeMoney(-amt);
            thisptr->showPlayerAMessage_withLog(
                "Lost " + ToString(amt) + " cats.", true);
          }
        } else if (act.type == ACT_RELEASE && target) {
          Log("ACTION_EXEC: Releasing " + target->getName());

          // 1. Handle carrying: If NPC is carrying the target, drop them.
          if (npc->isCarryingSomething &&
              npc->carryingObject == target->getHandle()) {
            Log("ACTION_EXEC: NPC is carrying target. Dropping.");
            npc->dropCarriedObject(false, false);
            npc->clearAllAIGoals();
            npc->addJob(IDLE, NULL, true, false, npc->getPosition());
            npc->addGoal(IDLE, NULL);
            npc->reThinkCurrentAIAction();
            thisptr->showPlayerAMessage(
                npc->getName() + " put down " + target->getName() + ".", false);
          } else {
            // 2. Handle imprisonment: Use RELEASE_PRISONER and
            // BREAKOUT_PRISONER
            npc->clearAllAIGoals();

            Log("ACTION_EXEC: Setting release/breakout goals for " +
                npc->getName() + " targeting " + target->getName());

            // Add IDLE as the base job so they stop after the order
            npc->addJob(IDLE, NULL, false, false, npc->getPosition());

            // addOrder is more authoritative for interactions
            npc->addOrder(nullptr, RELEASE_PRISONER, (RootObject *)target, true,
                          true, target->getPosition());

            // Add both goals to maximize chance of success
            npc->addGoal(RELEASE_PRISONER, (RootObjectBase *)target);
            npc->addGoal(BREAKOUT_PRISONER, (RootObjectBase *)target);

            npc->reThinkCurrentAIAction();
            thisptr->showPlayerAMessage(npc->getName() + " is releasing " +
                                            target->getName() + "!",
                                        false);
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
          std::string payload = act.message;
          std::string templateName = payload;
          std::string itemName = "";
          std::string itemDesc = "";

          size_t p1 = payload.find("|");
          if (p1 != std::string::npos) {
            templateName = payload.substr(0, p1);
            std::string rest = payload.substr(p1 + 1);
            size_t p2 = rest.find("|");
            if (p2 != std::string::npos) {
              itemName = rest.substr(0, p2);
              itemDesc = rest.substr(p2 + 1);
            } else {
              itemName = rest;
            }
          }

          auto trim = [](std::string &s) {
            size_t first = s.find_first_not_of(" \t\r\n");
            if (first == std::string::npos) {
              s = "";
              return;
            }
            s.erase(0, first);
            s.erase(s.find_last_not_of(" \t\r\n") + 1);
          };
          trim(templateName);
          trim(itemName);
          trim(itemDesc);

          GameData *gd = thisptr->leveldata.getDataByName(templateName, ITEM);
          if (!gd)
            gd = thisptr->gamedata.getDataByName(templateName, ITEM);
          if (gd) {
            Log("ACTION_EXEC: Spawning item " + templateName);
            std::string uniqueID =
                templateName + "_AI_" + ToString((unsigned int)GetTickCount());
            GameData *newGd =
                thisptr->savedata.createNewData(ITEM, uniqueID, gd->name);
            newGd->updateFrom(gd, true);
            Item *item = thisptr->theFactory->createItem(newGd, hand(), NULL,
                                                         NULL, 1, NULL);
            if (item) {
              Character *p = (thisptr->player &&
                              thisptr->player->playerCharacters.size() > 0)
                                 ? thisptr->player->playerCharacters[0]
                                 : nullptr;
              if (p) {
                p->giveItem(item, true, true);
                std::string displayMsg =
                    itemName.empty() ? templateName : itemName;
                thisptr->showPlayerAMessage_withLog("Received " + displayMsg,
                                                    true);
              } else {

                item->activate(true, npc->getPosition(),
                               Ogre::Quaternion::IDENTITY, false,
                               YesNoMaybe::YES, true);
              }
            }
          }
        }

        EnterCriticalSection(&g_uiMutex);
      }
      LeaveCriticalSection(&g_uiMutex);
    }
  }
}
