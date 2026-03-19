#include "Utils.h"
#include "ChatUIGlobals.h"
#include "Globals.h"
#include <fstream>
#include <iomanip>
#include <kenshi/Enums.h>
#include <kenshi/util/hand.h>
#include <sstream>

#include <algorithm>
#include <cctype>
#include <windows.h>

using namespace SentientSands::UI;

std::wstring Utf8ToWide(const std::string &str) {
  if (str.empty())
    return L"";
  int size_needed =
      MultiByteToWideChar(CP_UTF8, 0, &str[0], (int)str.size(), NULL, 0);
  std::wstring wstrTo(size_needed, 0);
  MultiByteToWideChar(CP_UTF8, 0, &str[0], (int)str.size(), &wstrTo[0],
                      size_needed);
  return wstrTo;
}

void Log(const std::string &msg) {
  EnterCriticalSection(&g_LogMutex);
  std::ofstream logFile("SentientSands_SDK.log", std::ios::app);
  if (logFile.is_open()) {
    logFile << "[SentientSands] " << msg << std::endl;
  }
  LeaveCriticalSection(&g_LogMutex);
  OutputDebugStringA(("[SentientSands] " + msg + "\n").c_str());
}

template <typename T> std::string ToStringT(T val) {
  std::ostringstream ss;
  ss << val;
  return ss.str();
}

std::string ToString(int val) { return ToStringT(val); }
std::string ToString(unsigned int val) { return ToStringT(val); }
std::string ToString(float val) { return ToStringT(val); }

