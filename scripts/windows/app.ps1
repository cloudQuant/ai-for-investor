[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('start', 'stop', 'restart', 'status', 'doctor', 'help')]
    [string]$Action = 'help',
    [switch]$NoBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$BackendDir = Join-Path $ProjectRoot 'src\backend'
$FrontendDir = Join-Path $ProjectRoot 'src\frontend'
$PidDir = Join-Path $ProjectRoot '.pids'
$LogDir = Join-Path $ProjectRoot 'logs'
$BackendHealthUrl = 'http://127.0.0.1:8000/health'
$FrontendUrl = 'http://127.0.0.1:3000/'
$script:PythonExe = $null
$script:NodeExe = $null

function Write-Info([string]$Message) {
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host "[OK]   $Message" -ForegroundColor Green
}

function Write-Warn([string]$Message) {
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-Problem([string]$Message) {
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Get-CommandPath([string]$Name) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $command) {
        return $null
    }
    if ($command.Source) {
        return $command.Source
    }
    if ($command.Path) {
        return $command.Path
    }
    return $null
}

function Get-PythonExecutable {
    $candidates = New-Object 'System.Collections.Generic.List[string]'

    if (-not [string]::IsNullOrWhiteSpace($env:AI_FOR_INVESTOR_PYTHON)) {
        $candidates.Add($env:AI_FOR_INVESTOR_PYTHON)
    } else {
        @(
            (Join-Path $BackendDir '.venv\Scripts\python.exe'),
            (Join-Path $BackendDir 'venv\Scripts\python.exe'),
            (Join-Path $ProjectRoot '.venv\Scripts\python.exe'),
            (Join-Path $ProjectRoot 'venv\Scripts\python.exe')
        ) | ForEach-Object { $candidates.Add($_) }

        $pyLauncher = Get-CommandPath 'py.exe'
        if ($pyLauncher) {
            $listing = (& $pyLauncher -0p 2>$null | Out-String)
            $available = @()
            foreach ($line in ($listing -split "`r?`n")) {
                if ($line -match '^\s*-V:(\d+\.\d+)\s+\*?\s*(.+?)\s*$') {
                    $available += [pscustomobject]@{
                        version = $Matches[1]
                        path = $Matches[2]
                    }
                }
            }
            foreach ($preferredVersion in @('3.12', '3.11', '3.10', '3.14')) {
                foreach ($installation in @($available | Where-Object { $_.version -eq $preferredVersion })) {
                    if (Test-Path -LiteralPath $installation.path -PathType Leaf) {
                        $candidates.Add([string]$installation.path)
                    }
                }
            }
            foreach ($installation in @($available | Where-Object {
                $_.version -notin @('3.12', '3.11', '3.10', '3.14')
            } | Sort-Object { [version]$_.version } -Descending)) {
                if (Test-Path -LiteralPath $installation.path -PathType Leaf) {
                    $candidates.Add([string]$installation.path)
                }
            }
        }

        $pathPython = Get-CommandPath 'python.exe'
        if ($pathPython) {
            $candidates.Add($pathPython)
        }
    }

    $seen = @{}
    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            continue
        }
        $fullPath = [System.IO.Path]::GetFullPath($candidate)
        $key = $fullPath.ToLowerInvariant()
        if ($seen.ContainsKey($key)) {
            continue
        }
        $seen[$key] = $true

        $versionLine = (& $fullPath --version 2>$null | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or $versionLine -notmatch '^Python\s+(\d+)\.(\d+)') {
            continue
        }
        $major = [int]$Matches[1]
        $minor = [int]$Matches[2]
        if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
            continue
        }
        return $fullPath
    }

    throw '找不到可用的 Python 3.10+。可设置 AI_FOR_INVESTOR_PYTHON，或安装 Python Launcher。'
}

function Get-NodeExecutable {
    $nodePath = Get-CommandPath 'node.exe'
    if (-not $nodePath) {
        $nodePath = Get-CommandPath 'node'
    }
    if (-not $nodePath -or -not (Test-Path -LiteralPath $nodePath -PathType Leaf)) {
        throw '找不到 Node.js。请安装项目要求的 Node.js 20.19+、22.13+ 或 24.x。'
    }

    $versionText = (& $nodePath --version 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $versionText -notmatch '^v(\d+)\.(\d+)\.(\d+)') {
        throw '无法读取 Node.js 版本。'
    }
    $major = [int]$Matches[1]
    $minor = [int]$Matches[2]
    $compatible = ($major -eq 20 -and $minor -ge 19) -or
        ($major -eq 22 -and $minor -ge 13) -or
        ($major -eq 24)
    if (-not $compatible) {
        throw "Node.js $versionText 不符合 src/frontend/package.json 的 engines 要求。"
    }
    return $nodePath
}

