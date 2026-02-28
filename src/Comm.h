#pragma once
#include <string>
#include <windows.h>

DWORD WINAPI PipeThread(LPVOID lpParam);
void AsyncPostToPython(const std::wstring &endpoint,
                       const std::string &jsonData);
void PostToPython(const std::wstring &endpoint, const std::string &jsonData);
std::string PostToPythonWithResponse(const std::wstring &endpoint,
                                     const std::string &jsonData);
DWORD WINAPI AmbientPollThread(LPVOID lpParam);
