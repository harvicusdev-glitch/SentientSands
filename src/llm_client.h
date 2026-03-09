#pragma once

#include <map>
#include <string>
#include <vector>

namespace SentientSands {

struct LLMResponse {
  int objId;
  std::string text;
};

// Async chat request (Using const char* to be binary safe)
void talksToLLMAsync(const char *npcName, const char *playerName,
                     const char *context, const char *playerInput);

// Check for responses (poll in update loop)
bool llmGetNextResponse(LLMResponse &outResponse);

void llmCleanup();

} // namespace SentientSands
