# CA Copilot - Windows launcher core (PowerShell)
# Started by run_windows.bat (just double-click that file).
# Same job as before: finds/installs Python, sets up the environment,
# installs dependencies, builds the database if needed, starts the app
# and opens your browser. Everything runs on this computer only.

$ErrorActionPreference = 'Stop'
$AppName  = 'CA Copilot'
$Port     = 8501
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogFile   = Join-Path $ScriptDir 'launch.log'
$VenvDir   = Join-Path $ScriptDir '.venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = 'false'

function Log($msg) {
    $line = "$(Get-Date -Format 'HH:mm:ss')  $msg"
    Write-Host $line
    try { Add-Content -Path $LogFile -Value $line } catch { }
}

function Invoke-Native {
    # Runs a native command, capturing stdout+stderr to a file (echoed into
    # launch.log with a tag). Returns the process exit code and NEVER throws
    # on native stderr: on Windows PowerShell 5.1, $ErrorActionPreference =
    # 'Stop' turns any native stderr into a terminating error, even when
    # redirected - which used to kill the launcher on every first run with a
    # bare "Traceback (most recent call last):" message.
    param([string]$Exe, [string[]]$Argv, [string]$LogFile, [string]$Tag)
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Exe @Argv > $LogFile 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prevEap
    }
    if (Test-Path $LogFile) { Get-Content $LogFile | ForEach-Object { Log "[$Tag] $_" } }
    return $code
}


function Test-Python($exe, $argv) {
    try {
        & $exe @argv --version >$null 2>&1
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

try {
    Set-Location $ScriptDir
    Log "=== $AppName launcher started ==="

    if (-not (Test-Path (Join-Path $ScriptDir 'app.py'))) {
        throw 'app.py was not found next to the launcher. Please extract ALL files from the ZIP into a folder first, then double-click run_windows.bat inside that folder.'
    }

    # If the app is already running, just open the browser.
    try {
        $c = New-Object Net.Sockets.TcpClient
        $c.Connect('127.0.0.1', $Port)
        $c.Close()
        Log "$AppName is already running. Opening it in your browser..."
        Start-Process "http://127.0.0.1:$Port"
        return
    } catch { }

    # --- Find Python, installing it automatically if missing ---
    $pyCmd = $null; $pyArgs = @()
    if (Test-Python 'py' @('-3'))            { $pyCmd = 'py'; $pyArgs = @('-3') }
    elseif (Test-Python 'python' @())       { $pyCmd = 'python' }
    else {
        Log 'Python not found. Installing it automatically via winget (needs internet)...'
        try { & winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements >$null 2>&1 } catch { }
        if (Test-Python 'py' @('-3'))       { $pyCmd = 'py'; $pyArgs = @('-3') }
        elseif (Test-Python 'python' @())  { $pyCmd = 'python' }
        else {
            $fallback = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
            if (Test-Path $fallback) { $pyCmd = $fallback }
        }
    }
    if (-not $pyCmd) { throw 'Could not get Python working. Please install Python 3.10+ from python.org (tick "Add python.exe to PATH") and run this file again.' }
    Log "Using Python: $pyCmd $($pyArgs -join ' ')"

    # --- Virtual environment (one-time setup) ---
    # NOTE (2026-10-22): native calls go through Invoke-Native and the
    # dependency probe uses Test-Path, never `python -c "import ..."`. On
    # Windows PowerShell 5.1 with $ErrorActionPreference='Stop', ANY native
    # stderr becomes a terminating error (even when redirected), so the old
    # import probe crashed the launcher on EVERY first run with a bare
    # "Traceback (most recent call last):" (fresh venv => ModuleNotFoundError).
    $venvJustCreated = $false
    if (-not (Test-Path $VenvPython)) {
        Log 'First run: creating the isolated environment...'
        $code = Invoke-Native $pyCmd ($pyArgs + @('-m','venv',$VenvDir)) (Join-Path $ScriptDir 'venv_create.log') 'venv'
        if (-not (Test-Path $VenvPython)) { throw 'Could not create the virtual environment (.venv). The [venv] lines above show why - send launch.log for help.' }
        $venvJustCreated = $true
    }

    # --- Dependencies (only if streamlit is missing) ---
    $streamlitDir = Join-Path $VenvDir 'Lib\site-packages\streamlit'
    $marker = Join-Path $VenvDir 'install_ok.txt'
    if (-not ((Test-Path $streamlitDir) -and (Test-Path $marker))) {
        if ((-not $venvJustCreated) -and (Test-Path $VenvDir) -and -not (Test-Path $marker)) {
            Log 'Cleaning up a previous incomplete installation...'
            Remove-Item -Recurse -Force $VenvDir
            $code = Invoke-Native $pyCmd ($pyArgs + @('-m','venv',$VenvDir)) (Join-Path $ScriptDir 'venv_create.log') 'venv'
            if (-not (Test-Path $VenvPython)) { throw 'Could not re-create the virtual environment. The [venv] lines above show why - send launch.log for help.' }
        }
        Log 'Installing dependencies (needs internet; a few minutes on first run)...'
        $code = Invoke-Native $VenvPython @('-m','pip','install','--upgrade','pip') (Join-Path $ScriptDir 'pip_upgrade.log') 'pip-upgrade'
        if ($code -ne 0) { Log 'WARNING: pip self-upgrade failed - continuing with the bundled pip.' }
        $code = Invoke-Native $VenvPython @('-m','pip','install','-r',(Join-Path $ScriptDir 'requirements.txt')) (Join-Path $ScriptDir 'pip_install.log') 'pip'
        if ($code -ne 0) { throw 'Dependency installation failed. The [pip] lines above show why - send launch.log for help.' }
        Set-Content -Path $marker -Value 'ok'
        Log 'Dependencies installed.'
    }

    # --- Start the server in its own window ---
    Log "Starting $AppName..."
    Start-Process -FilePath $VenvPython -ArgumentList @('-m','streamlit','run','app.py','--server.headless','true','--server.port',"$Port") -WorkingDirectory $ScriptDir

    # --- Wait until the server answers, then open the browser ---
    $ready = $false
    for ($i = 0; $i -lt 90; $i++) {
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/_stcore/health" -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200) { $ready = $true; break }
        } catch { }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'The app server did not start in time. Close any "$AppName" window and run again.' }
    Log "$AppName is running at http://127.0.0.1:$Port - opening your browser."
    Start-Process "http://127.0.0.1:$Port"
    Log 'Done. Keep the server window open while using the app; closing it stops the app.'
}
catch {
    Log "ERROR: $($_.Exception.Message)"
    if ($_.ScriptStackTrace) { Log "PowerShell stack: $($_.ScriptStackTrace)" }
    Log 'Full details are above in this log (look for [venv] / [pip] lines). Send launch.log if you need help.'
}
finally {
    Read-Host 'Press Enter to close this window'
}
