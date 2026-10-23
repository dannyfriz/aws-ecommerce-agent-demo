param(
    [string]$Profile = 'default',
    [string]$CostCenter = 'ecommerce-agent-demo',
    [string]$Start = '',
    [string]$End = '',
    [string]$PythonPath = ''
)
. "$PSScriptRoot/Common.ps1"
if (-not $PythonPath -and (Test-Path "$script:ProjectRoot/.build/venv/Scripts/python.exe")) {
    $PythonPath = "$script:ProjectRoot/.build/venv/Scripts/python.exe"
}
$python = Resolve-Program 'python' $PythonPath
$arguments = @("$PSScriptRoot/report_daily_costs.py", '--profile', $Profile, '--cost-center', $CostCenter)
if ($Start) { $arguments += @('--start', $Start) }
if ($End) { $arguments += @('--end', $End) }
Invoke-Checked $python $arguments
