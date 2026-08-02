Option Explicit

Dim shell, files, installDir, logPath, command, url, ready, attempt, request
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")

installDir = files.GetParentFolderName(WScript.ScriptFullName)
logPath = files.BuildPath(installDir, "dashboard-launch.log")
url = "http://127.0.0.1:7871/"

' Start an already-installed Docker environment without showing a terminal.
' The installer owns builds and updates; this launcher only starts the app.
command = "cmd.exe /d /s /c ""cd /d """ & installDir & """ && docker compose up -d >> """ & logPath & """ 2>&1"""
shell.Run command, 0, True

ready = False
For attempt = 1 To 60
    On Error Resume Next
    Set request = CreateObject("MSXML2.XMLHTTP")
    request.Open "GET", url, False
    request.Send
    If Err.Number = 0 Then
        If request.Status >= 200 And request.Status < 500 Then ready = True
    End If
    Err.Clear
    On Error GoTo 0
    If ready Then Exit For
    WScript.Sleep 2000
Next

shell.Run url, 1, False
