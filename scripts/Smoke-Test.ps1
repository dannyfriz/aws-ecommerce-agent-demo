param([string]$ComputeOutputs = '', [string]$PythonPath = '')
. "$PSScriptRoot/Common.ps1"
$arguments = @((Join-Path $PSScriptRoot 'smoke_test.py'))
if ($ComputeOutputs) { $arguments += @('--outputs', (Get-Item -LiteralPath $ComputeOutputs).FullName) }
Invoke-Checked (Resolve-Program 'python' $PythonPath) $arguments
