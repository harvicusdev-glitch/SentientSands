#include "SettingsWindow.h"
#include "CampaignsWindow.h"
#include "Comm.h"
#include "Globals.h"
#include "Utils.h"
#include "WelcomeWindow.h"

#include <shellapi.h>
#include <windows.h>

#include <mygui/MyGUI_Button.h>
#include <mygui/MyGUI_ComboBox.h>
#include <mygui/MyGUI_Delegate.h>
#include <mygui/MyGUI_EditBox.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_Window.h>

namespace SentientSands {
namespace UI {

MyGUI::Window *g_settingsWindow = nullptr;
MyGUI::ComboBox *g_settingsProvider = nullptr;
MyGUI::ComboBox *g_settingsModel = nullptr;
MyGUI::EditBox *g_settingsRadii[3] = {nullptr, nullptr, nullptr};
MyGUI::EditBox *g_settingsAmbientTimer = nullptr;
MyGUI::Button *g_settingsAmbientToggle = nullptr;
MyGUI::Button *g_settingsRenamerToggle = nullptr;
MyGUI::Button *g_settingsAnimalToggle = nullptr;
MyGUI::EditBox *g_settingsEventsCount = nullptr;
MyGUI::EditBox *g_settingsDialogueSpeed = nullptr;
MyGUI::EditBox *g_settingsSpeechBubbleLife = nullptr;
MyGUI::EditBox *g_settingsSynthesisTimer = nullptr;
MyGUI::ComboBox *g_settingsHotkey = nullptr;
MyGUI::ComboBox *g_settingsLanguage = nullptr;

void CloseSettingsUI() {
  if (g_settingsWindow) {
    if (MyGUI::Gui::getInstancePtr())
      MyGUI::Gui::getInstancePtr()->destroyWidget(g_settingsWindow);
    g_settingsWindow = nullptr;
    g_settingsProvider = nullptr;
    g_settingsModel = nullptr;
    for (int i = 0; i < 3; ++i)
      g_settingsRadii[i] = nullptr;
    g_settingsAmbientToggle = nullptr;
    g_settingsRenamerToggle = nullptr;
    g_settingsAnimalToggle = nullptr;
    g_settingsEventsCount = nullptr;
    g_settingsDialogueSpeed = nullptr;
    g_settingsSpeechBubbleLife = nullptr;
    g_settingsSynthesisTimer = nullptr;
    g_settingsHotkey = nullptr;
    g_settingsLanguage = nullptr;
  }
}

void OnSettingsWindowButtonPressed(MyGUI::Window *sender,
                                   const std::string &name) {
  if (name == "close")
    CloseSettingsUI();
}

void OnSettingsSaveClick(MyGUI::Widget *sender) {
  if (!g_settingsWindow)
    return;

  std::string provider = "";
  if (g_settingsProvider->getIndexSelected() != MyGUI::ITEM_NONE)
    provider = g_settingsProvider->getItemNameAt(
        g_settingsProvider->getIndexSelected());

  if (g_settingsHotkey &&
      g_settingsHotkey->getIndexSelected() != MyGUI::ITEM_NONE) {
    SetHotkeyFromString(
        g_settingsHotkey->getItemNameAt(g_settingsHotkey->getIndexSelected()));
    SavePluginConfig();
  }

  if (g_settingsLanguage &&
      g_settingsLanguage->getIndexSelected() != MyGUI::ITEM_NONE) {
    g_language = g_settingsLanguage->getItemNameAt(
        g_settingsLanguage->getIndexSelected());
    SavePluginConfig();
  }

  std::string model = "";
  if (g_settingsModel->getIndexSelected() != MyGUI::ITEM_NONE)
    model = g_settingsModel->getItemNameAt(g_settingsModel->getIndexSelected());

  std::string json = "{";
  json += "\"current_model\": \"" + model + "\",";
  json += "\"radii\": {";
  json += "\"radiant\": " + g_settingsRadii[0]->getCaption() + ",";
  json += "\"talk\": " + g_settingsRadii[1]->getCaption() + ",";
  json += "\"yell\": " + g_settingsRadii[2]->getCaption();
  json += "},";
  json += "\"ambient_timer\": " + g_settingsAmbientTimer->getCaption() + ",";
  json +=
      "\"synthesis_timer\": " + g_settingsSynthesisTimer->getCaption() + ",";
  json += "\"global_events_count\": " +
          (g_settingsEventsCount ? g_settingsEventsCount->getCaption()
                                 : std::string("10")) +
          ",";
  json += "\"dialogue_speed\": " +
          (g_settingsDialogueSpeed ? g_settingsDialogueSpeed->getCaption()
                                   : std::string("5")) +
          ",";
  json += "\"bubble_life\": " +
          (g_settingsSpeechBubbleLife ? g_settingsSpeechBubbleLife->getCaption()
                                      : std::string("5")) +
          ",";
  json += "\"enable_ambient\": ";
  json += (g_enableAmbient ? "true" : "false");
  json += ",\"enable_renamer\": ";
  json += (g_enableRenamer ? "true" : "false");
  json += ",\"enable_animal_renamer\": ";
  json += (g_enableAnimalRenamer ? "true" : "false");
  json += ",\"language\": \"" + EscapeJSON(g_language) + "\",";
  json += "\"chat_hotkey\": \"" + EscapeJSON(g_chatHotkeyStr) + "\"";
  json += "}";

  // Use synchronous post to ensure server updates before window closes
  // and we get the fresh translation map back.
  std::string response = PostToPythonWithResponse(L"/settings", json);
  if (!response.empty()) {
    PopulateSettingsUI(response);
  }

  CloseSettingsUI();
}

void OnSettingsAmbientToggleClick(MyGUI::Widget *sender) {
  g_enableAmbient = !g_enableAmbient;
  g_settingsAmbientToggle->setCaption(
      Utf8ToWide(g_enableAmbient ? "Radiant: [ON]" : "Radiant: [OFF]").c_str());
}

void OnSettingsRenamerToggleClick(MyGUI::Widget *sender) {
  g_enableRenamer = !g_enableRenamer;
  g_settingsRenamerToggle->setCaption(
      Utf8ToWide(g_enableRenamer ? "Global: [ON]" : "Global: [OFF]").c_str());
}

void OnSettingsAnimalToggleClick(MyGUI::Widget *sender) {
  g_enableAnimalRenamer = !g_enableAnimalRenamer;
  g_settingsAnimalToggle->setCaption(
      Utf8ToWide(g_enableAnimalRenamer ? "Animals: [ON]" : "Animals: [OFF]").c_str());
}

void OnSettingsOpenConfigClick(MyGUI::Widget *sender) {
  std::string configPath = g_modRoot + "\\server\\config";
  ShellExecuteA(NULL, "open", configPath.c_str(), NULL, NULL, SW_SHOWDEFAULT);
}

static DWORD WINAPI TestPingThread(LPVOID lp) {
  MyGUI::Button *btn = (MyGUI::Button *)lp;
  // Test both server and LLM connectivity
  std::string response = PostToPythonWithResponse(L"/test_llm", "{}");

  if (response.empty()) {
    btn->setCaption(Utf8ToWide(T("OFFLINE")).c_str());
  } else if (response.find("\"llm\":\"ok\"") != std::string::npos ||
             response.find("\"llm\": \"ok\"") != std::string::npos) {
    btn->setCaption(Utf8ToWide(T("LLM OK")).c_str());
  } else if (response.find("\"status\":\"ok\"") != std::string::npos ||
             response.find("\"status\": \"ok\"") != std::string::npos) {
    btn->setCaption(Utf8ToWide(T("SRV OK / LLM FAIL")).c_str());
  } else {
    btn->setCaption(Utf8ToWide(T("ERR")).c_str());
  }
  return 0;
}

void OnSettingsTestClick(MyGUI::Widget *sender) {
  MyGUI::Button *btn = (MyGUI::Button *)sender;
  btn->setCaption(Utf8ToWide("...").c_str());
  CreateThread(NULL, 0, TestPingThread, sender, 0, NULL);
}

void OnSettingsRestartClick(MyGUI::Widget *sender) {
  MyGUI::Button *btn = (MyGUI::Button *)sender;
  btn->setCaption(Utf8ToWide(T("REBOOTING")).c_str());
  StartPythonServer();
}

void OnSettingsProviderChange(MyGUI::ComboBox *sender, size_t index) {
  if (index == MyGUI::ITEM_NONE || g_allModelsJson.empty())
    return;

  std::string provider = sender->getItemNameAt(index);
  g_settingsModel->removeAllItems();

  // Parse models for this provider from g_allModelsJson
  // Format: {"provider1": ["model1", "model2"], "provider2": [...]}
  size_t pPos = g_allModelsJson.find("\"" + provider + "\":");
  if (pPos != std::string::npos) {
    size_t start = g_allModelsJson.find("[", pPos);
    size_t end = g_allModelsJson.find("]", start);
    if (start != std::string::npos && end != std::string::npos) {
      std::string list = g_allModelsJson.substr(start + 1, end - start - 1);
      size_t cur = 0, next;
      while ((next = list.find(",", cur)) != std::string::npos) {
        std::string item = list.substr(cur, next - cur);
        size_t q1 = item.find("\"");
        size_t q2 = item.find("\"", q1 + 1);
        if (q1 != std::string::npos && q2 != std::string::npos)
          g_settingsModel->addItem(
              Utf8ToWide(item.substr(q1 + 1, q2 - q1 - 1)).c_str());
        cur = next + 1;
      }
      std::string last = list.substr(cur);
      size_t q1 = last.find("\"");
      size_t q2 = last.find("\"", q1 + 1);
      if (q1 != std::string::npos && q2 != std::string::npos)
        g_settingsModel->addItem(
            Utf8ToWide(last.substr(q1 + 1, q2 - q1 - 1)).c_str());
    }
  }

  if (g_settingsModel->getItemCount() > 0)
    g_settingsModel->setIndexSelected(0);
}

DWORD WINAPI SettingsResponseThread(LPVOID lpParam) {
  Log("SETTINGS_THREAD: Fetching config...");
  std::string response = PostToPythonWithResponse(L"/settings", "");
  if (!response.empty()) {
    std::string pipeMsg = "CMD: POPULATE_SETTINGS: " + response;
    EnterCriticalSection(&g_msgMutex);
    g_messageQueue.push_back(pipeMsg);
    LeaveCriticalSection(&g_msgMutex);
  } else {
    Log("SETTINGS_THREAD: Failed to fetch settings.");
  }
  return 0;
}

void CreateSettingsUI() {
  MyGUI::Gui *gui = MyGUI::Gui::getInstancePtr();
  if (!gui)
    return;
  if (g_settingsWindow)
    CloseSettingsUI();

  g_settingsWindow = gui->createWidgetReal<MyGUI::Window>(
      "Kenshi_WindowCX", 0.3f, 0.1f, 0.4f, 0.73f, MyGUI::Align::Center,
      "Overlapped", "SentientSands_SettingsWindow");
  g_settingsWindow->setCaption(Utf8ToWide(T("AI Settings")).c_str());
  g_settingsWindow->eventWindowButtonPressed +=
      MyGUI::newDelegate(OnSettingsWindowButtonPressed);

  MyGUI::Widget *client = g_settingsWindow->getClientWidget();

  float y = 0.05f;
  float yDelta = 0.11f;

  // Provider
  client
      ->createWidgetReal<MyGUI::TextBox>("Kenshi_TextboxStandardText", 0.05f, y,
                                         0.3f, 0.08f, MyGUI::Align::Left,
                                         "SentientSands_SetProvLabel")
      ->setCaption(Utf8ToWide(T("LLM Provider:")).c_str());
  g_settingsProvider = client->createWidgetReal<MyGUI::ComboBox>(
      "Kenshi_ComboBox", 0.4f, y, 0.55f, 0.06f, MyGUI::Align::Top,
      "SentientSands_SetProvCombo");
  g_settingsProvider->setComboModeDrop(true);
  g_settingsProvider->eventComboAccept +=
      MyGUI::newDelegate(OnSettingsProviderChange);
  y += 0.09f;

  // Model
  client
      ->createWidgetReal<MyGUI::TextBox>("Kenshi_TextboxStandardText", 0.05f, y,
                                         0.3f, 0.08f, MyGUI::Align::Left,
                                         "SentientSands_SetModelLabel")
      ->setCaption(Utf8ToWide(T("LLM Model:")).c_str());
  g_settingsModel = client->createWidgetReal<MyGUI::ComboBox>(
      "Kenshi_ComboBox", 0.4f, y, 0.55f, 0.06f, MyGUI::Align::Top,
      "SentientSands_SetModelCombo");
  g_settingsModel->setComboModeDrop(true);
  y += 0.09f;

  // Radii
  const char *labelKeys[] = {"Radiant Range:", "Talk Range:", "Yell Range:"};
  const char *ids[] = {"0", "1", "2"};
  for (int i = 0; i < 3; i++) {
    client
        ->createWidgetReal<MyGUI::TextBox>(
            "Kenshi_TextboxStandardText", 0.05f, y, 0.3f, 0.08f,
            MyGUI::Align::Left,
            std::string("SentientSands_SetRadiusLabel") + ids[i])
        ->setCaption(Utf8ToWide(T(labelKeys[i])).c_str());
    g_settingsRadii[i] = client->createWidgetReal<MyGUI::EditBox>(
        "Kenshi_EditBox", 0.4f, y, 0.2f, 0.06f, MyGUI::Align::Top,
        std::string("SentientSands_SetRadiusEdit") + ids[i]);

    if (i == 0) {
      MyGUI::Button *openConfigBtn = client->createWidgetReal<MyGUI::Button>(
          "Kenshi_Button1", 0.65f, y, 0.3f, 0.06f, MyGUI::Align::Top,
          "SentientSands_SetOpenConfigBtn");
      openConfigBtn->setCaption(Utf8ToWide(T("Open config folder")).c_str());
      openConfigBtn->eventMouseButtonClick +=
          MyGUI::newDelegate(OnSettingsOpenConfigClick);
    }

    y += 0.07f;
  }
  y += 0.04f;

  // Timer
  client
      ->createWidgetReal<MyGUI::TextBox>("Kenshi_TextboxStandardText", 0.05f, y,
                                         0.3f, 0.08f, MyGUI::Align::Left,
                                         "SentientSands_SetTimerLabel")
      ->setCaption(Utf8ToWide(T("Radiant Timer (s):")).c_str());
  g_settingsAmbientTimer = client->createWidgetReal<MyGUI::EditBox>(
      "Kenshi_EditBox", 0.4f, y, 0.2f, 0.06f, MyGUI::Align::Top,
      "SentientSands_SetTimerEdit");

  g_settingsAmbientToggle = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.65f, y, 0.3f, 0.06f, MyGUI::Align::Top,
      "SentientSands_SetAmbientToggle");
  g_settingsAmbientToggle->setCaption(
      Utf8ToWide(g_enableAmbient ? T("Radiant: [ON]") : T("Radiant: [OFF]"))
          .c_str());
  g_settingsAmbientToggle->eventMouseButtonClick +=
      MyGUI::newDelegate(OnSettingsAmbientToggleClick);

