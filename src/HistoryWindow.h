#pragma once
#include "ChatUIGlobals.h"

namespace SentientSands {
namespace UI {

extern MyGUI::Window *g_historyWindow;
extern MyGUI::ListBox *g_historyText;

void CreateHistoryUI(const std::string &npcName, const std::string &content);
void CloseHistoryUI();

DWORD WINAPI HistoryResponseThread(LPVOID lpParam);
void OnHistoryCloseClick(MyGUI::Widget *sender);
void OnHistoryWindowButtonPressed(MyGUI::Window *sender,
                                  const std::string &name);

} // namespace UI
} // namespace SentientSands
