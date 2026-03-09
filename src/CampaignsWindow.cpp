#include "CampaignsWindow.h"
#include "Comm.h"
#include "Globals.h"
#include "Utils.h"

#include <mygui/MyGUI_Button.h>
#include <mygui/MyGUI_ComboBox.h>
#include <mygui/MyGUI_Delegate.h>
#include <mygui/MyGUI_EditBox.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_TextBox.h>
#include <mygui/MyGUI_Window.h>

namespace SentientSands {
namespace UI {

static bool g_cullConfirmed = false;

void CloseCampaignsUI() {
  if (g_campaignWindow) {
    if (MyGUI::Gui::getInstancePtr())
      MyGUI::Gui::getInstancePtr()->destroyWidget(g_campaignWindow);
    g_campaignWindow = nullptr;
    g_campaignList = nullptr;
    g_campaignNewName = nullptr;
    g_campaignStatus = nullptr;
    g_campaignActiveLabel = nullptr;
    g_cullConfirmed = false;
  }
}

DWORD WINAPI CampaignsResponseThread(LPVOID lpParam);

void OnCampaignWindowButtonPressed(MyGUI::Window *sender,
                                   const std::string &name) {
  if (name == "close")
    CloseCampaignsUI();
}

void OnCampaignCreateClick(MyGUI::Widget *sender) {
  if (!g_campaignNewName || !g_campaignStatus)
    return;
  std::string name = g_campaignNewName->getCaption();
  if (name.empty()) {
    g_campaignStatus->setCaption(
        Utf8ToWide(T("Error: Name cannot be empty.")).c_str());
    g_campaignStatus->setTextColour(MyGUI::Colour(1.0f, 0.4f, 0.4f));
    return;
  }

  g_campaignStatus->setCaption(Utf8ToWide(T("Creating Campaign...")).c_str());
  g_campaignStatus->setTextColour(MyGUI::Colour(0.9f, 0.9f, 0.9f));

  // Request creation
  std::string json = "{\"name\": \"" + name + "\"}";
  std::string response = PostToPythonWithResponse(L"/campaigns/create", json);

  if (response.find("\"status\":\"ok\"") != std::string::npos) {
    g_campaignStatus->setCaption(
        Utf8ToWide(T("Campaign Created! Switching...")).c_str());
    g_campaignStatus->setTextColour(MyGUI::Colour(0.4f, 1.0f, 0.4f));
    // Re-fetch to update list and active campaign UI
    CreateThread(NULL, 0, CampaignsResponseThread, NULL, 0, NULL);
    g_campaignNewName->setCaption("");
  } else {
    g_campaignStatus->setCaption(
        Utf8ToWide(T("Failed to create campaign.")).c_str());
    g_campaignStatus->setTextColour(MyGUI::Colour(1.0f, 0.4f, 0.4f));
  }
}

void OnCampaignSwitchClick(MyGUI::Widget *sender) {
  if (!g_campaignList || !g_campaignStatus)
    return;
  size_t idx = g_campaignList->getIndexSelected();
  if (idx == MyGUI::ITEM_NONE)
    return;

  std::string name = g_campaignList->getItemNameAt(idx);
  g_campaignStatus->setCaption(
      Utf8ToWide(T("Switching to ") + name + "...").c_str());
  g_campaignStatus->setTextColour(MyGUI::Colour(0.9f, 0.9f, 0.9f));

  std::string json = "{\"name\": \"" + name + "\"}";
  std::string response = PostToPythonWithResponse(L"/campaigns/switch", json);

  if (response.find("\"status\":\"ok\"") != std::string::npos) {
    g_campaignStatus->setCaption(Utf8ToWide(T("Switched to ") + name).c_str());
    g_campaignStatus->setTextColour(MyGUI::Colour(0.4f, 1.0f, 0.4f));
    // Trigger world reload on server and update local UI status
    CreateThread(NULL, 0, CampaignsResponseThread, NULL, 0, NULL);
  } else {
    g_campaignStatus->setCaption(
        Utf8ToWide(T("Failed to switch campaign.")).c_str());
    g_campaignStatus->setTextColour(MyGUI::Colour(1.0f, 0.4f, 0.4f));
  }
}

void OnCampaignCullClick(MyGUI::Widget *sender) {
  if (!g_campaignStatus)
    return;
  MyGUI::Button *btn = static_cast<MyGUI::Button *>(sender);

  if (!g_cullConfirmed) {
    btn->setCaption(Utf8ToWide(T("CONFIRM CULL?")).c_str());
    btn->setTextColour(MyGUI::Colour(1.0f, 0.4f, 0.4f));
    g_cullConfirmed = true;
    g_campaignStatus->setCaption(
        Utf8ToWide(T("DANGER: This deletes all data after the current in-game "
                     "minute!"))
            .c_str());
    return;
  }

  // Reset state
  g_cullConfirmed = false;
  btn->setCaption(Utf8ToWide(T("CULL")).c_str());
  btn->setTextColour(MyGUI::Colour::White);

  g_campaignStatus->setCaption(Utf8ToWide(T("Culling future data...")).c_str());
  g_campaignStatus->setTextColour(MyGUI::Colour(0.9f, 0.9f, 0.9f));

  std::string response = PostToPythonWithResponse(L"/campaigns/cull", "{}");

  if (response.find("\"status\":\"ok\"") != std::string::npos) {
    g_campaignStatus->setCaption(
        Utf8ToWide(T("Cull complete. Data after current minute deleted."))
            .c_str());
    g_campaignStatus->setTextColour(MyGUI::Colour(0.4f, 1.0f, 0.4f));
  } else {
    g_campaignStatus->setCaption(
        Utf8ToWide(T("Cull failed. Check server logs.")).c_str());
    g_campaignStatus->setTextColour(MyGUI::Colour(1.0f, 0.4f, 0.4f));
  }
}

DWORD WINAPI CampaignsResponseThread(LPVOID lpParam) {
  std::string response = PostToPythonWithResponse(L"/settings", "");
  if (response.empty())
    return 0;

  std::string pipeMsg = "CMD: POPULATE_CAMPAIGNS: " + response;
  EnterCriticalSection(&g_msgMutex);
  g_messageQueue.push_back(pipeMsg);
  LeaveCriticalSection(&g_msgMutex);
  return 0;
}

void CreateCampaignsUI() {
  MyGUI::Gui *gui = MyGUI::Gui::getInstancePtr();
  if (!gui)
    return;
  if (g_campaignWindow)
    CloseCampaignsUI();

  g_campaignWindow = gui->createWidgetReal<MyGUI::Window>(
      "Kenshi_WindowCX", 0.35f, 0.2f, 0.3f, 0.5f, MyGUI::Align::Center,
      "Overlapped", "SentientSands_CampaignWindow");
  g_campaignWindow->setCaption(Utf8ToWide(T("Campaign Management")).c_str());
  g_campaignWindow->eventWindowButtonPressed +=
      MyGUI::newDelegate(OnCampaignWindowButtonPressed);

  MyGUI::Widget *client = g_campaignWindow->getClientWidget();

  // Active Campaign (Always visible)
  g_campaignActiveLabel = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", 0.05f, 0.02f, 0.9f, 0.08f,
      MyGUI::Align::Top, "SentientSands_CampActiveLabel");
  g_campaignActiveLabel->setCaption(
      Utf8ToWide(T("Active Campaign: ") + T("None")).c_str());
  g_campaignActiveLabel->setTextColour(MyGUI::Colour(1.0f, 0.8f, 0.4f));