function Get-EnvValue([string]$Name) {
    $processValue = [Environment]::GetEnvironmentVariable($Name, 'Process')
    if (-not [string]::IsNullOrWhiteSpace($processValue)) {
        return $processValue.Trim()
    }

    $envFile = Join-Path $BackendDir '.env'
    if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
        return ''
    }
    $pattern = '^\s*' + [regex]::Escape($Name) + '\s*=\s*(.*?)\s*$'
    foreach ($line in [System.IO.File]::ReadAllLines($envFile)) {
        $match = [regex]::Match($line, $pattern)
        if ($match.Success) {
            $value = $match.Groups[1].Value.Trim()
            if ($value.Length -ge 2 -and
                (($value.StartsWith('"') -and $value.EndsWith('"')) -or
                 ($value.StartsWith("'") -and $value.EndsWith("'")))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            return $value
        }
    }
    return ''
}

function Test-PlaceholderSecret([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value) -or $Value.Length -lt 32) {
        return $true
    }
    return $Value -match '^(your-|replace-with-|change-me|changeme|secret-key)'
}

function Test-BackendImport([string]$PythonPath, [ref]$Diagnostic) {
    Push-Location $BackendDir
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = (& $PythonPath -B -c 'import fastapi, uvicorn, sqlalchemy; import app.main' 2>&1 |
            Out-String).Trim()
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
        Pop-Location
    }
    if ($exitCode -ne 0) {
        $knownErrors = @($output -split "`r?`n" | Where-Object {
            $_ -match '^\s*(ModuleNotFoundError|ImportError|SyntaxError|AttributeError|NameError|ValueError|RuntimeError|OSError):'
        } | Select-Object -Last 3)
        if ($knownErrors.Count -gt 0) {
            $Diagnostic.Value = $knownErrors -join [Environment]::NewLine
        } else {
            $Diagnostic.Value = ($output -split "`r?`n" | Select-Object -Last 2) -join [Environment]::NewLine
        }
        return $false
    }
    return $true
}

function Get-PreflightProblems {
    $problems = @()
    $python = $null
    try {
        $python = Get-PythonExecutable
        $script:PythonExe = $python
        Write-Ok "Python: $python"
    } catch {
        $problems += $_.Exception.Message
    }

    try {
        $node = Get-NodeExecutable
        $script:NodeExe = $node
        $nodeVersion = (& $node --version 2>$null | Out-String).Trim()
        Write-Ok "Node.js: $nodeVersion"
    } catch {
        $problems += $_.Exception.Message
    }

    $viteCli = Join-Path $FrontendDir 'node_modules\vite\bin\vite.js'
    if (-not (Test-Path -LiteralPath $viteCli -PathType Leaf)) {
        $problems += '前端依赖未安装。请在 src\frontend 执行 npm ci。'
    } else {
        Write-Ok '前端依赖：已找到 Vite'
    }

    $envFile = Join-Path $BackendDir '.env'
    if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
        $problems += '缺少 src\backend\.env。请从 src\backend\.env.example 复制后配置本地数据库和安全密钥。'
    }
    if ((Get-EnvValue 'DEBUG').ToLowerInvariant() -notin @('true', '1', 'yes', 'on')) {
        $problems += '本地开发启动要求在 src\backend\.env 中设置 DEBUG=true。'
    }
    foreach ($secretName in @('SECRET_KEY', 'JWT_SECRET_KEY')) {
        $secretValue = Get-EnvValue $secretName
        if (Test-PlaceholderSecret $secretValue) {
            $problems += "后端配置 $secretName 缺失、过短或仍是示例值；请在 src\backend\.env 中设置至少 32 字符的随机值。"
        }
    }

    if ($python) {
        $weasyPrintDllDirectories = Get-EnvValue 'WEASYPRINT_DLL_DIRECTORIES'
        if (-not [string]::IsNullOrWhiteSpace($weasyPrintDllDirectories)) {
            $env:WEASYPRINT_DLL_DIRECTORIES = $weasyPrintDllDirectories
        }
        $diagnostic = ''
        if (Test-BackendImport $python ([ref]$diagnostic)) {
            Write-Ok '后端依赖：app.main 可导入'
        } else {
            if ($diagnostic -match 'cannot load library.*libgobject-2\.0-0' -or
                $diagnostic -match 'cannot load library.*libpango') {
                $problems += '缺少 WeasyPrint 的 Windows 原生 Pango/GTK 运行库。请安装 MSYS2，并在 UCRT64 终端执行 pacman -S mingw-w64-ucrt-x86_64-pango；安装后设置 WEASYPRINT_DLL_DIRECTORIES 指向其 ucrt64\bin 目录。'
            } else {
                $problems += '后端依赖或应用导入失败。请在 src\backend 执行 pip install -e ".[dev,backtrader]"。'
            }
            if ($diagnostic) {
                $problems += "后端导入诊断：$diagnostic"
            }
        }
    }

    return $problems
}

