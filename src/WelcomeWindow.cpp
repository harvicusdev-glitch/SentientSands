#include "WelcomeWindow.h"
#include "Comm.h"
#include "Globals.h"
#include "Utils.h"

#include <mygui/MyGUI_Button.h>
#include <mygui/MyGUI_ComboBox.h>
#include <mygui/MyGUI_Delegate.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_TextBox.h>
#include <mygui/MyGUI_Window.h>

namespace SentientSands {
namespace UI {

MyGUI::Window *g_welcomeWindow = nullptr;

void CloseWelcomeUI() {
  if (g_welcomeWindow) {
    if (MyGUI::Gui::getInstancePtr())
      MyGUI::Gui::getInstancePtr()->destroyWidget(g_welcomeWindow);
    g_welcomeWindow = nullptr;
    g_welcomeCheckbox = nullptr;
  }
}

void OnWelcomeDiscordClick(MyGUI::Widget *sender) {
  ShellExecuteA(NULL, "open", "https://discord.gg/B9YgRk8AE8", NULL, NULL,
                SW_SHOWNORMAL);
}

void OnWelcomeToggleClick(MyGUI::Widget *sender) {
  g_enableWelcome = !g_enableWelcome;
  ((MyGUI::Button *)sender)
      ->setCaption(g_enableWelcome
                       ? Utf8ToWide(T("Show on Startup: [ON]")).c_str()
                       : Utf8ToWide(T("Show on Startup: [OFF]")).c_str());
}

void OnWelcomeWindowButtonPressed(MyGUI::Window *sender,
                                  const std::string &name) {
  if (name == "close")
    CloseWelcomeUI();
}

DWORD WINAPI WelcomeResponseThread(LPVOID lpParam) {
  Log("WELCOME_THREAD: Fetching initial config...");
  std::string response = PostToPythonWithResponse(L"/settings", "");
  if (response.empty()) {
    Log("WELCOME_THREAD: Server not responding.");
    return 0;
  }

  std::string pipeMsg = "CMD: POPULATE_WELCOME: " + response;
  EnterCriticalSection(&g_msgMutex);
  g_messageQueue.push_back(pipeMsg);
  LeaveCriticalSection(&g_msgMutex);

  return 0;
}

void CreateWelcomeUI() {
  MyGUI::Gui *gui = MyGUI::Gui::getInstancePtr();
  if (!gui)
    return;
  if (g_welcomeWindow)
    CloseWelcomeUI();

  // Smaller window: 45% height, positioned higher up
  g_welcomeWindow = gui->createWidgetReal<MyGUI::Window>(
      "Kenshi_WindowCX", 0.32f, 0.10f, 0.36f, 0.45f, MyGUI::Align::Center,
      "Popup", "SentientSands_WelcomeWindow");
  g_welcomeWindow->setCaption(
      Utf8ToWide(T("Welcome to SentientSands")).c_str());
  g_welcomeWindow->eventWindowButtonPressed +=
      MyGUI::newDelegate(OnWelcomeWindowButtonPressed);

  MyGUI::Widget *client = g_welcomeWindow->getClientWidget();

  float yProg = 0.02f;
  float yDelta = 0.07f;

  MyGUI::TextBox *l1 = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", 0.05f, yProg, 0.9f, 0.06f,
      MyGUI::Align::Top | MyGUI::Align::HStretch, "SentientSands_WelcomeL1");
  l1->setCaption(
      Utf8ToWide(
          T("Welcome to SentientSands, the Kenshi LLM project by Harvicus"))
          .c_str());
  l1->setTextAlign(MyGUI::Align::Center);
  l1->setTextColour(MyGUI::Colour(0.85f, 0.85f, 0.85f));
  yProg += yDelta;

