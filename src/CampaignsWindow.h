#pragma once
#include "ChatUIGlobals.h"

namespace SentientSands {
namespace UI {

extern MyGUI::Window *g_campaignWindow;

void CreateCampaignsUI();
void CloseCampaignsUI();
void PopulateCampaignsUI(const std::string &json);

void OnCampaignCreateClick(MyGUI::Widget *sender);
void OnCampaignSwitchClick(MyGUI::Widget *sender);
void OnCampaignWindowButtonPressed(MyGUI::Window *sender,
                                   const std::string &name);

} // namespace UI
} // namespace SentientSands