function Get-PortListeners([int]$Port) {
    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
        try {
            return @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop)
        } catch {
            return @()
        }
    }
    return @()
}

function Test-PortOpen([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $pending = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        if (-not $pending.AsyncWaitHandle.WaitOne(300)) {
            return $false
        }
        try {
            $client.EndConnect($pending)
            return $true
        } catch {
            return $false
        }
    } finally {
        $client.Close()
    }
}

function Get-StatePath([string]$Service) {
    return Join-Path $PidDir "$Service.json"
}

function Get-LegacyPidPath([string]$Service) {
    return Join-Path $PidDir "$Service.pid"
}

function Read-ServiceState([string]$Service) {
    $statePath = Get-StatePath $Service
    if (Test-Path -LiteralPath $statePath -PathType Leaf) {
        try {
            $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
            if ([int]$state.pid -gt 0) {
                return [pscustomobject]@{
                    pid = [int]$state.pid
                    executable = [string]$state.executable
                    root = [string]$state.root
                    stdout = [string]$state.stdout
                    stderr = [string]$state.stderr
                    legacy = $false
                }
            }
        } catch {
            Write-Warn "忽略无效 PID 记录：$statePath"
        }
    }

    $legacyPath = Get-LegacyPidPath $Service
    if (Test-Path -LiteralPath $legacyPath -PathType Leaf) {
        $text = (Get-Content -LiteralPath $legacyPath -Raw).Trim()
        if ($text -match '^\d+$') {
            return [pscustomobject]@{
                pid = [int]$text
                executable = ''
                root = ''
                stdout = ''
                stderr = ''
                legacy = $true
            }
        }
    }
    return $null
}

function Remove-ServiceState([string]$Service) {
    foreach ($path in @((Get-StatePath $Service), (Get-LegacyPidPath $Service))) {
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            Remove-Item -LiteralPath $path -Force
        }
    }
}

function Get-ProcessRecord([int]$ProcessId) {
    try {
        return Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction Stop
    } catch {
        return $null
    }
}