  y += 0.09f;

  // Global Events Count
  client
      ->createWidgetReal<MyGUI::TextBox>("Kenshi_TextboxStandardText", 0.05f, y,
                                         0.3f, 0.08f, MyGUI::Align::Left,
                                         "SentientSands_SetEventsLabel")
      ->setCaption(Utf8ToWide(T("Dynamic Events in prompt:")).c_str());
  g_settingsEventsCount = client->createWidgetReal<MyGUI::EditBox>(
      "Kenshi_EditBox", 0.4f, y, 0.2f, 0.06f, MyGUI::Align::Top,
      "SentientSands_SetEventsEdit");

  // Synthesis Timer
  client
      ->createWidgetReal<MyGUI::TextBox>("Kenshi_TextboxStandardText", 0.61f, y,
                                         0.24f, 0.08f, MyGUI::Align::Left,
                                         "SentientSands_SetSynLabel")
      ->setCaption(Utf8ToWide(T("Dynamic Event Timer (m):")).c_str());
  g_settingsSynthesisTimer = client->createWidgetReal<MyGUI::EditBox>(
      "Kenshi_EditBox", 0.86f, y, 0.1f, 0.06f, MyGUI::Align::Top,
      "SentientSands_SetSynEdit");

  y += 0.08f;

  // Dialogue Speed
  client
      ->createWidgetReal<MyGUI::TextBox>("Kenshi_TextboxStandardText", 0.05f, y,
                                         0.3f, 0.08f, MyGUI::Align::Left,
                                         "SentientSands_SetDiagSpeedLabel")
      ->setCaption(Utf8ToWide(T("Dialogue Delay (s):")).c_str());
  g_settingsDialogueSpeed = client->createWidgetReal<MyGUI::EditBox>(
      "Kenshi_EditBox", 0.4f, y, 0.2f, 0.06f, MyGUI::Align::Top,
      "SentientSands_SetDiagSpeedEdit");

