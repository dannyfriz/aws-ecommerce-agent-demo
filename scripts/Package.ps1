param([string]$PythonPath = '')
. "$PSScriptRoot/Common.ps1"
$python = Resolve-Program 'python' $PythonPath
Invoke-Checked $python @((Join-Path $PSScriptRoot 'package.py'))