  MyGUI::TextBox *l2 = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", 0.05f, yProg, 0.9f, 0.06f,
      MyGUI::Align::Top | MyGUI::Align::HStretch, "SentientSands_WelcomeL2");
  l2->setCaption(
      Utf8ToWide(
          T("SentientSands is a work in progress... you WILL encounter bugs!"))
          .c_str());
  l2->setTextAlign(MyGUI::Align::Center);
  l2->setTextColour(MyGUI::Colour(1.0f, 0.6f, 0.6f));
  yProg += yDelta;

  MyGUI::TextBox *l3 = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", 0.05f, yProg, 0.9f, 0.06f,
      MyGUI::Align::Top | MyGUI::Align::HStretch, "SentientSands_WelcomeL3");
  l3->setCaption(
      Utf8ToWide(T("Join the discord to report bugs, suggest features, or join "
                   "the community"))
          .c_str());
  l3->setTextAlign(MyGUI::Align::Center);
  l3->setTextColour(MyGUI::Colour(0.7f, 0.7f, 1.0f));
  yProg += yDelta;

  MyGUI::TextBox *l4 = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", 0.05f, yProg, 0.9f, 0.06f,
      MyGUI::Align::Top | MyGUI::Align::HStretch, "SentientSands_WelcomeL4");
  l4->setCaption(Utf8ToWide(T("Special thanks to BFrizzleFoShizzle and the "
                              "RE_Kenshi contributors"))
                     .c_str());
  l4->setTextAlign(MyGUI::Align::Center);
  l4->setTextColour(MyGUI::Colour(1.0f, 0.9f, 0.5f));

  // Instructions
  MyGUI::TextBox *instructions = client->createWidgetReal<MyGUI::TextBox>(
      "Kenshi_TextboxStandardText", 0.05f, 0.40f, 0.9f, 0.1f,
      MyGUI::Align::Top | MyGUI::Align::HStretch, "SentientSands_WelcomeKeys");
  instructions->setCaption(
      Utf8ToWide(T("Use [ \\ ] to Chat and [ F8 ] to open the AI Panel"))
          .c_str());
  instructions->setTextAlign(MyGUI::Align::Center);
  instructions->setTextColour(MyGUI::Colour(0.6f, 1.0f, 0.6f));

  // Startup Toggle
  g_welcomeCheckbox = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.05f, 0.55f, 0.9f, 0.12f,
      MyGUI::Align::Top | MyGUI::Align::HStretch,
      "SentientSands_WelcomeToggle");
  g_welcomeCheckbox->setCaption(Utf8ToWide(g_enableWelcome
                                               ? T("Show on Startup: [ON]")
                                               : T("Show on Startup: [OFF]"))
                                    .c_str());
  g_welcomeCheckbox->eventMouseButtonClick +=
      MyGUI::newDelegate(OnWelcomeToggleClick);

  // Close Button
  MyGUI::Button *saveBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.05f, 0.75f, 0.42f, 0.18f,
      MyGUI::Align::Bottom | MyGUI::Align::Left,
      "SentientSands_WelcomeSaveBtn");
  saveBtn->setCaption(Utf8ToWide(T("CLOSE")).c_str());
  saveBtn->eventMouseButtonClick += MyGUI::newDelegate(OnWelcomeSaveClick);

  // Discord Button
  MyGUI::Button *discordBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.53f, 0.75f, 0.42f, 0.18f,
      MyGUI::Align::Bottom | MyGUI::Align::Right,
      "SentientSands_WelcomeDiscordBtn");
  discordBtn->setCaption(Utf8ToWide(T("JOIN DISCORD")).c_str());
  discordBtn->eventMouseButtonClick +=
      MyGUI::newDelegate(OnWelcomeDiscordClick);

  // Initial fetch for background
  CreateThread(NULL, 0, WelcomeResponseThread, NULL, 0, NULL);
}

void OnWelcomeSaveClick(MyGUI::Widget *sender) {
  SavePluginConfig();
  CloseWelcomeUI();
}

} // namespace UI
} // namespace SentientSands
