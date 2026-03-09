#include "EventsWindow.h"
#include "Comm.h"
#include "Globals.h"
#include "Utils.h"
#include <mygui/MyGUI_Button.h>
#include <mygui/MyGUI_Delegate.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_ListBox.h>
#include <mygui/MyGUI_Window.h>

namespace SentientSands {
namespace UI {

MyGUI::Window *g_eventsWindow = nullptr;
MyGUI::ListBox *g_eventsList = nullptr;
MyGUI::ListBox *g_eventsText = nullptr;
std::vector<std::string> g_eventsStorageIds;

void CloseEventsUI() {
  if (g_eventsWindow) {
    if (MyGUI::Gui::getInstancePtr())
      MyGUI::Gui::getInstancePtr()->destroyWidget(g_eventsWindow);
    g_eventsWindow = nullptr;
    g_eventsList = nullptr;
    g_eventsText = nullptr;
    g_eventsStorageIds.clear();
  }
}

void PopulateEventsUI(const std::string &data) {
  if (!g_eventsList)
    return;
  g_eventsList->removeAllItems();
  g_eventsStorageIds.clear();
  size_t cur = 0;
  // JSON Format: [{"id": "...", "title": "..."}, ...]
  while ((cur = data.find("\"id\":", cur)) != std::string::npos) {
    cur = data.find("\"", cur + 5); // start of id value
    if (cur == std::string::npos)
      break;
    size_t idEnd = data.find("\"", cur + 1);
    std::string id = data.substr(cur + 1, idEnd - cur - 1);

    size_t titleField = data.find("\"title\":", idEnd);
    if (titleField == std::string::npos)
      break;
    size_t titleStart = data.find("\"", titleField + 8);
    size_t titleEnd = data.find("\"", titleStart + 1);
    std::string title = data.substr(titleStart + 1, titleEnd - titleStart - 1);

    g_eventsList->addItem(Utf8ToWide(UnescapeJSON(title)).c_str());
    g_eventsStorageIds.push_back(id);
    cur = titleEnd;
  }
}

void SetEventsText(const std::string &data) {
  if (!g_eventsText)
    return;
  Log("EVENTS_TEXT: Received " + ToString((int)data.length()) + " bytes");
  size_t start = (data.length() > 0 && data[0] == ' ') ? 1 : 0;
  std::stringstream ss(data.substr(start));
  std::string line;
  g_eventsText->removeAllItems();
  while (std::getline(ss, line)) {
    g_eventsText->addItem(Utf8ToWide(line).c_str());
  }
}

void OnSynthesizeClick(MyGUI::Widget *sender) {
  if (g_eventsText) {
    g_eventsText->removeAllItems();
    g_eventsText->addItem(
        Utf8ToWide(T("Synthesizing world narrative... Please wait.")).c_str());
  }
  CreateThread(NULL, 0, SynthesizeThread, NULL, 0, NULL);
}

DWORD WINAPI SynthesizeThread(LPVOID lpParam) {
  Log("EVENTS_THREAD: Requesting manual synthesis...");
  std::string response = PostToPythonWithResponse(L"/synthesize", "");
  if (!response.empty()) {
    std::string rumor = GetJsonValue(response, "rumor");
    if (!rumor.empty()) {
      Log("EVENTS_THREAD: Synthesis successful: " + rumor);
      // Refresh the list to show the new rumor entry
      CreateThread(NULL, 0, EventsResponseThread, NULL, 0, NULL);
    } else {
      std::string error = GetJsonValue(response, "message");
      std::string msg = "CMD: SET_EVENTS_TEXT: " + T("Synthesis failed: ") +
                        (error.empty() ? T("Unknown error") : error);
      EnterCriticalSection(&g_msgMutex);
      g_messageQueue.push_back(msg);
      LeaveCriticalSection(&g_msgMutex);
    }
  }
  return 0;
}

void OnEventsSelect(MyGUI::ListBox *sender, size_t index) {
  if (index == MyGUI::ITEM_NONE)
    return;
  if (index >= g_eventsStorageIds.size())
    return;
  std::string dayId = g_eventsStorageIds[index];

  if (g_eventsText) {
    g_eventsText->removeAllItems();
    g_eventsText->addItem(
        Utf8ToWide(T("Reading global event: ") + dayId).c_str());
  }

  EventTask *t = new EventTask();
  t->day = dayId;
  t->json = "{\"day\":\"" + dayId + "\"}";
  CreateThread(NULL, 0, EventsContentThread, t, 0, NULL);
}

DWORD WINAPI EventsContentThread(LPVOID lpParam) {
  EventTask *t = (EventTask *)lpParam;
  Log("EVENTS_THREAD: Fetching content for Day " + t->day);
  std::string response = PostToPythonWithResponse(L"/events/content", t->json);
  if (!response.empty()) {
    std::string content = GetJsonValue(response, "text");
    if (!content.empty()) {
      std::string pipeMsg = "CMD: SET_EVENTS_TEXT: " + content;
      EnterCriticalSection(&g_msgMutex);
      g_messageQueue.push_back(pipeMsg);
      LeaveCriticalSection(&g_msgMutex);
    }
  }
  delete t;
  return 0;
}

DWORD WINAPI EventsResponseThread(LPVOID lpParam) {
  Log("EVENTS_THREAD: Fetching events list...");
  std::string response = PostToPythonWithResponse(L"/events", "");
  if (!response.empty()) {
    std::string eventsJson = GetJsonValue(response, "events");
    if (!eventsJson.empty()) {
      std::string pipeMsg = "CMD: POPULATE_EVENTS: " + eventsJson;
      EnterCriticalSection(&g_msgMutex);
      g_messageQueue.push_back(pipeMsg);
      LeaveCriticalSection(&g_msgMutex);
    }
  }
  return 0;
}

void OnEventsWindowClose(MyGUI::Window *sender, const std::string &name) {
  CloseEventsUI();
}

void CreateEventsUI() {
  MyGUI::Gui *gui = MyGUI::Gui::getInstancePtr();
  if (!gui)
    return;
  if (g_eventsWindow)
    CloseEventsUI();

  g_eventsWindow = gui->createWidgetReal<MyGUI::Window>(
      "Kenshi_WindowCX", 0.1f, 0.1f, 0.8f, 0.8f, MyGUI::Align::Center, "Popup",
      "SentientSands_EventsWindow");
  g_eventsWindow->setCaption(Utf8ToWide(T("Dynamic World Events Log")).c_str());
  g_eventsWindow->eventWindowButtonPressed +=
      MyGUI::newDelegate(OnEventsWindowClose);

  MyGUI::Widget *client = g_eventsWindow->getClientWidget();

  // List (Left 30%)
  g_eventsList = client->createWidgetReal<MyGUI::ListBox>(
      "Kenshi_ListBox", 0.02f, 0.02f, 0.28f, 0.82f,
      MyGUI::Align::Left | MyGUI::Align::VStretch, "SentientSands_EventsList");
  g_eventsList->eventListSelectAccept += MyGUI::newDelegate(OnEventsSelect);
  g_eventsList->eventListChangePosition += MyGUI::newDelegate(OnEventsSelect);

  // Synthesize Button
  MyGUI::Button *btnSync = client->createWidgetReal<MyGUI::Button>(
      "Kenshi_Button1", 0.02f, 0.86f, 0.28f, 0.08f,
      MyGUI::Align::Left | MyGUI::Align::Bottom, "SentientSands_SyncButton");
  btnSync->setCaption(Utf8ToWide(T("Generate World Event")).c_str());
  btnSync->eventMouseButtonClick += MyGUI::newDelegate(OnSynthesizeClick);

  // Text (Right 70%)
  g_eventsText = client->createWidgetReal<MyGUI::ListBox>(
      "Kenshi_ListBox", 0.32f, 0.02f, 0.66f, 0.96f, MyGUI::Align::Default,
      "SentientSands_EventsText");
  g_eventsText->addItem(
      Utf8ToWide(T("Select an entry to view details.")).c_str());

  CreateThread(NULL, 0, EventsResponseThread, NULL, 0, NULL);
}

} // namespace UI
} // namespace SentientSands
