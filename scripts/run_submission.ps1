param(
    [switch]$ResetDemo
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$submissionData = Join-Path $projectRoot "data\submission"

if ($ResetDemo -and (Test-Path -LiteralPath $submissionData)) {
    $resolvedSubmissionData = (Resolve-Path -LiteralPath $submissionData).Path
    $expectedSubmissionData = [System.IO.Path]::GetFullPath(
        (Join-Path $projectRoot "data\submission")
    )
    if ($resolvedSubmissionData -ne $expectedSubmissionData) {
        throw "拒绝重置：参赛数据目录不在预期位置。"
    }
    Remove-Item -LiteralPath $resolvedSubmissionData -Recurse -Force
}

New-Item -ItemType Directory -Path $submissionData -Force | Out-Null
$env:QINGJI_DATA_DIR = $submissionData
$env:QINGJI_DEMO_MODE = "true"

$projectPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $projectPython)) {
    $projectPython = "python"
}

& $projectPython -c "import streamlit" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "缺少依赖，正在从 requirements.txt 安装..."
    & $projectPython -m pip install -r (Join-Path $projectRoot "requirements.txt")
}

Set-Location -LiteralPath $projectRoot
& $projectPython -m streamlit run app.py
