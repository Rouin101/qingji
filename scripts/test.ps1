$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"

$projectPython = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $projectPython)) {
    $projectPython = "python"
}

& $projectPython -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $projectPython -m compileall -q app.py qingji pages scripts tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $projectPython scripts\e2e_apptest.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $projectPython scripts\eval_retrieval.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
