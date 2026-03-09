#include "ProfileEditorWindow.h"
#include "ChatUIGlobals.h"
#include "Comm.h"
#include "Globals.h"
#include "Utils.h"
#include <mygui/MyGUI_Button.h>
#include <mygui/MyGUI_Delegate.h>
#include <mygui/MyGUI_EditBox.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_ListBox.h>
#include <mygui/MyGUI_TextBox.h>
#include <mygui/MyGUI_Window.h>
#include <sstream>

namespace SentientSands {
namespace UI {

MyGUI::Window *g_profileEditorWindow = nullptr;
MyGUI::EditBox *g_profileBioEdit = nullptr;
MyGUI::EditBox *g_profileFactionEdit = nullptr;
MyGUI::ListBox *g_profileBioView = nullptr;
MyGUI::ListBox *g_profileFactionView = nullptr;

void CloseProfileEditorUI() {
  if (g_profileEditorWindow) {
    if (MyGUI::Gui::getInstancePtr())
      MyGUI::Gui::getInstancePtr()->destroyWidget(g_profileEditorWindow);
    g_profileEditorWindow = nullptr;
    g_profileBioEdit = nullptr;
    g_profileFactionEdit = nullptr;
    g_profileBioView = nullptr;
    g_profileFactionView = nullptr;
  }
}

static void OnProfileEditorWindowButtonPressed(MyGUI::Window *sender,
                                               const std::string &button) {
  if (button == "close") {
    CloseProfileEditorUI();
  }
}

static std::string JsonEscape(const std::string &s) {
  std::string res = "";
  for (size_t i = 0; i < s.length(); ++i) {
    char c = s[i];
    if (c == '"')
      res += "\\\"";
    else if (c == '\\')
      res += "\\\\";
    else if (c == '\n')
      res += "\\n";
    else if (c == '\r')
      res += "\\r";
    else
      res += c;
  }
  return res;
}

DWORD WINAPI ProfileEditorResponseThread(LPVOID lpParam) {
  std::string response = PostToPythonWithResponse(L"/player_profile", "");
  if (!response.empty()) {
    std::string pipeMsg = "CMD: POPULATE_PROFILE: " + response;
    EnterCriticalSection(&g_msgMutex);
    g_messageQueue.push_back(pipeMsg);
    LeaveCriticalSection(&g_msgMutex);
  }
  return 0;
}

struct ProfileSaveTask {
  std::string json;
};

DWORD WINAPI ProfileSaveThread(LPVOID lpParam) {
  ProfileSaveTask *task = (ProfileSaveTask *)lpParam;
  PostToPythonWithResponse(L"/player_profile", task->json);
  delete task;

  // Re-fetch to update the previews
  CreateThread(NULL, 0, ProfileEditorResponseThread, NULL, 0, NULL);
  return 0;
}

static void OnProfileSaveClick(MyGUI::Widget *sender) {
  if (!g_profileBioEdit || !g_profileFactionEdit)
    return;

  std::string bio = g_profileBioEdit->getCaption().asUTF8();
  std::string faction = g_profileFactionEdit->getCaption().asUTF8();

  std::string json = "{";
  json += "\"character_bio\": \"";
  json += JsonEscape(bio);
  json += "\",";
  json += "\"player_faction\": \"";
  json += JsonEscape(faction);
  json += "\"";
  json += "}";

  ProfileSaveTask *task = new ProfileSaveTask();
  task->json = json;
  CreateThread(NULL, 0, ProfileSaveThread, task, 0, NULL);
}

void CreateProfileEditorUI() {
  MyGUI::Gui *gui = MyGUI::Gui::getInstancePtr();
  if (!gui)
    return;
  if (g_profileEditorWindow)
    CloseProfileEditorUI();

  // Shrunk window height from 0.85f to 0.65f to eliminate dead space
  g_profileEditorWindow = gui->createWidgetReal<MyGUI::Window>(
      "Kenshi_WindowCX", 0.20f, 0.15f, 0.60f, 0.65f, MyGUI::Align::Center,
      "Popup", "SentientSands_ProfileEditorWindow");
  g_profileEditorWindow->setCaption(
      Utf8ToWide(T("PLAYER & FACTION PROFILES")).c_str());
  g_profileEditorWindow->eventWindowButtonPressed +=
      MyGUI::newDelegate(OnProfileEditorWindowButtonPressed);

  MyGUI::Widget *client = g_profileEditorWindow->getClientWidget();

  float y = 0.02f;

  // --- Character Bio Section ---
  client
      ->createWidgetReal<MyGUI::TextBox>(
          "Kenshi_TextboxStandardText", 0.05f, y, 0.9f, 0.04f,
          MyGUI::Align::Top | MyGUI::Align::HStretch, "Label1")
      ->setCaption(
          Utf8ToWide(T("CURRENT Character Backstory (Preview):")).c_str());
  y += 0.05f;

  g_profileBioView = client->createWidgetReal<MyGUI::ListBox>(
      "Kenshi_ListBox", 0.05f, y, 0.9f, 0.20f,
      MyGUI::Align::Top | MyGUI::Align::HStretch, "BioView");
  g_profileBioView->setNeedKeyFocus(false);
  y += 0.21f;

  client
      ->createWidgetReal<MyGUI::TextBox>(
          "Kenshi_TextboxStandardText", 0.05f, y, 0.9f, 0.04f,
          MyGUI::Align::Top | MyGUI::Align::HStretch, "EditLabel1")
      ->setCaption(
          Utf8ToWide(T("INPUT NEW Character Backstory (Paste to overwrite):"))
              .c_str());
  y += 0.05f;

  g_profileBioEdit = client->createWidgetReal<MyGUI::EditBox>(
      "Kenshi_EditBox", 0.05f, y, 0.9f, 0.08f,
      MyGUI::Align::Top | MyGUI::Align::HStretch, "BioEdit");
  g_profileBioEdit->setEditMultiLine(true);
  g_profileBioEdit->setEditWordWrap(true);
  g_profileBioEdit->setFontHeight(15);
  g_profileBioEdit->setTextColour(MyGUI::Colour::White);
  y += 0.10f;

  // --- Faction Description Section ---
  client
      ->createWidgetReal<MyGUI::TextBox>(
          "Kenshi_TextboxStandardText", 0.05f, y, 0.9f, 0.04f,
          MyGUI::Align::Top | MyGUI::Align::HStretch, "Label2")
      ->setCaption(
          Utf8ToWide(T("CURRENT Faction Description (Preview):")).c_str());
  y += 0.05f;

  g_profileFactionView = client->createWidgetReal<MyGUI::ListBox>(
      "Kenshi_ListBox", 0.05f, y, 0.9f, 0.15f,
      MyGUI::Align::Top | MyGUI::Align::HStretch, "FactionView");
  g_profileFactionView->setNeedKeyFocus(false);
  y += 0.16f;

  client
      ->createWidgetReal<MyGUI::TextBox>(
          "Kenshi_TextboxStandardText", 0.05f, y, 0.9f, 0.04f,
          MyGUI::Align::Top | MyGUI::Align::HStretch, "EditLabel2")
      ->setCaption(
          Utf8ToWide(T("INPUT NEW Faction Description (Paste to overwrite):"))
              .c_str());
  y += 0.05f;

  g_profileFactionEdit = client->createWidgetReal<MyGUI::EditBox>(
      "Kenshi_EditBox", 0.05f, y, 0.9f, 0.08f,
      MyGUI::Align::Top | MyGUI::Align::HStretch, "FactionEdit");
  g_profileFactionEdit->setEditMultiLine(true);
  g_profileFactionEdit->setEditWordWrap(true);
  g_profileFactionEdit->setFontHeight(15);
  g_profileFactionEdit->setTextColour(MyGUI::Colour::White);
  y += 0.08f;

  // Save Button: Moved up to 0.88f to close the gap
  MyGUI::Button *saveBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.35f, 0.88f, 0.3f, 0.07f, MyGUI::Align::Bottom,
      "SaveBtn");
  saveBtn->setCaption(Utf8ToWide(T("SAVE CHANGES")).c_str());
  saveBtn->eventMouseButtonClick += MyGUI::newDelegate(OnProfileSaveClick);

