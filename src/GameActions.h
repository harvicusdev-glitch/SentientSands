#pragma once
#include <string>
#include <windows.h>

class Character;
class GameWorld;

void PerformLeaveSquad(Character *npc, GameWorld *world,
                       const std::string &originFaction);
void ExecuteQueuedActions(GameWorld *thisptr, int &inventoryTimer);
