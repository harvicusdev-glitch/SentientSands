#pragma once
#include "ChatUIGlobals.h"

namespace SentientSands {
namespace UI {

extern MyGUI::Window *g_launcherWindow;

void CreateLauncherUI();
void CloseLauncherUI();

void OnLauncherLibraryClick(MyGUI::Widget *sender);
void OnLauncherEventsClick(MyGUI::Widget *sender);
void OnLauncherSettingsClick(MyGUI::Widget *sender);
void OnLauncherWindowButtonPressed(MyGUI::Window *sender,
                                   const std::string &name);

} // namespace UI
} // namespace SentientSands
