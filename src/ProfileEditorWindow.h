#pragma once
#include <string>

namespace MyGUI {
class Window;
class EditBox;
class Widget;
} // namespace MyGUI

namespace SentientSands {
namespace UI {

extern MyGUI::Window *g_profileEditorWindow;

void CreateProfileEditorUI();
void CloseProfileEditorUI();
void PopulateProfileEditorUI(const std::string &json);

} // namespace UI
} // namespace SentientSands