  // Bubble Life
  client
      ->createWidgetReal<MyGUI::TextBox>("Kenshi_TextboxStandardText", 0.61f, y,
                                         0.24f, 0.08f, MyGUI::Align::Left,
                                         "SentientSands_SetBubbleLifeLabel")
      ->setCaption(Utf8ToWide(T("Bubble Life (s):")).c_str());
  g_settingsSpeechBubbleLife = client->createWidgetReal<MyGUI::EditBox>(
      "Kenshi_EditBox", 0.86f, y, 0.1f, 0.06f, MyGUI::Align::Top,
      "SentientSands_SetBubbleLifeEdit");

  y += 0.08f;

  // Renamer Toggles
  client
      ->createWidgetReal<MyGUI::TextBox>("Kenshi_TextboxStandardText", 0.05f, y,
                                         0.3f, 0.08f, MyGUI::Align::Left,
                                         "SentientSands_SetRenamerLabel")
      ->setCaption(Utf8ToWide(T("Renaming Toggles:")).c_str());

  g_settingsRenamerToggle = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.4f, y, 0.25f, 0.06f, MyGUI::Align::Top,
      "SentientSands_SetRenamerToggle");
  g_settingsRenamerToggle->setCaption(
      Utf8ToWide(g_enableRenamer ? T("Global: [ON]") : T("Global: [OFF]"))
          .c_str());
  g_settingsRenamerToggle->eventMouseButtonClick +=
      MyGUI::newDelegate(OnSettingsRenamerToggleClick);