function Test-ServiceProcess($State, $Process, [string]$Service) {
    if ($null -eq $State -or $null -eq $Process -or
        [string]::IsNullOrWhiteSpace([string]$Process.CommandLine)) {
        return $false
    }
    if (-not $State.legacy -and
        ("$($State.root)".TrimEnd('\') -ine $ProjectRoot.TrimEnd('\'))) {
        return $false
    }

    $commandLine = [string]$Process.CommandLine
    $executable = [string]$Process.ExecutablePath
    if (-not $State.legacy -and $State.executable -and
        $executable -and $executable -ine $State.executable) {
        return $false
    }

    if ($Service -eq 'backend') {
        return ($commandLine -match '(?i)(^|\s)-m\s+uvicorn(\s|$)' -and
            $commandLine.IndexOf('app.main:app', [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
            $commandLine -match '(?i)--port\s+\D*8000\b')
    }

    $viteCli = Join-Path $FrontendDir 'node_modules\vite\bin\vite.js'
    return ($commandLine.IndexOf($viteCli, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
        $commandLine -match '(?i)--port\s+\D*3000\b')
}

function Save-ServiceState([string]$Service, $Process, [string]$Executable, [string]$Stdout, [string]$Stderr) {
    $state = [ordered]@{
        pid = [int]$Process.Id
        executable = [System.IO.Path]::GetFullPath($Executable)
        root = $ProjectRoot
        started_at = (Get-Date).ToString('o')
        stdout = $Stdout
        stderr = $Stderr
    }
    $json = $state | ConvertTo-Json -Depth 4
    [System.IO.File]::WriteAllText((Get-StatePath $Service), $json, (New-Object System.Text.UTF8Encoding($false)))
    $legacyPath = Get-LegacyPidPath $Service
    if (Test-Path -LiteralPath $legacyPath -PathType Leaf) {
        Remove-Item -LiteralPath $legacyPath -Force
    }
}

function Get-CurrentManagedProcess([string]$Service) {
    $state = Read-ServiceState $Service
    if ($null -eq $state) {
        return $null
    }
    $process = Get-ProcessRecord $state.pid
    if (Test-ServiceProcess $state $process $Service) {
        return [pscustomobject]@{ state = $state; process = $process }
    }
    if ($null -eq $process) {
        Remove-ServiceState $Service
    } else {
        Write-Warn "$Service 的 PID $($state.pid) 已被其他进程占用；不会结束该进程。"
        Remove-ServiceState $Service
    }
    return $null
}

function Assert-PortAvailable([int]$Port, [string]$Service) {
    if (Test-PortOpen $Port) {
        $listeners = Get-PortListeners $Port
        $owners = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
        $ownerText = if ($owners.Count -gt 0) { "；监听 PID: $($owners -join ', ')" } else { '' }
        throw "$Service 端口 $Port 已被占用$ownerText。脚本不会结束未登记为本项目的进程。"
    }
}

function Wait-BackendReady([int]$ProcessId, [int]$TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ($null -eq (Get-ProcessRecord $ProcessId)) {
            return $false
        }
        try {
            $health = Invoke-RestMethod -Uri $BackendHealthUrl -TimeoutSec 3 -ErrorAction Stop
            if ($health.status -eq 'healthy' -and $health.database -eq 'connected') {
                return $true
            }
        } catch {
            # The backend may still be importing modules or connecting to its database.
        }
        Start-Sleep -Milliseconds 750
    }
    return $false
}

function Wait-FrontendReady([int]$ProcessId, [int]$TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ($null -eq (Get-ProcessRecord $ProcessId)) {
            return $false
        }
        try {
            $response = Invoke-WebRequest -Uri $FrontendUrl -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
            if ([int]$response.StatusCode -ge 200 -and [int]$response.StatusCode -lt 400) {
                return $true
            }
        } catch {
            # Vite may need a moment to optimize dependencies on first launch.
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Show-RecentLog([string]$Path) {
    if ($Path -and (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Write-Host "--- 最近日志：$Path ---"
        Get-Content -LiteralPath $Path -Tail 35 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ }
        Write-Host '--- 日志结束 ---'
    }
}

function Start-Backend {
    $existing = Get-CurrentManagedProcess 'backend'
    if ($existing) {
        Write-Info "复用已登记的后端进程 PID $($existing.state.pid)，检查数据库健康..."
        if (Wait-BackendReady $existing.state.pid 5) {
            return [pscustomobject]@{ pid = $existing.state.pid; started = $false; stdout = $existing.state.stdout; stderr = $existing.state.stderr }
        }
        throw "已登记的后端进程 PID $($existing.state.pid) 未通过健康检查。请查看 $($existing.state.stderr)"
    }

    Assert-PortAvailable 8000 '后端'
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $stdout = Join-Path $LogDir "backend-$stamp.out.log"
    $stderr = Join-Path $LogDir "backend-$stamp.err.log"
    $process = Start-Process -FilePath $script:PythonExe `
        -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000') `
        -WorkingDirectory $BackendDir `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -WindowStyle Hidden -PassThru
    try {
        Save-ServiceState 'backend' $process $script:PythonExe $stdout $stderr
    } catch {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw
    }
    Write-Info "后端进程已创建：PID $($process.Id)"

    if (-not (Wait-BackendReady $process.Id 120)) {
        Show-RecentLog $stderr
        Show-RecentLog $stdout
        [void](Stop-Service 'backend' 8000 -Quiet)
        throw "后端在 120 秒内未达到数据库健康状态。日志：$stderr"
    }
    Write-Ok '后端就绪（/health 返回 healthy，数据库 connected）'
    return [pscustomobject]@{ pid = $process.Id; started = $true; stdout = $stdout; stderr = $stderr }
}

function Start-Frontend {
    $existing = Get-CurrentManagedProcess 'frontend'
    if ($existing) {
        Write-Info "复用已登记的前端进程 PID $($existing.state.pid)，检查 HTTP 响应..."
        if (Wait-FrontendReady $existing.state.pid 5) {
            return [pscustomobject]@{ pid = $existing.state.pid; started = $false; stdout = $existing.state.stdout; stderr = $existing.state.stderr }
        }
        throw "已登记的前端进程 PID $($existing.state.pid) 未通过 HTTP 检查。请查看 $($existing.state.stderr)"
    }

    Assert-PortAvailable 3000 '前端'
    $viteCli = Join-Path $FrontendDir 'node_modules\vite\bin\vite.js'
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $stdout = Join-Path $LogDir "frontend-$stamp.out.log"
    $stderr = Join-Path $LogDir "frontend-$stamp.err.log"
    $arguments = '"{0}" --host 127.0.0.1 --port 3000 --strictPort' -f $viteCli
    $process = Start-Process -FilePath $script:NodeExe `
        -ArgumentList $arguments `
        -WorkingDirectory $FrontendDir `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -WindowStyle Hidden -PassThru
    try {
        Save-ServiceState 'frontend' $process $script:NodeExe $stdout $stderr
    } catch {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw
    }
    Write-Info "前端进程已创建：PID $($process.Id)"

    if (-not (Wait-FrontendReady $process.Id 60)) {
        Show-RecentLog $stderr
        Show-RecentLog $stdout
        [void](Stop-Service 'frontend' 3000 -Quiet)
        throw "前端在 60 秒内未通过 HTTP 检查。日志：$stderr"
    }
    Write-Ok '前端就绪（HTTP 200）'
    return [pscustomobject]@{ pid = $process.Id; started = $true; stdout = $stdout; stderr = $stderr }
}

function Stop-Service([string]$Service, [int]$Port, [switch]$Quiet) {
    $managed = Get-CurrentManagedProcess $Service
    if (-not $managed) {
        if (-not $Quiet) {
            Write-Info "$Service 没有已登记的运行进程；未按端口结束其他程序。"
        }
        return $true
    }

    $pidValue = [int]$managed.state.pid
    if (-not $Quiet) {
        Write-Info "停止 $Service（PID $pidValue）..."
    }
    $taskkill = Join-Path $env:SystemRoot 'System32\taskkill.exe'
    if (-not (Test-Path -LiteralPath $taskkill -PathType Leaf)) {
        throw '找不到 Windows taskkill.exe。'
    }
    & $taskkill /PID $pidValue /T /F 2>$null | Out-Null
    $deadline = (Get-Date).AddSeconds(15)
    while ((Get-Date) -lt $deadline -and $null -ne (Get-ProcessRecord $pidValue)) {
        Start-Sleep -Milliseconds 300
    }
    if ($null -ne (Get-ProcessRecord $pidValue)) {
        Write-Problem "$Service PID $pidValue 停止超时。"
        return $false
    }
    Remove-ServiceState $Service

    $portDeadline = (Get-Date).AddSeconds(8)
    while ((Get-Date) -lt $portDeadline -and (Test-PortOpen $Port)) {
        Start-Sleep -Milliseconds 250
    }
    if (Test-PortOpen $Port) {
        Write-Problem "$Service 进程已停止，但端口 $Port 仍有监听者；该进程未被结束。"
        return $false
    }
    if (-not $Quiet) {
        Write-Ok "$Service 已停止，端口 $Port 已释放。"
    }
    return $true
}

function Stop-App {
    $frontendStopped = Stop-Service 'frontend' 3000
    $backendStopped = Stop-Service 'backend' 8000
    if (-not $frontendStopped -or -not $backendStopped) {
        throw '至少一个服务未能确认停止或端口释放；未继续启动。'
    }
}

function Start-App([switch]$OpenBrowser) {
    New-Item -ItemType Directory -Force -Path $PidDir, $LogDir | Out-Null
    $problems = @(Get-PreflightProblems)
    if ($problems.Count -gt 0) {
        foreach ($problem in $problems) {
            Write-Problem $problem
        }
        throw '启动前检查未通过。请先补齐上面的环境或配置。'
    }

    $startedThisRun = New-Object 'System.Collections.Generic.List[string]'
    try {
        $backend = Start-Backend
        if ($backend.started) { $startedThisRun.Add('backend') }
        $frontend = Start-Frontend
        if ($frontend.started) { $startedThisRun.Add('frontend') }
    } catch {
        Write-Problem $_.Exception.Message
        foreach ($service in @('frontend', 'backend')) {
            if ($startedThisRun.Contains($service)) {
                try { [void](Stop-Service $service $(if ($service -eq 'frontend') { 3000 } else { 8000 }) -Quiet) }
                catch { Write-Warn "回收本次启动的 $service 失败：$($_.Exception.Message)" }
            }
        }
        throw '应用启动未完成；本次新启动的服务已回收，日志保留在 logs\。'
    }

    Write-Host ''
    Write-Ok 'ai-for-investor 已启动'
    Write-Host "  前端：$FrontendUrl"
    Write-Host '  API：  http://127.0.0.1:8000/docs'
    Write-Host "  日志：$LogDir"
    if ($OpenBrowser) {
        Start-Process $FrontendUrl | Out-Null
    }
}

function Invoke-Doctor {
    Write-Host 'ai-for-investor Win11 启动环境检查'
    $problems = @(Get-PreflightProblems)
    foreach ($port in @(3000, 8000)) {
        if (Test-PortOpen $port) {
            $managedService = if ($port -eq 3000) { 'frontend' } else { 'backend' }
            if (Get-CurrentManagedProcess $managedService) {
                Write-Info "端口 $port 正由本项目登记的 $managedService 占用。"
            } else {
                $problems += "端口 $port 已被其他进程占用；停止脚本不会结束它。"
            }
        } else {
            Write-Ok "端口 $port 可用"
        }
    }

    if ($problems.Count -eq 0) {
        Write-Ok '启动条件已满足。'
        return 0
    }
    foreach ($problem in $problems) {
        Write-Problem $problem
    }
    return 1
}

function Show-Status {
    foreach ($service in @('backend', 'frontend')) {
        $managed = Get-CurrentManagedProcess $service
        if ($managed) {
            $healthy = if ($service -eq 'backend') {
                Wait-BackendReady $managed.state.pid 2
            } else {
                Wait-FrontendReady $managed.state.pid 2
            }
            $label = if ($healthy) { 'running / healthy' } else { 'running / not ready' }
            Write-Host ("{0}: {1} (PID {2})" -f $service, $label, $managed.state.pid)
        } else {
            $port = if ($service -eq 'backend') { 8000 } else { 3000 }
            if (Test-PortOpen $port) {
                Write-Host "$service`: unmanaged listener on port $port (left untouched)" -ForegroundColor Yellow
            } else {
                Write-Host "$service`: stopped"
            }
        }
    }
}

function Invoke-WithLifecycleLock([scriptblock]$Operation) {
    New-Item -ItemType Directory -Force -Path $PidDir | Out-Null
    $lockPath = Join-Path $PidDir 'app.lifecycle.lock'
    $stream = $null
    try {
        $stream = New-Object System.IO.FileStream(
            $lockPath,
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
    } catch {
        throw '另一个启动/停止/重启命令正在执行。请等它完成后再试。'
    }
    try {
        & $Operation
    } finally {
        if ($null -ne $stream) {
            $stream.Dispose()
        }
    }
}

function Show-Usage {
    Write-Host @'
用法：scripts\windows\app.bat <start|stop|restart|status|doctor>

  start    启动后端与前端，成功后打开浏览器
  stop     仅停止 PID 记录匹配本项目的服务
  restart  停止并确认端口释放后，再启动并检查两个健康端点
  status   显示进程登记与服务健康状态
  doctor   检查 Python、Node.js、依赖、.env 与端口
'@
}

try {
    switch ($Action) {
        'start' {
            Invoke-WithLifecycleLock { Start-App -OpenBrowser:(-not $NoBrowser) }
            exit 0
        }
        'stop' {
            Invoke-WithLifecycleLock { Stop-App }
            exit 0
        }
        'restart' {
            Invoke-WithLifecycleLock {
                Write-Info '重启第 1/2 步：停止当前项目服务并确认端口释放。'
                Stop-App
                Write-Info '重启第 2/2 步：重新启动并检查后端、前端健康状态。'
                Start-App -OpenBrowser:(-not $NoBrowser)
            }
            exit 0
        }
        'status' {
            Show-Status
            exit 0
        }
        'doctor' {
            $doctorResult = Invoke-Doctor
            exit $doctorResult
        }
        default {
            Show-Usage
            exit 0
        }
    }
} catch {
    Write-Problem $_.Exception.Message
    exit 1
}
