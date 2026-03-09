#include "LibraryWindow.h"
#include "Comm.h"
#include "Globals.h"
#include "Utils.h"
#include <algorithm>
#include <mygui/MyGUI_Button.h>
#include <mygui/MyGUI_Delegate.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_ListBox.h>
#include <mygui/MyGUI_Window.h>
#include <string>
#include <vector>

namespace SentientSands {
namespace UI {

MyGUI::Window *g_libraryWindow = nullptr;
MyGUI::ListBox *g_libraryList = nullptr;
MyGUI::ListBox *g_libraryText = nullptr;
MyGUI::Button *g_libraryLatestBtn = nullptr;
MyGUI::Button *g_libraryAZBtn = nullptr;
MyGUI::Button *g_libraryFavBtn = nullptr;
MyGUI::Button *g_libraryRegenBtn = nullptr;

std::vector<std::string> g_libraryStorageIds;
std::string g_librarySortMode = "alphabetical";
std::vector<std::string> g_libraryFavorites;

void CloseLibraryUI() {
  if (g_libraryWindow) {
    if (MyGUI::Gui::getInstancePtr())
      MyGUI::Gui::getInstancePtr()->destroyWidget(g_libraryWindow);
    g_libraryWindow = nullptr;
    g_libraryList = nullptr;
    g_libraryText = nullptr;
    g_libraryLatestBtn = nullptr;
    g_libraryAZBtn = nullptr;
    g_libraryFavBtn = nullptr;
    g_libraryRegenBtn = nullptr;
    g_libraryStorageIds.clear();
    g_libraryFavorites.clear();
  }
}

void OnLibrarySortLatest(MyGUI::Widget *sender) {
  g_librarySortMode = "latest";
  CreateThread(NULL, 0, LibraryListThread, NULL, 0, NULL);
}

void OnLibrarySortAZ(MyGUI::Widget *sender) {
  g_librarySortMode = "alphabetical";
  CreateThread(NULL, 0, LibraryListThread, NULL, 0, NULL);
}

void OnLibraryFavoriteClick(MyGUI::Widget *sender) {
  size_t index = g_libraryList->getIndexSelected();
  if (index == MyGUI::ITEM_NONE)
    return;

  std::string sid = g_libraryStorageIds[index];

  // Send favorite toggle task
  LibraryTask *t = new LibraryTask();
  t->npcName = g_libraryList->getItemNameAt(index);
  t->json = "{\"sid\":\"" + EscapeJSON(sid) + "\"}";

  struct FavHelper {
    static DWORD WINAPI ThreadProc(LPVOID lpParam) {
      LibraryTask *lt = (LibraryTask *)lpParam;
      PostToPythonWithResponse(L"/favorite", lt->json);
      delete lt;
      // Refresh list to show favorite on top
      CreateThread(NULL, 0, LibraryListThread, NULL, 0, NULL);
      return 0;
    }
  };

  CreateThread(NULL, 0, FavHelper::ThreadProc, t, 0, NULL);
}

void OnLibraryRegenerateClick(MyGUI::Widget *sender) {
  size_t index = g_libraryList->getIndexSelected();
  if (index == MyGUI::ITEM_NONE)
    return;

  std::string sid = g_libraryStorageIds[index];
  std::string displayName = g_libraryList->getItemNameAt(index).asUTF8();

  if (g_libraryText) {
    g_libraryText->removeAllItems();
    g_libraryText->addItem(T("Regenerating profile for ") + displayName +
                           "...");
    g_libraryText->addItem(T("This may take a moment..."));
  }

  if (g_libraryRegenBtn)
    g_libraryRegenBtn->setEnabled(false);

  LibraryTask *t = new LibraryTask();
  t->npcName = displayName;
  t->json = "{\"sid\":\"" + EscapeJSON(sid) + "\"}";

  struct RegenHelper {
    static DWORD WINAPI ThreadProc(LPVOID lpParam) {
      LibraryTask *lt = (LibraryTask *)lpParam;
      std::string response =
          PostToPythonWithResponse(L"/regenerate_profile", lt->json);

      std::string status = GetJsonValue(response, "status");
      if (status == "ok") {
        // Success: Refresh the history display to show new bio/backstory
        LibraryTask *t2 = new LibraryTask();
        t2->npcName = lt->npcName;
        t2->json = "{\"npc\":\"" + GetJsonValue(lt->json, "sid") + "\"}";
        LibraryHistoryThread(t2);
      } else {
        // Error: Show feedback in the text area
        std::string msg = GetJsonValue(response, "message");
        if (msg.empty())
          msg = "Unknown error during synthesis.";

        std::string pipeMsg = "CMD: SET_LIBRARY_TEXT: [REGEN ERROR]: " + msg;
        EnterCriticalSection(&g_msgMutex);
        g_messageQueue.push_back(pipeMsg);
        LeaveCriticalSection(&g_msgMutex);
      }

      std::string pipeMsg = "CMD: ENABLE_REGEN_BTN:";
      EnterCriticalSection(&g_msgMutex);
      g_messageQueue.push_back(pipeMsg);
      LeaveCriticalSection(&g_msgMutex);

      delete lt;
      return 0;
    }
  };

  CreateThread(NULL, 0, RegenHelper::ThreadProc, t, 0, NULL);
}

void PopulateLibraryUI(const std::string &dataInput) {
  if (!g_libraryList)
    return;

  // Selection restoration
  size_t selIndex = g_libraryList->getIndexSelected();
  std::string selSid = "";
  if (selIndex != MyGUI::ITEM_NONE && selIndex < g_libraryStorageIds.size()) {
    selSid = g_libraryStorageIds[selIndex];
  }

  g_libraryList->removeAllItems();
  g_libraryStorageIds.clear();
  g_libraryFavorites.clear();

  std::string data = dataInput;
  std::string favsPart = "";
  size_t mainPipe = std::string::npos;
  // Manual reverse search for the pipe that opens the favorites section
  for (int i = (int)strlen(data.c_str()) - 1; i >= 0; i--) {
    if (data[i] == '|') {
      if (data.find('[', i) != std::string::npos) {
        mainPipe = (size_t)i;
        break;
      }
    }
  }
  // Check if this pipe is likely the favorites separator (it will be followed
  // by brackets)
  if (mainPipe != std::string::npos &&
      data.find("[", mainPipe) != std::string::npos) {
    favsPart = data.substr(mainPipe + 1);
    data = data.substr(0, mainPipe);
  }

  // Parse favorites list
  if (!favsPart.empty()) {
    size_t cur = 0, next;
    while ((next = favsPart.find("\"", cur)) != std::string::npos) {
      size_t end = favsPart.find("\"", next + 1);
      if (end == std::string::npos)
        break;
      g_libraryFavorites.push_back(favsPart.substr(next + 1, end - next - 1));
      cur = end + 1;
    }
  }

  // Clean brackets/quotes if present from characters part
  if (!data.empty() && data[0] == '[')
    data = data.substr(1);
  if (!data.empty() && data[data.length() - 1] == ']')
    data = data.substr(0, data.length() - 1);

  auto trim = [](std::string &s) {
    s.erase(0, s.find_first_not_of(" \t\r\n"));
    s.erase(s.find_last_not_of(" \t\r\n") + 1);
  };

  if (!data.empty()) {
    size_t cur = 0, next;
    while ((next = data.find(",", cur)) != std::string::npos) {
      std::string entry = data.substr(cur, next - cur);
      trim(entry);
      if (!entry.empty()) {
        if (entry[0] == '"')
          entry = entry.substr(1);
        if (entry[entry.length() - 1] == '"')
          entry = entry.substr(0, entry.length() - 1);

        size_t pipePos = entry.find("|");
        std::string sid = entry;
        std::string display = entry;
        if (pipePos != std::string::npos) {
          display = entry.substr(0, pipePos);
          sid = entry.substr(pipePos + 1);
        }

        // Add star to favorite display
        bool isFav = false;
        for (size_t f = 0; f < g_libraryFavorites.size(); f++) {
          if (g_libraryFavorites[f] == sid) {
            isFav = true;
            break;
          }
        }

        g_libraryList->addItem(
            Utf8ToWide(isFav ? "[*] " + display : display).c_str());
        g_libraryStorageIds.push_back(sid);
      }
      cur = next + 1;
    }
    std::string last = data.substr(cur);
    trim(last);
    if (!last.empty()) {
      if (last[0] == '"')
        last = last.substr(1);
      if (last[last.length() - 1] == '"')
        last = last.substr(0, last.length() - 1);

      size_t pipePos = last.find("|");
      std::string sid = last;
      std::string display = last;
      if (pipePos != std::string::npos) {
        display = last.substr(0, pipePos);
        sid = last.substr(pipePos + 1);
      }

      bool isFav = false;
      for (size_t f = 0; f < g_libraryFavorites.size(); f++) {
        if (g_libraryFavorites[f] == sid) {
          isFav = true;
          break;
        }
      }

      g_libraryList->addItem(
          Utf8ToWide(isFav ? "[*] " + display : display).c_str());
      g_libraryStorageIds.push_back(sid);
    }
  }

  // Restore selection
  if (!selSid.empty()) {
    for (size_t i = 0; i < g_libraryStorageIds.size(); i++) {
      if (g_libraryStorageIds[i] == selSid) {
        g_libraryList->setIndexSelected(i);
        break;
      }
    }
  }
}

void SetLibraryText(const std::string &data) {
  if (!g_libraryText)
    return;
  Log("LIBRARY_TEXT: Received " + ToString((int)data.length()) + " bytes");
  size_t start = (data.length() > 0 && data[0] == ' ') ? 1 : 0;
  std::stringstream ss(data.substr(start));
  std::string line;
  g_libraryText->removeAllItems();
  while (std::getline(ss, line)) {
    g_libraryText->addItem(Utf8ToWide(line).c_str());
  }
}

void OnLibraryNPCSelect(MyGUI::ListBox *sender, size_t index) {
  if (index == MyGUI::ITEM_NONE)
    return;
  std::string displayName = sender->getItemNameAt(index);

  // Use storage_id for file lookup if available, otherwise fall back to display
  // name
  std::string storageId = displayName;
  if (index < g_libraryStorageIds.size()) {
    storageId = g_libraryStorageIds[index];
  }

  // Update favorite button state
  if (g_libraryFavBtn) {
    bool isFav = false;
    for (size_t f = 0; f < g_libraryFavorites.size(); f++) {
      if (g_libraryFavorites[f] == storageId) {
        isFav = true;
        break;
      }
    }
    g_libraryFavBtn->setCaption(
        Utf8ToWide(isFav ? T("Fav: [YES]") : T("Fav: [NO]")).c_str());
  }

  // Show loading indicator
  if (g_libraryText) {
    g_libraryText->removeAllItems();
    g_libraryText->addItem(
        Utf8ToWide(T("Loading profile for ") + displayName + "...").c_str());
  }

  // Fetch history using storage_id for reliable file lookup
  LibraryTask *t = new LibraryTask();
  t->npcName = displayName;
  t->json = "{\"npc\":\"" + EscapeJSON(storageId) + "\"}";
  CreateThread(NULL, 0, LibraryHistoryThread, t, 0, NULL);
}

void OnLibraryWindowButtonPressed(MyGUI::Window *sender,
                                  const std::string &name) {
  if (name == "close")
    CloseLibraryUI();
}

DWORD WINAPI LibraryListThread(LPVOID lpParam) {
  Log("LIBRARY_THREAD: Fetching characters (Sort: " + g_librarySortMode +
      ")...");
  std::string json = "{\"sort\":\"" + g_librarySortMode + "\"}";
  std::string response = PostToPythonWithResponse(L"/characters", json);
  if (!response.empty()) {
    std::string chars = GetJsonValue(response, "names");
    if (chars.empty())
      chars = GetJsonValue(response, "characters");

    if (!chars.empty()) {
      std::string favs = GetJsonValue(response, "favorites");
      std::string pipeMsg = "CMD: POPULATE_LIBRARY: " + chars + "|" + favs;
      EnterCriticalSection(&g_msgMutex);
      g_messageQueue.push_back(pipeMsg);
      LeaveCriticalSection(&g_msgMutex);
    }
  }
  return 0;
}

DWORD WINAPI LibraryHistoryThread(LPVOID lpParam) {
  LibraryTask *t = (LibraryTask *)lpParam;
  Log("LIBRARY_THREAD: Fetching history for " + t->npcName);
  std::string response = PostToPythonWithResponse(L"/history", t->json);
  if (!response.empty()) {
    std::string content = GetJsonValue(response, "text");
    if (!content.empty()) {
      std::string pipeMsg = "CMD: SET_LIBRARY_TEXT: " + content;
      EnterCriticalSection(&g_msgMutex);
      g_messageQueue.push_back(pipeMsg);
      LeaveCriticalSection(&g_msgMutex);
    }
  }
  delete t;
  return 0;
}

void CreateLibraryUI() {
  MyGUI::Gui *gui = MyGUI::Gui::getInstancePtr();
  if (!gui)
    return;
  if (g_libraryWindow)
    CloseLibraryUI();

  g_libraryWindow = gui->createWidgetReal<MyGUI::Window>(
      "Kenshi_WindowCX", 0.15f, 0.1f, 0.7f, 0.8f, MyGUI::Align::Center, "Popup",
      "SentientSands_LibraryWindow");
  g_libraryWindow->setCaption(
      Utf8ToWide(T("AI Dialogue Library & Logs")).c_str());
  g_libraryWindow->eventWindowButtonPressed +=
      MyGUI::newDelegate(OnLibraryWindowButtonPressed);

  MyGUI::Widget *client = g_libraryWindow->getClientWidget();

  // Sorting/Favorite Buttons
  g_libraryLatestBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.02f, 0.015f, 0.09f, 0.05f, MyGUI::Align::Left,
      "SentientSands_LibLatestBtn");
  g_libraryLatestBtn->setCaption(Utf8ToWide(T("Latest")).c_str());
  g_libraryLatestBtn->eventMouseButtonClick +=
      MyGUI::newDelegate(OnLibrarySortLatest);

