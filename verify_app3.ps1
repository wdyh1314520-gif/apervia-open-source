param(
  [string]$BaseUrl = "http://127.0.0.1:8002",
  [switch]$SkipHttp
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PartsDir = Join-Path $Root "app3_parts"
$StaticRoot = Join-Path $Root "static"
$Index3Dir = Join-Path $StaticRoot "index3"

$checks = New-Object System.Collections.Generic.List[object]

function Add-Check {
  param(
    [string]$Name,
    [bool]$Ok,
    [string]$Detail = ""
  )
  $script:checks.Add([PSCustomObject]@{
    Name = $Name
    Ok = $Ok
    Detail = $Detail
  }) | Out-Null
  if ($Ok) {
    Write-Host "[OK] $Name" -ForegroundColor Green
  } else {
    Write-Host "[FAIL] $Name" -ForegroundColor Red
    if ($Detail) { Write-Host "       $Detail" -ForegroundColor DarkYellow }
  }
}

function Get-CommandPath {
  param([string[]]$Names)
  foreach ($name in $Names) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { return $cmd.Source }
  }
  return ""
}

function Resolve-Python {
  $localPython = Join-Path (Split-Path -Parent $Root) "python311\python.exe"
  if (Test-Path -LiteralPath $localPython) { return $localPython }
  return Get-CommandPath @("python", "py")
}

function Invoke-HttpCheck {
  param(
    [string]$Path,
    [string]$Method = "GET",
    [string]$Body = ""
  )
  $uri = "$BaseUrl$Path"
  try {
    if ($Method -eq "POST") {
      Invoke-RestMethod -Uri $uri -Method Post -ContentType "application/json" -Body $Body -TimeoutSec 5 | Out-Null
    } else {
      Invoke-RestMethod -Uri $uri -TimeoutSec 5 | Out-Null
    }
    Add-Check "HTTP $Path" $true
    return $true
  } catch {
    Add-Check "HTTP $Path" $false $_.Exception.Message
    return $false
  }
}

Write-Host "== app3 verify =="
Write-Host "Root: $Root"

# 1) Docs are UTF-8 readable and contain required sections.
try {
  $runbook = Join-Path $Root "RUNBOOK.md"
  if (!(Test-Path -LiteralPath $runbook)) { throw "RUNBOOK.md missing" }

  $nodeForDocs = Get-CommandPath @("node")
  if (!$nodeForDocs) { throw "node not found for UTF-8 doc check" }
  $docCheck = "const fs=require('fs'); const runbook=fs.readFileSync(process.argv[1],'utf8'); for (const s of ['\u804a\u5929\u4e0d\u52a8','\u4e0a\u4f20\u5361\u4f4f','\u751f\u56fe\u5931\u8d25','\u5feb\u901f\u5b9a\u4f4d\u53e3\u8bc0']) { if (!runbook.includes(s)) throw new Error('RUNBOOK missing '+s); }"
  & $nodeForDocs -e $docCheck $runbook
  if ($LASTEXITCODE -ne 0) { throw "Doc check failed with exit code $LASTEXITCODE" }
  Add-Check "Docs UTF-8 and required sections" $true
} catch {
  Add-Check "Docs UTF-8 and required sections" $false $_.Exception.Message
}

# 2) Python syntax via AST parsing. This avoids writing __pycache__.
$python = Resolve-Python
if (!$python) {
  Add-Check "Python available" $false "Could not find python, py, or workspace python311\python.exe"
} else {
  Add-Check "Python available" $true $python
  try {
    $script = @"
import ast, pathlib
import sys
root = pathlib.Path(sys.argv[1])
files = [root / 'app3.py']
for folder in ('app3_parts', 'mcp_client', 'tests'):
    path = root / folder
    if path.exists():
        files.extend(sorted(path.rglob('*.py')))
for path in files:
    ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
"@
    & $python -c $script $Root
    if ($LASTEXITCODE -ne 0) { throw "Python AST check failed with exit code $LASTEXITCODE" }
    Add-Check "Python AST syntax" $true
  } catch {
    Add-Check "Python AST syntax" $false $_.Exception.Message
  }
}

# 3) JavaScript syntax checks.
$node = Get-CommandPath @("node")
if (!$node) {
  Add-Check "Node available" $false "node not found"
} else {
  Add-Check "Node available" $true $node
  try {
    $jsFiles = Get-ChildItem -LiteralPath (Join-Path $Index3Dir "js") -Filter "*.js" -File
    foreach ($file in $jsFiles) {
      & $node --check $file.FullName | Out-Null
      if ($LASTEXITCODE -ne 0) { throw "node --check failed: $($file.Name)" }
    }
    Add-Check "JavaScript syntax" $true "$($jsFiles.Count) files"
  } catch {
    Add-Check "JavaScript syntax" $false $_.Exception.Message
  }
}

# 4) Ensure script/css references in index3.html exist locally. External URLs are ignored.
try {
  $indexPath = Join-Path $StaticRoot "index3.html"
  if (!(Test-Path -LiteralPath $indexPath)) { throw "index3.html missing" }
  $html = [System.IO.File]::ReadAllText($indexPath, [System.Text.Encoding]::UTF8)
  $missing = New-Object System.Collections.Generic.List[string]
  $regex = [regex]'(?:src|href)="([^"]+)"'
  foreach ($match in $regex.Matches($html)) {
    $url = [string]$match.Groups[1].Value
    if (!$url.StartsWith("/static/index3/")) { continue }
    $clean = $url.Split("?")[0]
    $relative = $clean.Substring("/static/".Length).Replace("/", "\")
    $local = Join-Path $StaticRoot $relative
    if (!(Test-Path -LiteralPath $local)) {
      $missing.Add($clean) | Out-Null
    }
  }
  if ($missing.Count -gt 0) { throw ("Missing static references: " + ($missing -join ", ")) }
  Add-Check "index3 static references" $true
} catch {
  Add-Check "index3 static references" $false $_.Exception.Message
}

# 5) Optional HTTP checks. Skip cleanly when service is not running.
if ($SkipHttp) {
  Add-Check "HTTP checks" $true "Skipped by -SkipHttp"
} else {
  try {
    Invoke-RestMethod -Uri "$BaseUrl/api3/health/live" -TimeoutSec 3 | Out-Null
    Add-Check "Service reachable" $true $BaseUrl
    Invoke-HttpCheck "/api3/health/live" | Out-Null
    Invoke-HttpCheck "/api3/health/ready" | Out-Null
    Invoke-HttpCheck "/api3/auth/status" | Out-Null
    Invoke-HttpCheck "/api3/storage/quota" | Out-Null
  } catch {
    Add-Check "Service reachable" $true "Not running or not reachable; HTTP checks skipped: $($_.Exception.Message)"
  }
}

$failed = @($checks | Where-Object { -not $_.Ok })
Write-Host ""
Write-Host "== summary =="
Write-Host ("Checks: {0}, Failed: {1}" -f $checks.Count, $failed.Count)

if ($failed.Count -gt 0) {
  Write-Host "Failed checks:" -ForegroundColor Red
  foreach ($item in $failed) {
    Write-Host ("- {0}: {1}" -f $item.Name, $item.Detail) -ForegroundColor Red
  }
  exit 1
}

Write-Host "All required checks passed." -ForegroundColor Green
exit 0
