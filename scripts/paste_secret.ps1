# يأخذ المنسوخ من الحافظة ويحفظه في secrets.local.env تحت الاسم المطلوب
param([Parameter(Mandatory)][string]$Name, [switch]$Quiet)
Add-Type -AssemblyName PresentationFramework
$file = Join-Path $PSScriptRoot "..\secrets.local.env"
$val = (Get-Clipboard -Raw)
if ($val) { $val = $val.Trim() }
$patterns = @{
  GEMINI_API_KEY     = '^AIza[0-9A-Za-z_\-]{30,}$'
  GROQ_API_KEY       = '^gsk_[0-9A-Za-z]{20,}$'
  TELEGRAM_BOT_TOKEN = '^\d{6,}:[0-9A-Za-z_\-]{30,}$'
}
if (-not $val -or ($patterns.ContainsKey($Name) -and $val -notmatch $patterns[$Name])) {
  if ($Quiet) { Write-Output "BAD" } else { [System.Windows.MessageBox]::Show("المنسوخ مو هو المفتاح المطلوب.`nارجع انسخه مرة ثانية ثم اضغط هنا من جديد.", "راصد", "OK", "Warning") | Out-Null }
  exit 1
}
$lines = @()
if (Test-Path $file) { $lines = @(Get-Content $file -Encoding UTF8 | Where-Object { $_ -notmatch "^$Name=" }) }
$lines += "$Name=$val"
[System.IO.File]::WriteAllLines((Resolve-Path -LiteralPath (Split-Path $file)).Path + "\secrets.local.env", $lines, (New-Object System.Text.UTF8Encoding $false))
Set-Clipboard -Value " "
if ($Quiet) { Write-Output "SAVED" } else { [System.Windows.MessageBox]::Show("تم الحفظ ✅`nانتقل للخطوة اللي بعدها.", "راصد", "OK", "Information") | Out-Null }
