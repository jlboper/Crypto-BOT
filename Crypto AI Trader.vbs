Option Explicit

Dim shell, fso, projectRoot, managerScript, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

projectRoot = fso.GetParentFolderName(WScript.ScriptFullName)
managerScript = fso.BuildPath(projectRoot, "scripts\manager_windows.ps1")

If Not fso.FileExists(managerScript) Then
    MsgBox "No se encontró scripts\manager_windows.ps1", 16, "Crypto AI Trader"
    WScript.Quit 1
End If

command = "powershell.exe -NoLogo -NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & managerScript & """"
If WScript.Arguments.Named.Exists("minimized") Then
    command = command & " -Minimized"
End If
shell.Run command, 0, False
