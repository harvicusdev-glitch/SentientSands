#pragma once
#include "ChatUIGlobals.h"

namespace SentientSands {
namespace UI {

extern MyGUI::Window *g_settingsWindow;
extern MyGUI::ComboBox *g_settingsProvider;
extern MyGUI::ComboBox *g_settingsModel;
extern MyGUI::EditBox *g_settingsRadii[3];
extern MyGUI::EditBox *g_settingsEventsCount;
extern MyGUI::Button *g_settingsAmbientToggle;
extern MyGUI::ComboBox *g_settingsCampaign;
extern MyGUI::EditBox *g_settingsNewCampaignName;
extern MyGUI::ComboBox *g_settingsHotkey;
extern MyGUI::ComboBox *g_settingsLanguage;

void CreateSettingsUI();
void CloseSettingsUI();
void PopulateSettingsUI(const std::string &json);

void OnSettingsProviderChange(MyGUI::ComboBox *sender, size_t index);
void OnSettingsSaveClick(MyGUI::Widget *sender);
void OnSettingsTestClick(MyGUI::Widget *sender);
void OnSettingsRestartClick(MyGUI::Widget *sender);
void OnSettingsAmbientToggleClick(MyGUI::Widget *sender);
void OnSettingsWindowButtonPressed(MyGUI::Window *sender,
                                   const std::string &name);
DWORD WINAPI SettingsResponseThread(LPVOID lpParam);

} // namespace UI
} // namespace SentientSands