std::string EscapeJSON(const std::string &s) {
  std::string res = "";
  for (size_t i = 0; i < s.length(); ++i) {
    char c = s[i];
    if (c == '\"')
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

std::string UnescapeJSON(const std::string &s) {
  std::string res = "";
  for (size_t i = 0; i < s.length(); ++i) {
    if (s[i] == '\\' && i + 1 < s.length()) {
      if (s[i + 1] == 'n') {
        res += '\n';
        i++;
      } else if (s[i + 1] == 'r') {
        res += '\r';
        i++;
      } else if (s[i + 1] == '\"') {
        res += '\"';
        i++;
      } else if (s[i + 1] == '\\') {
        res += '\\';
        i++;
      } else if (s[i + 1] == 'u') {
        if (i + 5 < s.length()) {
          // Handle \uXXXX hex sequence
          unsigned int cp = 0;
          bool valid = true;
          for (int j = 0; j < 4; ++j) {
            char c = s[i + 2 + j];
            cp <<= 4;
            if (c >= '0' && c <= '9')
              cp += (c - '0');
            else if (c >= 'a' && c <= 'f')
              cp += (10 + c - 'a');
            else if (c >= 'A' && c <= 'F')
              cp += (10 + c - 'A');
            else {
              valid = false;
              break;
            }
          }

          if (valid) {
            // Convert Unicode codepoint to UTF-8
            if (cp <= 0x7F) {
              res += (char)cp;
            } else if (cp <= 0x7FF) {
              res += (char)(0xC0 | ((cp >> 6) & 0x1F));
              res += (char)(0x80 | (cp & 0x3F));
            } else {
              res += (char)(0xE0 | ((cp >> 12) & 0x0F));
              res += (char)(0x80 | ((cp >> 6) & 0x3F));
              res += (char)(0x80 | (cp & 0x3F));
            }
            i += 5; // skip uXXXX
          } else {
            res += s[i]; // Not a valid hex sequence, just append the backslash
          }
        } else {
          // Truncated \u sequence
          res += s[i];
        }
      } else {
        res += s[i];
      }
    } else {
      res += s[i];
    }
  }
  return res;
}

std::string GetJsonValue(const std::string &json, const std::string &key) {
  std::string keyQuery = "\"" + key + "\":";
  size_t pos = json.find(keyQuery);
  if (pos == std::string::npos) {
    // try without quotes in case it's non-standard but that's unlikely
    return "";
  }

  size_t valStart = json.find_first_not_of(" \t\r\n", pos + keyQuery.length());
  if (valStart == std::string::npos)
    return "";

  if (json[valStart] == '\"') {
    // String value
    valStart++;
    std::string res = "";
    for (size_t i = valStart; i < json.length(); ++i) {
      if (json[i] == '\\' && i + 1 < json.length()) {
        res += json[i];
        res += json[i + 1];
        i++;
      } else if (json[i] == '\"') {
        return UnescapeJSON(res);
      } else {
        res += json[i];
      }
    }
  } else if (json[valStart] == '[' || json[valStart] == '{') {
    char open = json[valStart];
    char close = (open == '[') ? ']' : '}';
    int bracketCount = 0;
    bool inString = false;
    size_t i = valStart;
    for (; i < json.length(); i++) {
      if (json[i] == '"' && (i == 0 || json[i - 1] != '\\')) {
        inString = !inString;
      } else if (!inString) {
        if (json[i] == open)
          bracketCount++;
        else if (json[i] == close) {
          bracketCount--;
          if (bracketCount == 0)
            break;
        }
      }
    }
    if (i < json.length() && json[i] == close) {
      return json.substr(valStart, i - valStart + 1);
    }
  } else {
    // Number or bool
    size_t end = json.find_first_of(",}", valStart);
    if (end != std::string::npos) {
      return json.substr(valStart, end - valStart);
    }
  }
  return "";
}

static std::string Trim(const std::string &s) {
  auto start = s.begin();
  while (start != s.end() && std::isspace(*start)) {
    start++;
  }
  auto end = s.end();
  do {
    end--;
  } while (std::distance(start, end) > 0 && std::isspace(*end));
  return std::string(start, end + 1);
}

void SetHotkeyFromString(const std::string &keyStrRaw) {
  std::string keyStr = Trim(keyStrRaw);
  g_chatHotkeyStr = keyStr;

  if (keyStr == "\\")
    g_chatHotkey = VK_OEM_5;
  else if (keyStr == "[")
    g_chatHotkey = VK_OEM_4;
  else if (keyStr == "P" || keyStr == "p")
    g_chatHotkey = 'P';
  else if (keyStr == "T" || keyStr == "t")
    g_chatHotkey = 'T';
  else if (keyStr == "J" || keyStr == "j")
    g_chatHotkey = 'J';
  else if (keyStr == "U" || keyStr == "u")
    g_chatHotkey = 'U';
  else if (keyStr == "K" || keyStr == "k")
    g_chatHotkey = 'K';
  else {
    Log("WARNING: Unrecognized hotkey '" + keyStr + "', defaulting to '\\'");
    g_chatHotkey = VK_OEM_5;
    g_chatHotkeyStr = "\\";
  }
}

void LoadPluginConfig() {
  std::string iniPath = g_modRoot + "\\SentientSands_Config.ini";

  char hotkeyBuf[32];
  GetPrivateProfileStringA("Settings", "ChatHotkey", "\\", hotkeyBuf, 32,
                           iniPath.c_str());
  SetHotkeyFromString(hotkeyBuf);

  char langBuf[64];
  GetPrivateProfileStringA("Settings", "Language", "English", langBuf, 64,
                           iniPath.c_str());
  g_language = langBuf;

  g_radiantRange = (float)GetPrivateProfileIntA("Settings", "RadiantRange", 100,
                                                iniPath.c_str());
  g_proximityRadius = (float)GetPrivateProfileIntA("Settings", "TalkRadius", 100,
                                                   iniPath.c_str());
  g_yellRadius = (float)GetPrivateProfileIntA("Settings", "YellRadius", 200,
                                              iniPath.c_str());

  g_visionRange = 100.0f; // Standard vision range for NPC awareness
  g_ambientIntervalSeconds =
      GetPrivateProfileIntA("Settings", "RadiantDelay", 240, iniPath.c_str());

  g_worldEventIntervalDays = GetPrivateProfileIntA(
      "Settings", "GlobalEventsCount", 10, iniPath.c_str());

  g_enableAmbient =
      GetPrivateProfileIntA("Settings", "EnableAmbientConversations", 1,
                            iniPath.c_str()) != 0;

  g_enableWelcome = GetPrivateProfileIntA("Settings", "EnableWelcomePopup", 1,
                                          iniPath.c_str()) != 0;

  g_dialogueSpeedSeconds =
      GetPrivateProfileIntA("Settings", "DialogueSpeed", 8, iniPath.c_str());

  char bubbleLifeBuf[32];
  GetPrivateProfileStringA("Settings", "SpeechBubbleLife", "15.0", bubbleLifeBuf,
                           32, iniPath.c_str());
  g_speechBubbleLife = (float)atof(bubbleLifeBuf);

  Log("CONFIG: Loaded ProximityRadius=" + ToString(g_proximityRadius) +
      ", RadiantRange=" + ToString(g_radiantRange) +
      ", YellRadius=" + ToString(g_yellRadius) +
      ", AmbientInterval=" + ToString(g_ambientIntervalSeconds) + "s" +
      ", EnableAmbient=" + (g_enableAmbient ? "true" : "false") +
      ", BubbleLife=" + ToString(g_speechBubbleLife) + "s" +
      ", Hotkey=" + g_chatHotkeyStr);

  // Note: We no longer call SavePluginConfig() here to avoid race conditions
  // during initialization with the Python server, which also populates defaults.
}

void SavePluginConfig() {
  std::string iniPath = g_modRoot + "\\SentientSands_Config.ini";

  WritePrivateProfileStringA("Settings", "ChatHotkey", g_chatHotkeyStr.c_str(),
                             iniPath.c_str());
  WritePrivateProfileStringA("Settings", "Language", g_language.c_str(),
                             iniPath.c_str());
  WritePrivateProfileStringA("Settings", "RadiantRange",
                             ToString((int)g_radiantRange).c_str(),
                             iniPath.c_str());
  WritePrivateProfileStringA("Settings", "TalkRadius",
                             ToString((int)g_proximityRadius).c_str(),
                             iniPath.c_str());
  WritePrivateProfileStringA("Settings", "YellRadius",
                             ToString((int)g_yellRadius).c_str(),
                             iniPath.c_str());
  WritePrivateProfileStringA("Settings", "RadiantDelay",
                             ToString(g_ambientIntervalSeconds).c_str(),
                             iniPath.c_str());
  WritePrivateProfileStringA("Settings", "EnableAmbientConversations",
                             g_enableAmbient ? "1" : "0", iniPath.c_str());
  WritePrivateProfileStringA("Settings", "EnableWelcomePopup",
                             g_enableWelcome ? "1" : "0", iniPath.c_str());
  WritePrivateProfileStringA("Settings", "GlobalEventsCount",
                             ToString(g_worldEventIntervalDays).c_str(),
                             iniPath.c_str());
  WritePrivateProfileStringA("Settings", "DialogueSpeed",
                             ToString(g_dialogueSpeedSeconds).c_str(),
                             iniPath.c_str());
  WritePrivateProfileStringA("Settings", "SpeechBubbleLife",
                             ToString(g_speechBubbleLife).c_str(),
                             iniPath.c_str());

  Log("CONFIG: Saved full settings state to INI.");
}

void StartPythonServer() {
  Log("SYSTEM: Starting Python server...");

  // Use g_modRoot (the DLL's own directory) so this works for both regular
  // mods/SentientSands/ installs and Steam Workshop numeric-ID folders.
  std::string localPython = g_modRoot + "\\server\\python\\python.exe";
  std::string serverScript =
      g_modRoot + "\\server\\scripts\\kenshi_llm_server.py";

  Log("SYSTEM: Python path: " + localPython);
  Log("SYSTEM: Server script: " + serverScript);

  DWORD fileAttr = GetFileAttributesA(localPython.c_str());
  if (fileAttr != INVALID_FILE_ATTRIBUTES &&
      !(fileAttr & FILE_ATTRIBUTE_DIRECTORY)) {
    Log("SYSTEM: Using embedded Python runtime.");
    std::string cmd = "\"" + localPython + "\" \"" + serverScript + "\"";
    WinExec(cmd.c_str(), SW_HIDE);
  } else {
    // Check if python is in system PATH
    int result = system("python --version >nul 2>&1");
    if (result == 0) {
      Log("SYSTEM: Local Python not found, falling back to global 'python'.");
      WinExec(("python \"" + serverScript + "\"").c_str(), SW_HIDE);
    } else {
      Log("ERROR: No Python installation found!");
      MessageBoxA(
          NULL,
          "Sentient Sands requires a Python engine to connect to AI "
          "models, but no Python installation was found!\n\n"
          "Please go to your mod directory and run 'Install_Python.bat' "
          "to download the local engine, then restart the game.",
          "Sentient Sands - Python Missing", MB_ICONERROR | MB_OK);
    }
  }
}
void LogGameEvent(const std::string &type, const std::string &actor,
                  const std::string &actorFaction, const std::string &target,
                  const std::string &targetFaction,
                  const std::string &message) {
  EnterCriticalSection(&g_eventMutex);
  GameEvent ev;
  ev.type = type;
  ev.actor = actor;
  ev.actorFaction = actorFaction;
  ev.target = target;
  ev.targetFaction = targetFaction;
  ev.message = message;
  ev.timestamp = GetTickCount();
  g_gameEvents.push_back(ev);
  if (g_gameEvents.size() > 100) {
    g_gameEvents.pop_front();
  }
  LeaveCriticalSection(&g_eventMutex);

  std::string logMsg = "[EVENT] " + type + ": " + actor;
  if (!actorFaction.empty() && actorFaction != "None")
    logMsg += " (" + actorFaction + ")";
  logMsg += " -> " + target;
  if (!targetFaction.empty() && targetFaction != "None")
    logMsg += " (" + targetFaction + ")";
  logMsg += " (" + message + ")";
  Log(logMsg);
}

#include "../RE_Kenshi_Source/KenshiLib/Include/kenshi/GameWorld.h"
void SleepIfPaused(DWORD ms) {
  DWORD start = GetTickCount();
  while (GetTickCount() - start < ms) {
    if (ppWorld && *ppWorld && (*ppWorld)->isPaused()) {
      Sleep(100);
      start +=
          100; // Shift start so the actual message delay remains consistent
      continue;
    }
    Sleep(100);
  }
}
