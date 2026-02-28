#include "llm_client.h"
#include <atomic>
#include <condition_variable>
#include <iostream>
#include <map>
#include <mutex>
#include <queue>
#include <sstream>
#include <thread>
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
static std::mutex gPendingMutex;
static std::mutex gFinishedMutex;
static std::condition_variable gPendingCV;
static std::thread gWorkerThread;
static std::atomic<bool> gQuitWorker(false);
static bool gWorkerStarted = false;

// Helper to escape JSON strings
std::string escapeJson(const std::string &input) {
  std::string output;
  for (char c : input) {
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

static void llmWorkerMain() {
  while (!gQuitWorker) {
    LLMRequest req;
    {
      std::unique_lock<std::mutex> lock(gPendingMutex);
      gPendingCV.wait_for(lock, std::chrono::milliseconds(100), [] {
        return !gPendingRequests.empty() || gQuitWorker;
      });
      if (gQuitWorker && gPendingRequests.empty())
        break;
      if (gPendingRequests.empty())
        continue;
      req = gPendingRequests.front();
      gPendingRequests.pop();
    }

    LLMResponse res = talkToLLMSync(req.npcName, req.playerName, req.context,
                                    req.playerInput);
    {
      std::lock_guard<std::mutex> lock(gFinishedMutex);
      gFinishedResponses.push(res);
    }
  }
}

static void startWorkerIfNeeded() {
  if (!gWorkerStarted) {
    gQuitWorker = false;
    gWorkerThread = std::thread(llmWorkerMain);
    gWorkerStarted = true;
  }
}

void talksToLLMAsync(const char *npcName, const char *playerName,
                     const char *context, const char *playerInput) {
  startWorkerIfNeeded();
  std::lock_guard<std::mutex> lock(gPendingMutex);
  gPendingRequests.push({LLM_CHAT, npcName ? npcName : "Unknown",
                         playerName ? playerName : "Player",
                         context ? context : "Dialogue",
                         playerInput ? playerInput : ""});
  gPendingCV.notify_one();
}

bool llmGetNextResponse(LLMResponse &outResponse) {
  std::lock_guard<std::mutex> lock(gFinishedMutex);
  if (gFinishedResponses.empty())
    return false;
  outResponse = gFinishedResponses.front();
  gFinishedResponses.pop();
  return true;
}

void llmCleanup() {
  if (gWorkerStarted) {
    gQuitWorker = true;
    gPendingCV.notify_all();
    if (gWorkerThread.joinable())
      gWorkerThread.join();
    gWorkerStarted = false;
  }
}

} // namespace SentientSands
