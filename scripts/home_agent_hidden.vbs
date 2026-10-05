' يشغّل وسيط جهاز المؤسس مخفياً تماماً (بلا نافذة) ثم يقفل.
' يستدعي بايثون المشروع نفسه مباشرة (لا يعتمد على أدوات مثبتة في مكان آخر)، والأخطاء تُكتب في السجل.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
sh.Run "cmd /c .venv\Scripts\python.exe -m relay.home_agent >> state\home_agent_run.log 2>&1", 0, True
