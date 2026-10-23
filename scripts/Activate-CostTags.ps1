param([Parameter(Mandatory)][string]$Profile, [string]$PythonPath = '')
. "$PSScriptRoot/Common.ps1"
if (-not $PythonPath -and (Test-Path "$script:ProjectRoot/.build/venv/Scripts/python.exe")) {
    $PythonPath = "$script:ProjectRoot/.build/venv/Scripts/python.exe"
}
Invoke-Checked (Resolve-Program 'python' $PythonPath) @("$PSScriptRoot/activate_cost_tags.py", '--profile', $Profile)
