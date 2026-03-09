#include "ChatUIGlobals.h"

namespace SentientSands {
namespace UI {

std::string g_allModelsJson = "";
bool g_welcomeShown = false;
bool g_enableWelcome = true;
MyGUI::Button *g_welcomeCheckbox = nullptr;

MyGUI::Window *g_campaignWindow = nullptr;
MyGUI::ComboBox *g_campaignList = nullptr;
MyGUI::EditBox *g_campaignNewName = nullptr;
MyGUI::TextBox *g_campaignStatus = nullptr;
MyGUI::TextBox *g_campaignActiveLabel = nullptr;

} // namespace UI
} // namespace SentientSands