  g_libraryAZBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.115f, 0.015f, 0.08f, 0.05f, MyGUI::Align::Left,
      "SentientSands_LibAZBtn");
  g_libraryAZBtn->setCaption(Utf8ToWide(T("A-Z")).c_str());
  g_libraryAZBtn->eventMouseButtonClick += MyGUI::newDelegate(OnLibrarySortAZ);

  g_libraryFavBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.20f, 0.015f, 0.1f, 0.05f, MyGUI::Align::Left,
      "SentientSands_LibFavBtn");
  g_libraryFavBtn->setCaption(Utf8ToWide(T("Fav Toggle")).c_str());
  g_libraryFavBtn->eventMouseButtonClick +=
      MyGUI::newDelegate(OnLibraryFavoriteClick);

  // NPC List (Left 30%) - Moved down to y=0.07f
  g_libraryList = client->createWidgetReal<MyGUI::ListBox>(
      "Kenshi_ListBox", 0.02f, 0.07f, 0.28f, 0.91f,
      MyGUI::Align::Left | MyGUI::Align::VStretch, "SentientSands_LibraryList");
  g_libraryList->eventListSelectAccept +=
      MyGUI::newDelegate(OnLibraryNPCSelect);
  g_libraryList->eventListChangePosition +=
      MyGUI::newDelegate(OnLibraryNPCSelect);

  g_libraryRegenBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.305f, 0.015f, 0.11f, 0.05f, MyGUI::Align::Left,
      "SentientSands_LibRegenBtn");
  g_libraryRegenBtn->setCaption(Utf8ToWide(T("Regen Bio")).c_str());
  g_libraryRegenBtn->eventMouseButtonClick +=
      MyGUI::newDelegate(OnLibraryRegenerateClick);

  // Log View (Right 70%) - Moved down to y=0.07f to avoid covering buttons
  g_libraryText = client->createWidgetReal<MyGUI::ListBox>(
      "Kenshi_ListBox", 0.32f, 0.07f, 0.66f, 0.91f, MyGUI::Align::Default,
      "SentientSands_LibraryText");
  g_libraryText->addItem(
      Utf8ToWide(
          T("Select an NPC from the list to view their raw profile data."))
          .c_str());

  // Fetch character list
  CreateThread(NULL, 0, LibraryListThread, NULL, 0, NULL);
}

} // namespace UI
} // namespace SentientSands