  // Existing Campaigns
  MyGUI::TextBox *label = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", 0.05f, 0.10f, 0.9f, 0.08f,
      MyGUI::Align::Top, "SentientSands_CampLabel");
  label->setCaption(Utf8ToWide(T("Select Campaign:")).c_str());

  g_campaignList = client->createWidgetReal<MyGUI::ComboBox>(
      "Kenshi_ComboBox", 0.05f, 0.18f, 0.65f, 0.1f, MyGUI::Align::Top,
      "SentientSands_CampList");
  g_campaignList->setComboModeDrop(true);

  MyGUI::Button *switchBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.72f, 0.18f, 0.23f, 0.1f, MyGUI::Align::Top,
      "SentientSands_CampSwitchBtn");
  switchBtn->setCaption(Utf8ToWide(T("LOAD")).c_str());
  switchBtn->eventMouseButtonClick += MyGUI::newDelegate(OnCampaignSwitchClick);

  // New Campaign
  MyGUI::TextBox *nLabel = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", 0.05f, 0.34f, 0.9f, 0.08f,
      MyGUI::Align::Top, "SentientSands_CampNewLabel");
  nLabel->setCaption(Utf8ToWide(T("Create New Campaign:")).c_str());

  g_campaignNewName = client->createWidgetReal<MyGUI::EditBox>(
      "Kenshi_EditBox", 0.05f, 0.42f, 0.65f, 0.1f, MyGUI::Align::Top,
      "SentientSands_CampNewName");

  MyGUI::Button *createBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.72f, 0.42f, 0.23f, 0.1f, MyGUI::Align::Top,
      "SentientSands_CampCreateBtn");
  createBtn->setCaption(Utf8ToWide(T("NEW")).c_str());
  createBtn->eventMouseButtonClick += MyGUI::newDelegate(OnCampaignCreateClick);

  // Cull Button (Dangerous)
  MyGUI::TextBox *cullDesc = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", 0.05f, 0.54f, 0.9f, 0.08f,
      MyGUI::Align::Top, "SentientSands_CampCullDesc");
  cullDesc->setCaption(
      Utf8ToWide(T("Loaded an old save? Cull deletes AI memories after "
                   "the current in-game minute:"))
          .c_str());
  cullDesc->setTextColour(MyGUI::Colour(0.8f, 0.8f, 0.8f));

  MyGUI::Button *cullBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.05f, 0.62f, 0.9f, 0.08f, MyGUI::Align::Top,
      "SentientSands_CampCullBtn");
  cullBtn->setCaption(Utf8ToWide(T("CULL FUTURE DATA")).c_str());
  cullBtn->eventMouseButtonClick += MyGUI::newDelegate(OnCampaignCullClick);

  // Status
  g_campaignStatus = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", 0.05f, 0.74f, 0.9f, 0.2f, MyGUI::Align::Top,
      "SentientSands_CampStatus");
  g_campaignStatus->setCaption(Utf8ToWide(T("Fetching campaigns...")).c_str());
  g_campaignStatus->setTextAlign(MyGUI::Align::Center);

  // Initial fetch — also populates the active campaign display
  CreateThread(NULL, 0, CampaignsResponseThread, NULL, 0, NULL);
}

