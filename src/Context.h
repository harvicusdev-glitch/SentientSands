#pragma once
#include <string>
#include <vector>

class Character;
class Item;

void GetAllCharacterItems(Character *npc, std::vector<Item *> &outItems);
std::string GetDetailedContext(Character *npc, const std::string &type = "npc");
std::string GetWorldEventsContext();
std::string GetIdentityFaction(Character *npc);
std::string GetRuntimeIDFor(Character *npc);
std::string GetPersistentIDFor(Character *npc);
std::string GetStorageIDFor(Character *npc);
