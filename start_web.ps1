param([string]$BlenderExe = $env:BLENDER_EXE, [string]$PythonExe = 'python', [int]$Port = 8765)
$ErrorActionPreference = 'Stop'
if (-not $BlenderExe) { throw 'Please pass -BlenderExe or set BLENDER_EXE.' }
Write-Host "浏览器打开 http://127.0.0.1:$Port ，保留此窗口运行；Ctrl+C 停止。"
& $PythonExe "$PSScriptRoot\api_server.py" --blender $BlenderExe --port $Port
if ($LASTEXITCODE -ne 0) { throw "Web server exited: $LASTEXITCODE" }
