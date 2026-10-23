param([string]$PythonPath = '', [string]$Output = '.build/version-audit.json')
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Common.ps1')
$python = Resolve-Program 'python' $PythonPath
Push-Location (Split-Path $PSScriptRoot -Parent)
try { Invoke-Checked $python @('scripts/audit_versions.py', '--output', $Output) }
finally { Pop-Location }
