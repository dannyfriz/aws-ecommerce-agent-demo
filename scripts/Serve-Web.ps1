param([ValidateRange(1024,65535)][int]$Port = 8766, [string]$PythonPath = '')
. "$PSScriptRoot/Common.ps1"
Invoke-Checked (Resolve-Program 'python' $PythonPath) @((Join-Path $PSScriptRoot 'serve_web.py'), '--port', "$Port")
