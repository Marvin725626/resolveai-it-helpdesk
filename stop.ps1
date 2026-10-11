$ErrorActionPreference = 'Stop'
$resolveRecord = Join-Path $PSScriptRoot '.local\processes.json'
if (!(Test-Path -LiteralPath $resolveRecord)) { Write-Output 'No recorded ResolveAI processes.'; exit }
$resolveIds = Get-Content -LiteralPath $resolveRecord -Raw | ConvertFrom-Json
foreach ($resolveId in @($resolveIds.api, $resolveIds.web)) {
    $resolveProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$resolveId" -ErrorAction SilentlyContinue
    if ($resolveProcess -and $resolveProcess.CommandLine -and $resolveProcess.CommandLine.Contains($PSScriptRoot)) {
        Stop-Process -Id $resolveId
    }
}
Write-Output 'Stopped recorded ResolveAI processes.'