  g_settingsAnimalToggle = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.7f, y, 0.25f, 0.06f, MyGUI::Align::Top,
      "SentientSands_SetAnimalToggle");
  g_settingsAnimalToggle->setCaption(
      Utf8ToWide(g_enableAnimalRenamer ? T("Animals: [ON]") : T("Animals: [OFF]"))
          .c_str());
  g_settingsAnimalToggle->eventMouseButtonClick +=
      MyGUI::newDelegate(OnSettingsAnimalToggleClick);

  y += 0.08f;

  // Hotkey
  client
      ->createWidgetReal<MyGUI::TextBox>("Kenshi_TextboxStandardText", 0.05f, y,
                                         0.3f, 0.08f, MyGUI::Align::Left,
                                         "SentientSands_SetHotkeyLabel")
      ->setCaption(Utf8ToWide(T("Chat Key:")).c_str());
  g_settingsHotkey = client->createWidgetReal<MyGUI::ComboBox>(
      "Kenshi_ComboBox", 0.4f, y, 0.2f, 0.06f, MyGUI::Align::Top,
      "SentientSands_SetHotkeyCombo");
  g_settingsHotkey->setComboModeDrop(true);
  const char *hotkeys[] = {"\\", "[", "P", "T", "J", "U", "K"};
  for (int i = 0; i < 7; i++) {
    g_settingsHotkey->addItem(Utf8ToWide(hotkeys[i]).c_str());
    if (std::string(hotkeys[i]) == g_chatHotkeyStr) {
      g_settingsHotkey->setIndexSelected(i);
    }
  }

  // Language
  client
      ->createWidgetReal<MyGUI::TextBox>("Kenshi_TextboxStandardText", 0.61f, y,
                                         0.24f, 0.08f, MyGUI::Align::Left,
                                         "SentientSands_SetLanguageLabel")
      ->setCaption(Utf8ToWide(T("Language:")).c_str());
  g_settingsLanguage = client->createWidgetReal<MyGUI::ComboBox>(
      "Kenshi_ComboBox", 0.86f, y, 0.1f, 0.06f, MyGUI::Align::Top,
      "SentientSands_SetLanguageCombo");
  g_settingsLanguage->setComboModeDrop(true);
  g_settingsLanguage->removeAllItems(); // Will be populated by server data

  // Footer Row: Test | Save | Restart
  MyGUI::Button *testBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.05f, 0.88f, 0.25f, 0.07f, MyGUI::Align::Bottom,
      "SentientSands_SettingsTestBtn");
  testBtn->setCaption(Utf8ToWide(T("TEST")).c_str());
  testBtn->eventMouseButtonClick += MyGUI::newDelegate(OnSettingsTestClick);

  MyGUI::Button *saveBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.35f, 0.88f, 0.3f, 0.07f, MyGUI::Align::Bottom,
      "SentientSands_SettingsSaveBtn");
  saveBtn->setCaption(Utf8ToWide(T("SAVE")).c_str());
  saveBtn->eventMouseButtonClick += MyGUI::newDelegate(OnSettingsSaveClick);

  MyGUI::Button *restartBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.70f, 0.88f, 0.25f, 0.07f, MyGUI::Align::Bottom,
      "SentientSands_SettingsRestartBtn");
  restartBtn->setCaption(Utf8ToWide(T("RESTART")).c_str());
  restartBtn->eventMouseButtonClick +=
      MyGUI::newDelegate(OnSettingsRestartClick);

  // Initial fetch using response thread
  CreateThread(NULL, 0, SettingsResponseThread, NULL, 0, NULL);
}

