#pragma once
#include "ChatUIGlobals.h"

namespace SentientSands {
namespace UI {

extern MyGUI::Window *g_welcomeWindow;

void CreateWelcomeUI();
void CloseWelcomeUI();
void OnWelcomeSaveClick(MyGUI::Widget *sender);
void OnWelcomeDiscordClick(MyGUI::Widget *sender);
void OnWelcomeWindowButtonPressed(MyGUI::Window *sender,
                                  const std::string &name);
DWORD WINAPI WelcomeResponseThread(LPVOID lpParam);

} // namespace UI
} // namespace SentientSands
