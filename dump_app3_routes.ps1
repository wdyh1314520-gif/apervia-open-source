param(
  [string]$OutFile = "",
  [switch]$Markdown
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Files = @((Join-Path $Root "app3.py")) + @(Get-ChildItem -LiteralPath (Join-Path $Root "app3_parts") -Filter "*.py" -File | Sort-Object Name | ForEach-Object { $_.FullName })

function Get-RelativePath {
  param([string]$Path)
  return $Path.Substring($Root.Length + 1).Replace("\", "/")
}

$rows = New-Object System.Collections.Generic.List[object]

foreach ($file in $Files) {
  if (!(Test-Path -LiteralPath $file)) { continue }
  $rel = Get-RelativePath $file
  $lines = [System.IO.File]::ReadAllLines($file)

  for ($i = 0; $i -lt $lines.Count; $i++) {
    $line = $lines[$i]

    if ($line -match '^\s*@app\.(route|get|post|put|delete|patch)\((.+)\)') {
      $kind = $Matches[1]
      $decorator = $line.Trim()
      $handler = ""
      for ($j = $i + 1; $j -lt [Math]::Min($i + 8, $lines.Count); $j++) {
        if ($lines[$j] -match '^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(') {
          $handler = $Matches[1]
          break
        }
      }
      $rows.Add([PSCustomObject]@{
        Type = "decorator"
        Method = $kind.ToUpperInvariant()
        Route = $decorator
        Handler = $handler
        File = $rel
        Line = $i + 1
      }) | Out-Null
      continue
    }

    if ($line -match "app\.add_url_rule\((.+)") {
      $entry = $line.Trim()
      $handler = ""
      if ($entry -match "add_url_rule\([^,]+,\s*['""]([^'""]+)['""]") {
        $handler = $Matches[1]
      }
      $rows.Add([PSCustomObject]@{
        Type = "dynamic"
        Method = "ADD_URL_RULE"
        Route = $entry
        Handler = $handler
        File = $rel
        Line = $i + 1
      }) | Out-Null
      continue
    }

    if ($line -match "app\.view_functions\[['""]([^'""]+)['""]\]\s*=") {
      $rows.Add([PSCustomObject]@{
        Type = "override"
        Method = "VIEW_FUNCTION"
        Route = $line.Trim()
        Handler = $Matches[1]
        File = $rel
        Line = $i + 1
      }) | Out-Null
    }
  }
}

$sorted = @($rows | Sort-Object Type, File, Line)

if ($Markdown) {
  $output = New-Object System.Collections.Generic.List[string]
  $output.Add("| Type | Method | Handler | File | Line | Route |") | Out-Null
  $output.Add("| --- | --- | --- | --- | ---: | --- |") | Out-Null
  foreach ($row in $sorted) {
    $route = ([string]$row.Route).Replace("|", "\|")
    $output.Add("| $($row.Type) | $($row.Method) | `$($row.Handler)` | `$($row.File)` | $($row.Line) | `$route` |") | Out-Null
  }
  $text = $output -join [Environment]::NewLine
} else {
  $text = ($sorted | Format-Table -AutoSize | Out-String).TrimEnd()
}

if ($OutFile) {
  $target = if ([System.IO.Path]::IsPathRooted($OutFile)) { $OutFile } else { Join-Path $Root $OutFile }
  [System.IO.File]::WriteAllText($target, $text + [Environment]::NewLine, [System.Text.Encoding]::UTF8)
  Write-Host "Wrote route scan: $target"
} else {
  $text
}

Write-Host ("Route entries: {0}" -f $sorted.Count)
