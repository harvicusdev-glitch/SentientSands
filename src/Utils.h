#pragma once
#include <string>
#include <vector>
#include <windows.h>

void Log(const std::string &msg);
std::string ToString(int val);
std::string ToString(unsigned int val);
std::string ToString(float val);
std::string ToString(float val);
std::string EscapeJSON(const std::string &s);
std::string UnescapeJSON(const std::string &s);
std::wstring Utf8ToWide(const std::string &str);
std::string GetJsonValue(const std::string &json, const std::string &key);
void LoadPluginConfig();
void SavePluginConfig();
void SetHotkeyFromString(const std::string &keyStr);
void StartPythonServer();
void SleepIfPaused(DWORD ms);