void PopulateSettingsUI(const std::string &json) {
  if (!g_settingsWindow && !g_campaignWindow)
    return;

  MyGUI::ComboBox *providerCombo = g_settingsProvider;
  MyGUI::ComboBox *modelCombo = g_settingsModel;

  std::string currentModel = GetJsonValue(json, "current");
  std::string provList = GetJsonValue(json, "providers");
  std::string enableAmbient = GetJsonValue(json, "enable_ambient");
  std::string enableRenamer = GetJsonValue(json, "enable_renamer");
  std::string enableAnimalRenamer = GetJsonValue(json, "enable_animal_renamer");
  std::string ambientTimer = GetJsonValue(json, "ambient_timer");
  std::string synthesisTimer = GetJsonValue(json, "synthesis_timer");
  std::string geCount = GetJsonValue(json, "global_events_count");
  std::string diagSpeed = GetJsonValue(json, "dialogue_speed");
  std::string bubbleLife = GetJsonValue(json, "bubble_life");
  std::string radii = GetJsonValue(json, "radii");
  std::string radiant = GetJsonValue(radii, "radiant");
  std::string t = GetJsonValue(radii, "talk");
  std::string y = GetJsonValue(radii, "yell");

  g_allModelsJson = GetJsonValue(json, "models");

  // Route campaign data to Campaigns Window
  PopulateCampaignsUI(json);

  if (providerCombo) {
    providerCombo->removeAllItems();
    size_t start = provList.find("[");
    size_t end = provList.find("]");
    if (start != std::string::npos && end != std::string::npos) {
      std::string list = provList.substr(start + 1, end - start - 1);
      size_t cur = 0, next;
      while ((next = list.find(",", cur)) != std::string::npos) {
        std::string item = list.substr(cur, next - cur);
        size_t q1 = item.find("\"");
        size_t q2 = item.find("\"", q1 + 1);
        if (q1 != std::string::npos && q2 != std::string::npos)
          providerCombo->addItem(
              Utf8ToWide(item.substr(q1 + 1, q2 - q1 - 1)).c_str());
        cur = next + 1;
      }
      std::string last = list.substr(cur);
      size_t q1 = last.find("\"");
      size_t q2 = last.find("\"", q1 + 1);
      if (q1 != std::string::npos && q2 != std::string::npos)
        providerCombo->addItem(
            Utf8ToWide(last.substr(q1 + 1, q2 - q1 - 1)).c_str());
    }

    // Use currentProvider from server if available, otherwise lookup in
    // all_models
    std::string currentProvider = GetJsonValue(json, "current_provider");
    if (currentProvider.empty()) {
      std::string allModelsInfo = GetJsonValue(json, "all_models");
      if (!currentModel.empty() && !allModelsInfo.empty()) {
        std::string searchStr = "\"" + currentModel + "\":{";
        size_t mPos = allModelsInfo.find(searchStr);
        if (mPos != std::string::npos) {
          size_t pPos = allModelsInfo.find("\"provider\":", mPos);
          if (pPos != std::string::npos) {
            size_t vStart = allModelsInfo.find('"', pPos + 11);
            size_t vEnd = allModelsInfo.find('"', vStart + 1);
            if (vStart != std::string::npos && vEnd != std::string::npos)
              currentProvider =
                  allModelsInfo.substr(vStart + 1, vEnd - vStart - 1);
          }
        }
      }
    }

    if (!currentProvider.empty()) {
      for (size_t i = 0; i < providerCombo->getItemCount(); ++i) {
        if (providerCombo->getItemNameAt(i) == currentProvider) {
          providerCombo->setIndexSelected(i);
          OnSettingsProviderChange(providerCombo, i);
          if (modelCombo) {
            for (size_t j = 0; j < modelCombo->getItemCount(); ++j) {
              if (modelCombo->getItemNameAt(j) == currentModel) {
                modelCombo->setIndexSelected(j);
                break;
              }
            }
          }
          break;
        }
      }
    }
  }

  if (g_settingsRadii[0])
    g_settingsRadii[0]->setCaption(Utf8ToWide(radiant).c_str());
  if (g_settingsRadii[1])
    g_settingsRadii[1]->setCaption(Utf8ToWide(t).c_str());
  if (g_settingsRadii[2])
    g_settingsRadii[2]->setCaption(Utf8ToWide(y).c_str());
  if (g_settingsAmbientTimer)
    g_settingsAmbientTimer->setCaption(Utf8ToWide(ambientTimer).c_str());
  if (g_settingsSynthesisTimer)
    g_settingsSynthesisTimer->setCaption(Utf8ToWide(synthesisTimer).c_str());
  if (g_settingsEventsCount)
    g_settingsEventsCount->setCaption(Utf8ToWide(geCount).c_str());
  if (g_settingsDialogueSpeed)
    g_settingsDialogueSpeed->setCaption(Utf8ToWide(diagSpeed).c_str());
  if (g_settingsSpeechBubbleLife)
    g_settingsSpeechBubbleLife->setCaption(Utf8ToWide(bubbleLife).c_str());

  std::string serverLang = GetJsonValue(json, "language");
  std::string supportedLangs = GetJsonValue(json, "supported_languages");

  if (g_settingsLanguage) {
    g_settingsLanguage->removeAllItems();
    size_t start = supportedLangs.find("[");
    size_t end = supportedLangs.find("]");
    if (start != std::string::npos && end != std::string::npos) {
      std::string list = supportedLangs.substr(start + 1, end - start - 1);
      size_t cur = 0, next;
      while ((next = list.find(",", cur)) != std::string::npos) {
        std::string item = list.substr(cur, next - cur);
        size_t q1 = item.find("\"");
        size_t q2 = item.find("\"", q1 + 1);
        if (q1 != std::string::npos && q2 != std::string::npos)
          g_settingsLanguage->addItem(
              Utf8ToWide(item.substr(q1 + 1, q2 - q1 - 1)).c_str());
        cur = next + 1;
      }
      std::string last = list.substr(cur);
      size_t q1 = last.find("\"");
      size_t q2 = last.find("\"", q1 + 1);
      if (q1 != std::string::npos && q2 != std::string::npos)
        g_settingsLanguage->addItem(
            Utf8ToWide(last.substr(q1 + 1, q2 - q1 - 1)).c_str());
    }

    if (!serverLang.empty()) {
      bool found = false;
      for (size_t i = 0; i < g_settingsLanguage->getItemCount(); ++i) {
        if (g_settingsLanguage->getItemNameAt(i) == serverLang) {
          g_settingsLanguage->setIndexSelected(i);
          found = true;
          break;
        }
      }
      if (!found) {
        g_settingsLanguage->addItem(Utf8ToWide(serverLang).c_str());
        g_settingsLanguage->setIndexSelected(
            g_settingsLanguage->getItemCount() - 1);
      }
    }

    if (g_settingsAmbientToggle) {
      if (!enableAmbient.empty()) g_enableAmbient = (enableAmbient == "true");
      g_settingsAmbientToggle->setCaption(
          Utf8ToWide(g_enableAmbient ? T("Radiant: [ON]") : T("Radiant: [OFF]"))
              .c_str());
    }

    if (g_settingsRenamerToggle) {
      if (!enableRenamer.empty()) g_enableRenamer = (enableRenamer == "true");
      g_settingsRenamerToggle->setCaption(
          Utf8ToWide(g_enableRenamer ? T("Global: [ON]") : T("Global: [OFF]"))
              .c_str());
    }

    if (g_settingsAnimalToggle) {
      if (!enableAnimalRenamer.empty()) g_enableAnimalRenamer = (enableAnimalRenamer == "true");
      g_settingsAnimalToggle->setCaption(
          Utf8ToWide(g_enableAnimalRenamer ? T("Animals: [ON]") : T("Animals: [OFF]"))
              .c_str());
    }

    // Parse ui_translation
    std::string uiTransJson = GetJsonValue(json, "ui_translation");
    if (!uiTransJson.empty()) {
      g_uiTranslation.clear();
      // Simple JSON object parser for translation map
      size_t pos = 1; // skip {
      while (pos < uiTransJson.length() - 1) {
        size_t q1 = uiTransJson.find('"', pos);
        if (q1 == std::string::npos)
          break;
        size_t q2 = uiTransJson.find('"', q1 + 1);
        if (q2 == std::string::npos)
          break;
        std::string key = uiTransJson.substr(q1 + 1, q2 - q1 - 1);

        size_t colon = uiTransJson.find(':', q2);
        if (colon == std::string::npos)
          break;

        size_t v1 = uiTransJson.find('"', colon);
        if (v1 == std::string::npos)
          break;
        size_t v2 = uiTransJson.find('"', v1 + 1);
        if (v2 == std::string::npos)
          break;
        std::string val = uiTransJson.substr(v1 + 1, v2 - v1 - 1);

        g_uiTranslation[key] = UnescapeJSON(val);
        pos = v2 + 1;
      }

      // If windows are open, refresh their main captions immediately
      if (g_settingsWindow) {
        g_settingsWindow->setCaption(Utf8ToWide(T("AI Settings")).c_str());
      }
      extern void RefreshLauncherUI();
      RefreshLauncherUI();
    }
  }
}

} // namespace UI
} // namespace SentientSands