void PopulateCampaignsUI(const std::string &json) {
  if (!g_campaignList)
    return;

  std::string currentCampaign = GetJsonValue(json, "current_campaign");
  std::string campList = GetJsonValue(json, "campaigns");

  g_campaignList->removeAllItems();

  size_t start = campList.find("[");
  size_t end = campList.find("]");
  if (start != std::string::npos && end != std::string::npos) {
    std::string list = campList.substr(start + 1, end - start - 1);
    size_t cur = 0, next;
    while ((next = list.find(",", cur)) != std::string::npos) {
      std::string item = list.substr(cur, next - cur);
      size_t q1 = item.find("\"");
      size_t q2 = item.find("\"", q1 + 1);
      if (q1 != std::string::npos && q2 != std::string::npos)
        g_campaignList->addItem(
            Utf8ToWide(item.substr(q1 + 1, q2 - q1 - 1)).c_str());
      cur = next + 1;
    }
    std::string last = list.substr(cur);
    size_t q1 = last.find("\"");
    size_t q2 = last.find("\"", q1 + 1);
    if (q1 != std::string::npos && q2 != std::string::npos)
      g_campaignList->addItem(
          Utf8ToWide(last.substr(q1 + 1, q2 - q1 - 1)).c_str());
  }

  // Select Current
  if (!currentCampaign.empty()) {
    for (size_t i = 0; i < g_campaignList->getItemCount(); ++i) {
      if (g_campaignList->getItemNameAt(i) == currentCampaign) {
        g_campaignList->setIndexSelected(i);
        break;
      }
    }
    if (g_campaignActiveLabel)
      g_campaignActiveLabel->setCaption(
          Utf8ToWide(T("Active Campaign: ") + currentCampaign).c_str());
  } else if (g_campaignList->getItemCount() > 0) {
    g_campaignList->setIndexSelected(0);
  }
}

} // namespace UI
} // namespace SentientSands