  // Fetch data
  CreateThread(NULL, 0, ProfileEditorResponseThread, NULL, 0, NULL);
}

void PopulateProfileEditorUI(const std::string &json) {
  Log("POPULATE_PROFILE: Received JSON: " + json);
  if (!g_profileEditorWindow)
    return;

  std::string bio = GetJsonValue(json, "character_bio");
  std::string faction = GetJsonValue(json, "player_faction");

  if (g_profileBioView) {
    g_profileBioView->removeAllItems();
    std::stringstream ss(bio);
    std::string line;
    while (std::getline(ss, line))
      g_profileBioView->addItem(Utf8ToWide(line).c_str());
    g_profileBioView->setIndexSelected(MyGUI::ITEM_NONE);
  }
  if (g_profileBioEdit) {
    g_profileBioEdit->setCaption(Utf8ToWide(bio).c_str());
  }

  if (g_profileFactionView) {
    g_profileFactionView->removeAllItems();
    std::stringstream ss(faction);
    std::string line;
    while (std::getline(ss, line))
      g_profileFactionView->addItem(Utf8ToWide(line).c_str());
    g_profileFactionView->setIndexSelected(MyGUI::ITEM_NONE);
  }
  if (g_profileFactionEdit) {
    g_profileFactionEdit->setCaption(Utf8ToWide(faction).c_str());
  }
}

} // namespace UI
} // namespace SentientSands
