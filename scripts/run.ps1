$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"

$projectPython = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $projectPython)) {
    $projectPython = "python"
}

& $projectPython -c "import streamlit" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "缺少依赖，正在从 requirements.txt 安装..."
    & $projectPython -m pip install -r requirements.txt
}

& $projectPython -m streamlit run app.py
