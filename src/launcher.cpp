
#define WIN32_LEAN_AND_MEAN
#include <cstdio>
#include <cstring>
#include <string>
#include <tlhelp32.h>
#include <windows.h>


bool InjectDLL(DWORD procID, const char *dllPath) {
  HANDLE hProc = OpenProcess(PROCESS_ALL_ACCESS, FALSE, procID);
  if (!hProc)
    return false;

  void *loc = VirtualAllocEx(hProc, 0, strlen(dllPath) + 1,
                             MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
  if (!loc) {
    CloseHandle(hProc);
    return false;
  }

  WriteProcessMemory(hProc, loc, dllPath, strlen(dllPath) + 1, 0);

  HMODULE hKernel32 = GetModuleHandleA("kernel32.dll");
  FARPROC pLoadLibrary = GetProcAddress(hKernel32, "LoadLibraryA");

  HANDLE hThread = CreateRemoteThread(
      hProc, 0, 0, (LPTHREAD_START_ROUTINE)pLoadLibrary, loc, 0, 0);

  if (!hThread) {
    VirtualFreeEx(hProc, loc, 0, MEM_RELEASE);
    CloseHandle(hProc);
    return false;
  }

  WaitForSingleObject(hThread, INFINITE);

  CloseHandle(hThread);
  CloseHandle(hProc);
  return true;
}

int main() {
  printf("--- Kenshi AI Standalone Launcher ---\n");

  STARTUPINFOA si;
  PROCESS_INFORMATION pi;
  ZeroMemory(&si, sizeof(si));
  si.cb = sizeof(si);
  ZeroMemory(&pi, sizeof(pi));

  char cmd[] = "Kenshi_x64.exe";

  if (CreateProcessA(NULL, cmd, NULL, NULL, FALSE, CREATE_SUSPENDED, NULL, NULL,
                     &si, &pi)) {
    printf("Kenshi started (Suspended). PID: %lu\n",
           (unsigned long)pi.dwProcessId);

    char path[MAX_PATH];
    if (GetFullPathNameA("SentientSands.dll", MAX_PATH, path, NULL)) {
      if (InjectDLL(pi.dwProcessId, path)) {
        printf("AI Plugin Injected: %s\n", path);
      } else {
        printf("Injection FAILED!\n");
      }
    }

    ResumeThread(pi.hThread);
    printf("Kenshi Resumed. Enjoy the AI conversation!\n");

    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);
  } else {
    printf("Failed to start Kenshi_x64.exe (Error: %lu). Ensure launcher is in "
           "Kenshi folder.\n",
           GetLastError());
  }

  Sleep(3000);
  return 0;
}
