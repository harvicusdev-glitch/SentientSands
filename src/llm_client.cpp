#include "llm_client.h"
#include <iostream>
#include <map>
#include <queue>
#include <sstream>
#include <windows.h>
#include <wininet.h>

#pragma comment(lib, "wininet.lib")

namespace SentientSands {

enum LLMRequestType { LLM_CHAT, LLM_LOG };

struct LLMRequest {
  LLMRequestType type;
  std::string npcName;
  std::string playerName;
  std::string context;
  std::string playerInput;
};

static std::queue<LLMRequest> gPendingRequests;
static std::queue<LLMResponse> gFinishedResponses;
static CRITICAL_SECTION gPendingMutex;
static CRITICAL_SECTION gFinishedMutex;
static CONDITION_VARIABLE gPendingCV;
static HANDLE gWorkerThread = NULL;
static volatile LONG gQuitWorker = 0;
static volatile LONG gActiveRequests = 0;
static bool gWorkerStarted = false;

// Helper to escape JSON strings
std::string escapeJson(const std::string &input) {
  std::string output;
  for (size_t i = 0; i < input.length(); ++i) {
    char c = input[i];
    if (c == '"')
      output += "\\\"";
    else if (c == '\\')
      output += "\\\\";
    else if (c == '\b')
      output += "\\b";
    else if (c == '\f')
      output += "\\f";
    else if (c == '\n')
      output += "\\n";
    else if (c == '\r')
      output += "\\r";
    else if (c == '\t')
      output += "\\t";
    else
      output += c;
  }
  return output;
}

static LLMResponse talkToLLMSync(const std::string &npcName,
                                 const std::string &playerName,
                                 const std::string &context,
                                 const std::string &playerInput) {
  LLMResponse response;
  response.objId = 0;

  HINTERNET hSession =
      InternetOpenA("KenshiLLM", INTERNET_OPEN_TYPE_DIRECT, NULL, NULL, 0);
  if (!hSession) {
    response.text = "Error: WinInet Init Failed";
    return response;
  }

  DWORD timeout = 2000;
  InternetSetOptionA(hSession, INTERNET_OPTION_CONNECT_TIMEOUT, &timeout,
                     sizeof(timeout));

  HINTERNET hConnect = InternetConnectA(hSession, "127.0.0.1", 5000, NULL, NULL,
                                        INTERNET_SERVICE_HTTP, 0, 0);
  if (!hConnect) {
    response.text = "Error: Connection Failed (Server down?)";
    InternetCloseHandle(hSession);
    return response;
  }

  const char *acceptTypes[] = {"application/json", NULL};
  HINTERNET hRequest = HttpOpenRequestA(hConnect, "POST", "/chat", NULL, NULL,
                                        acceptTypes, 0, 0);
  if (!hRequest) {
    response.text = "Error: Request Creation Failed";
    InternetCloseHandle(hConnect);
    InternetCloseHandle(hSession);
    return response;
  }

  std::stringstream json;
  json << "{\"npc\": \"" << escapeJson(npcName) << "\", ";
  json << "\"player\": \"" << escapeJson(playerName) << "\", \"context\": \""
       << escapeJson(context) << "\", \"message\": \""
       << escapeJson(playerInput) << "\"}";
  std::string postData = json.str();

  const char *headers = "Content-Type: application/json";

  if (HttpSendRequestA(hRequest, headers, (DWORD)strlen(headers),
                       (LPVOID)postData.c_str(), (DWORD)postData.length())) {
    char buffer[4096];
    DWORD bytesRead;
    std::string fullResponse;
    while (InternetReadFile(hRequest, buffer, sizeof(buffer) - 1, &bytesRead) &&
           bytesRead > 0) {
      buffer[bytesRead] = '\0';
      fullResponse += buffer;
    }

    size_t keyPos = fullResponse.find("\"text\"");
    if (keyPos != std::string::npos) {
      size_t valStart = fullResponse.find("\"", fullResponse.find(":", keyPos));
      if (valStart != std::string::npos) {
        size_t valEnd = fullResponse.find("\"", valStart + 1);
        if (valEnd != std::string::npos) {
          response.text =
              fullResponse.substr(valStart + 1, valEnd - valStart - 1);
        }
      }
    } else {
      response.text = fullResponse;
    }
  } else {
    response.text = "Error: Send Failed";
  }

  InternetCloseHandle(hRequest);
  InternetCloseHandle(hConnect);
  InternetCloseHandle(hSession);
  return response;
}

static DWORD WINAPI llmWorkerMain(LPVOID lpParam) {
  while (true) {
    LLMRequest req;
    
    EnterCriticalSection(&gPendingMutex);
    while (gPendingRequests.empty() && InterlockedCompareExchange(&gQuitWorker, 0, 0) == 0) {
      SleepConditionVariableCS(&gPendingCV, &gPendingMutex, INFINITE);
    }
    if (InterlockedCompareExchange(&gQuitWorker, 1, 1) == 1 && gPendingRequests.empty()) {
      LeaveCriticalSection(&gPendingMutex);
      break;
    }
    req = gPendingRequests.front();
    gPendingRequests.pop();
    LeaveCriticalSection(&gPendingMutex);

    LLMResponse res = talkToLLMSync(req.npcName, req.playerName, req.context,
                                    req.playerInput);
    InterlockedDecrement(&gActiveRequests);
    
    EnterCriticalSection(&gFinishedMutex);
    gFinishedResponses.push(res);
    LeaveCriticalSection(&gFinishedMutex);
  }
  return 0;
}

static void startWorkerIfNeeded() {
  if (!gWorkerStarted) {
    InitializeCriticalSection(&gPendingMutex);
    InitializeCriticalSection(&gFinishedMutex);
    InitializeConditionVariable(&gPendingCV);
    InterlockedExchange(&gQuitWorker, 0);
    gWorkerThread = CreateThread(NULL, 0, llmWorkerMain, NULL, 0, NULL);
    gWorkerStarted = true;
  }
}

void talksToLLMAsync(const char *npcName, const char *playerName,
                     const char *context, const char *playerInput) {
  startWorkerIfNeeded();
  
  EnterCriticalSection(&gPendingMutex);
  InterlockedIncrement(&gActiveRequests);
  LLMRequest req;
  req.type = LLM_CHAT;
  req.npcName = npcName ? npcName : "Unknown";
  req.playerName = playerName ? playerName : "Player";
  req.context = context ? context : "Dialogue";
  req.playerInput = playerInput ? playerInput : "";
  gPendingRequests.push(req);
  LeaveCriticalSection(&gPendingMutex);
  
  WakeConditionVariable(&gPendingCV);
}

bool isLLMActive() {
  return InterlockedCompareExchange(&gActiveRequests, 0, 0) > 0;
}

void llmStartActive() { InterlockedIncrement(&gActiveRequests); }
void llmFinishActive() { InterlockedDecrement(&gActiveRequests); }

bool llmGetNextResponse(LLMResponse &outResponse) {
  EnterCriticalSection(&gFinishedMutex);
  if (gFinishedResponses.empty()) {
    LeaveCriticalSection(&gFinishedMutex);
    return false;
  }
  outResponse = gFinishedResponses.front();
  gFinishedResponses.pop();
  LeaveCriticalSection(&gFinishedMutex);
  return true;
}

void llmCleanup() {
  if (gWorkerStarted) {
    InterlockedExchange(&gQuitWorker, 1);
    WakeAllConditionVariable(&gPendingCV);
    
    if (gWorkerThread != NULL) {
      WaitForSingleObject(gWorkerThread, INFINITE);
      CloseHandle(gWorkerThread);
      gWorkerThread = NULL;
    }
    
    DeleteCriticalSection(&gPendingMutex);
    DeleteCriticalSection(&gFinishedMutex);
    gWorkerStarted = false;
  }
}

} // namespace SentientSands
