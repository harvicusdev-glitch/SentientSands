using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.IO;
using System.Threading;

class SentientSandsLauncher {
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern IntPtr OpenProcess(uint dwDesiredAccess, bool bInheritHandle, int dwProcessId);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern IntPtr VirtualAllocEx(IntPtr hProcess, IntPtr lpAddress, uint dwSize, uint flAllocationType, uint flProtect);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool WriteProcessMemory(IntPtr hProcess, IntPtr lpBaseAddress, byte[] lpBuffer, uint nSize, out IntPtr lpNumberOfBytesWritten);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern IntPtr GetModuleHandle(string lpModuleName);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern IntPtr GetProcAddress(IntPtr hModule, string procName);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern IntPtr CreateRemoteThread(IntPtr hProcess, IntPtr lpThreadAttributes, uint dwStackSize, IntPtr lpStartAddress, IntPtr lpParameter, uint dwCreationFlags, IntPtr lpThreadId);

    const uint PROCESS_ALL_ACCESS = 0x1F0FFF;
    const uint MEM_COMMIT = 0x1000;
    const uint MEM_RESERVE = 0x2000;
    const uint PAGE_READWRITE = 0x40;

    static void Main() {
        Console.WriteLine("--- Kenshi AI Standalone Launcher (C#) ---");
        
        string exeName = "Kenshi_x64.exe";
        string dllName = "SentientSands.dll";

        if (!File.Exists(exeName)) {
            Console.WriteLine("Error: Kenshi_x64.exe not found in current directory!");
            Thread.Sleep(3000);
            return;
        }

        Process startInfo = new Process();
        startInfo.StartInfo.FileName = exeName;
        startInfo.Start();
        
        Console.WriteLine("Kenshi started. PID: " + startInfo.Id);
        
        string fullDllPath = Path.GetFullPath(dllName);
        if (!File.Exists(fullDllPath)) {
            Console.WriteLine("Error: " + dllName + " not found!");
            Thread.Sleep(3000);
            return;
        }

        // Wait a bit for game to initialize
        Thread.Sleep(2000);

        IntPtr hProc = OpenProcess(PROCESS_ALL_ACCESS, false, startInfo.Id);
        if (hProc == IntPtr.Zero) {
            Console.WriteLine("Error: Could not open process for injection.");
            return;
        }

        IntPtr loc = VirtualAllocEx(hProc, IntPtr.Zero, (uint)fullDllPath.Length + 1, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        IntPtr bytesWritten;
        WriteProcessMemory(hProc, loc, Encoding.ASCII.GetBytes(fullDllPath), (uint)fullDllPath.Length + 1, out bytesWritten);

        IntPtr loadLibAddr = GetProcAddress(GetModuleHandle("kernel32.dll"), "LoadLibraryA");
        IntPtr hThread = CreateRemoteThread(hProc, IntPtr.Zero, 0, loadLibAddr, loc, 0, IntPtr.Zero);

        if (hThread != IntPtr.Zero) {
            Console.WriteLine("Success: AI Plugin Injected!");
        } else {
            Console.WriteLine("Error: Injection failed.");
        }

        Thread.Sleep(3000);
    }
}
