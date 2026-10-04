' يشغّل وسيط جهاز المؤسس مخفياً تماماً (بلا نافذة) ثم يقفل.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
sh.Run "py -m uv run --no-sync python -m relay.home_agent", 0, True
