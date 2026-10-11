param([int]$ApiPort = 8104, [int]$WebPort = 5174)
$ErrorActionPreference = 'Stop'
$resolveRoot = $PSScriptRoot
$resolvePython = Join-Path $resolveRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $resolvePython)) { throw 'Create .venv and install backend/requirements.txt first; see README.md.' }
$resolveNode = Get-Command node -ErrorAction SilentlyContinue
if (!$resolveNode -and (Test-Path -LiteralPath 'E:\agent\tools\node-v22.22.3-win-x64\node.exe')) {
    $env:PATH = 'E:\agent\tools\node-v22.22.3-win-x64;' + $env:PATH
    $resolveNode = Get-Command node
}
if (!$resolveNode) { throw 'Node.js 22+ is required; see README.md.' }
foreach ($resolvePort in @($ApiPort, $WebPort)) {
    if (Get-NetTCPConnection -State Listen -LocalPort $resolvePort -ErrorAction SilentlyContinue) { throw "Port $resolvePort is already in use. Stop the old ResolveAI processes or choose another port." }
}
$resolveLog = Join-Path $resolveRoot '.local\logs'
New-Item -ItemType Directory -Force -Path $resolveLog | Out-Null
$env:RESOLVEAI_API_URL = "http://127.0.0.1:$ApiPort"
$resolveApi = Start-Process -FilePath $resolvePython -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port',"$ApiPort") -WorkingDirectory (Join-Path $resolveRoot 'backend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $resolveLog 'api.out.log') -RedirectStandardError (Join-Path $resolveLog 'api.err.log')
try {
    $resolveApiReady = $false
    for ($resolveAttempt = 0; $resolveAttempt -lt 30; $resolveAttempt++) {
        if ($resolveApi.HasExited) { throw 'Backend exited during startup; inspect .local/logs/api.err.log.' }
        try {
            $resolveHealth = Invoke-WebRequest -Uri "http://127.0.0.1:$ApiPort/api/v1/health" -TimeoutSec 1 -UseBasicParsing
            if ($resolveHealth.StatusCode -eq 200) { $resolveApiReady = $true; break }
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if (!$resolveApiReady) { throw 'Backend did not become ready; inspect .local/logs/api.err.log.' }
    $resolveVite = Join-Path $resolveRoot 'frontend\node_modules\vite\bin\vite.js'
    $resolveWebArgs = @("`"$resolveVite`"", '--host', '127.0.0.1', '--port', "$WebPort", '--strictPort')
    $resolveWeb = Start-Process -FilePath $resolveNode.Source -ArgumentList $resolveWebArgs -WorkingDirectory (Join-Path $resolveRoot 'frontend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $resolveLog 'web.out.log') -RedirectStandardError (Join-Path $resolveLog 'web.err.log')
    $resolveWebReady = $false
    for ($resolveAttempt = 0; $resolveAttempt -lt 20; $resolveAttempt++) {
        if ($resolveWeb.HasExited) { throw 'Frontend exited during startup; inspect .local/logs/web.err.log.' }
        try {
            $resolvePage = Invoke-WebRequest -Uri "http://127.0.0.1:$WebPort" -TimeoutSec 1 -UseBasicParsing
            if ($resolvePage.StatusCode -eq 200) { $resolveWebReady = $true; break }
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if (!$resolveWebReady) { throw 'Frontend did not become ready; inspect .local/logs/web.err.log.' }
    @{ api = $resolveApi.Id; web = $resolveWeb.Id; api_port = $ApiPort; web_port = $WebPort } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $resolveRoot '.local\processes.json')
    Write-Output "ResolveAI: http://127.0.0.1:$WebPort | API: http://127.0.0.1:$ApiPort/docs"
} catch {
    Stop-Process -Id $resolveApi.Id -ErrorAction SilentlyContinue
    if ($resolveWeb) { Stop-Process -Id $resolveWeb.Id -ErrorAction SilentlyContinue }
    throw
}
