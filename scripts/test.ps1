$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"

$projectPython = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $projectPython)) {
    $projectPython = "python"
}

& $projectPython -m unittest discover -s tests -v
& $projectPython -m compileall -q app.py qingji pages scripts tests
& $projectPython scripts\e2e_apptest.py
