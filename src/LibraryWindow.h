#pragma once
#include "ChatUIGlobals.h"

namespace SentientSands {
namespace UI {

extern MyGUI::Window *g_libraryWindow;
extern MyGUI::ListBox *g_libraryList;
extern MyGUI::ListBox *g_libraryText;
extern MyGUI::Button *g_libraryRegenBtn;
extern std::vector<std::string> g_libraryStorageIds;

void CreateLibraryUI();
void CloseLibraryUI();
void PopulateLibraryUI(const std::string &data);
void SetLibraryText(const std::string &data);

void OnLibraryNPCSelect(MyGUI::ListBox *sender, size_t index);
void OnLibraryWindowButtonPressed(MyGUI::Window *sender,
                                  const std::string &name);
DWORD WINAPI LibraryListThread(LPVOID lpParam);
DWORD WINAPI LibraryHistoryThread(LPVOID lpParam);

} // namespace UI
} // namespace SentientSands
