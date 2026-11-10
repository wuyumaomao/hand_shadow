param([string]$BlenderExe = $env:BLENDER_EXE, [string]$PythonExe = 'python', [int]$Port = 8765)
$ErrorActionPreference = 'Stop'
if (-not $BlenderExe) { throw 'Please pass -BlenderExe or set BLENDER_EXE.' }
& $PythonExe "$PSScriptRoot\api_server.py" --blender $BlenderExe --port $Port
if ($LASTEXITCODE -ne 0) { throw "API exited: $LASTEXITCODE" }
