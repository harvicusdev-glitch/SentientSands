#pragma once
#include "ChatUIGlobals.h"

namespace SentientSands {
namespace UI {

extern MyGUI::Window *g_eventsWindow;
extern MyGUI::ListBox *g_eventsList;
extern MyGUI::ListBox *g_eventsText;
extern std::vector<std::string> g_eventsStorageIds;

void CreateEventsUI();
void CloseEventsUI();
void PopulateEventsUI(const std::string &data);
void SetEventsText(const std::string &data);

void OnSynthesizeClick(MyGUI::Widget *sender);
DWORD WINAPI SynthesizeThread(LPVOID lpParam);
void OnEventsSelect(MyGUI::ListBox *sender, size_t index);
void OnEventsWindowClose(MyGUI::Window *sender, const std::string &name);
DWORD WINAPI EventsResponseThread(LPVOID lpParam);
DWORD WINAPI EventsContentThread(LPVOID lpParam);

} // namespace UI
} // namespace SentientSands
