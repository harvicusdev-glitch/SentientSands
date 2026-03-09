#include "HistoryWindow.h"
#include "Comm.h"
#include "Globals.h"
#include "Utils.h"
#include <mygui/MyGUI_Button.h>
#include <mygui/MyGUI_Delegate.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_ListBox.h>
#include <mygui/MyGUI_Window.h>
#include <sstream>

namespace SentientSands {
namespace UI {

MyGUI::Window *g_historyWindow = nullptr;
MyGUI::ListBox *g_historyText = nullptr;

void CloseHistoryUI() {
  if (g_historyWindow) {
    if (MyGUI::Gui::getInstancePtr())
      MyGUI::Gui::getInstancePtr()->destroyWidget(g_historyWindow);
    g_historyWindow = nullptr;
    g_historyText = nullptr;
  }
}

DWORD WINAPI HistoryResponseThread(LPVOID lpParam) {
  HistoryTask *t = (HistoryTask *)lpParam;
  Log("HISTORY_THREAD: Requesting history for " + t->npcName);
  std::string response = PostToPythonWithResponse(L"/history", t->json);

  if (!response.empty()) {
    std::string content = GetJsonValue(response, "text");
    if (!content.empty()) {
      std::string pipeMsg = "SHOW_HISTORY: " + t->npcName + "| " + content;
      EnterCriticalSection(&g_msgMutex);
      g_messageQueue.push_back(pipeMsg);
      LeaveCriticalSection(&g_msgMutex);
    } else {
      Log("HISTORY_THREAD: Failed to extract 'text' from response.");
    }
  } else {
    Log("HISTORY_THREAD: Empty response or server unavailable.");
  }
  delete t;
  return 0;
}

void OnHistoryCloseClick(MyGUI::Widget *sender) { CloseHistoryUI(); }

void OnHistoryWindowButtonPressed(MyGUI::Window *sender,
                                  const std::string &name) {
  if (name == "close")
    CloseHistoryUI();
}

void CreateHistoryUI(const std::string &npcName, const std::string &content) {
  MyGUI::Gui *gui = MyGUI::Gui::getInstancePtr();
  if (!gui)
    return;
  if (g_historyWindow)
    CloseHistoryUI();

  g_historyWindow = gui->createWidgetReal<MyGUI::Window>(
      "Kenshi_WindowCX", 0.2f, 0.1f, 0.6f, 0.8f, MyGUI::Align::Center, "Popup",
      "SentientSands_HistoryWindow");
  g_historyWindow->setCaption(
      Utf8ToWide(T("Profile & History: ") + npcName).c_str());
  g_historyWindow->eventWindowButtonPressed +=
      MyGUI::newDelegate(OnHistoryWindowButtonPressed);
  MyGUI::Widget *client = g_historyWindow->getClientWidget();
  g_historyText = client->createWidgetReal<MyGUI::ListBox>(
      "Kenshi_ListBox", 0.05f, 0.05f, 0.9f, 0.8f,
      MyGUI::Align::Top | MyGUI::Align::HStretch, "SentientSands_HistoryText");

  std::stringstream ss(content);
  std::string line;
  while (std::getline(ss, line)) {
    g_historyText->addItem(Utf8ToWide(line).c_str());
  }

  MyGUI::Button *closeBtn = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.4f, 0.88f, 0.2f, 0.08f,
      MyGUI::Align::Bottom | MyGUI::Align::HCenter,
      "SentientSands_HistoryCloseBtn");
  closeBtn->setCaption(Utf8ToWide(T("Close")).c_str());
  closeBtn->eventMouseButtonClick += MyGUI::newDelegate(OnHistoryCloseClick);
}

} // namespace UI
} // namespace SentientSands
