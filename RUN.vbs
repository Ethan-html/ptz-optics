Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
runBat = """" & scriptDir & "\RUN.bat"""

' Check if port 8080 is already in use
Set objExec = WshShell.Exec("cmd /c netstat -ano | findstr :8080")

If Not objExec.StdOut.AtEndOfStream Then
    ' Server already running → just open browser
    WshShell.Run "http://localhost:8080"
Else
    ' Not running → start the server hidden
    WshShell.Run "cmd /c " & runBat, 0
End If

Set WshShell = Nothing
Set fso = Nothing