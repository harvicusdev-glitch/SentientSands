#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include <windows.h>


// Use the actual SDK headers
#include <kenshi/Character.h>
#include <kenshi/GameWorld.h>
#include <kenshi/PlayerInterface.h>
#include <kenshi/util/hand.h>


// Global pointer to GameWorld, exported by KenshiLib.dll
GameWorld **ppWorld = nullptr;

void Log(const std::string &msg) {
  std::ofstream logFile("SentientSands_SDK.log", std::ios::app);
  if (logFile.is_open()) {
    logFile << "[SentientSands] " << msg << std::endl;
  }
  OutputDebugStringA(("[SentientSands] " + msg + "\n").c_str());
}

// Simple HTTP Post using WinHTTP to send data to Python
void PostToPython(const std::string &jsonData) {
  // This is a placeholder for a real WinHTTP implementation
  // For now, let's just log it to prove we have the data
  Log("DATA_PUSH: " + jsonData);
}

DWORD WINAPI MainThread(LPVOID lpParam) {
  Log("Main Thread Started. Waiting for KenshiLib...");

  HMODULE hLib = GetModuleHandleA("KenshiLib.dll");
  while (!hLib) {
    Sleep(500);
    hLib = GetModuleHandleA("KenshiLib.dll");
  }

  // Resolve the exported 'ou' (GameWorld*) pointer
  ppWorld = (GameWorld **)GetProcAddress(hLib, "?ou@@3PEAVGameWorld@@EA");
  if (!ppWorld) {
    Log("CRITICAL: Failed to resolve 'ou' from KenshiLib.dll");
    return 1;
  }

  Log("KenshiLib linked and 'ou' resolved.");

  while (true) {
    Sleep(2000); // Poll every 2 seconds

    GameWorld *world = *ppWorld;
    if (!world)
      continue;

    // 1. Check GUI Display Hand (what you hover over or have open in UI)
    hand &guiHand = world->guiDisplayObject;

    // 2. Check Player Selection
    Character *selectedChar = nullptr;
    if (world->player) {
      selectedChar = world->player->selectedCharacter.getCharacter();
    }

    std::stringstream ss;
    ss << "Poll Result: ";

    if (selectedChar) {
      ss << "SELECTED: " << selectedChar->getName()
         << " (ID: " << selectedChar->getHandle().index << ")";
    } else if (guiHand.isValid()) {
      Character *guiChar = guiHand.getCharacter();
      if (guiChar) {
        ss << "HOVERED: " << guiChar->getName() << " (ID: " << guiHand.index
           << ")";
      } else {
        ss << "GUI_HAND VALID BUT NOT CHAR (Type: " << guiHand.type << ")";
      }
    } else {
      ss << "NO SELECTION";
    }

    std::string result = ss.str();
    Log(result);

    // Push to Python if we have a name
    if (selectedChar || (guiHand.isValid() && guiHand.getCharacter())) {
      // Build a simple JSON-ish string
      std::string name = selectedChar ? selectedChar->getName()
                                      : guiHand.getCharacter()->getName();
      PostToPython("{\"event\": \"selection\", \"name\": \"" + name + "\"}");
    }
  }

  return 0;
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD ul_reason_for_call,
                      LPVOID lpReserved) {
  if (ul_reason_for_call == DLL_PROCESS_ATTACH) {
    CreateThread(NULL, 0, MainThread, NULL, 0, NULL);
  }
  return TRUE;
}
