param([switch]$Live, [switch]$Managed, [string]$Profile = 'default', [string]$Region = 'us-east-1', [string]$ModelId = '', [string]$Cases = '', [string]$Output = '', [string]$ComputeOutputs = '', [string]$Evaluator = 'Builtin.ToolSelectionAccuracy', [double]$Threshold = 0.8, [string[]]$CaseId = @(), [string]$PythonPath = '')
. "$PSScriptRoot/Common.ps1"
if ($Managed -and $Cases) { throw 'La evaluación administrada usa exclusivamente el dataset ficticio versionado.' }
$entrypoint = if ($Managed) { 'evaluate_agent_managed.py' } else { 'evaluate_agent.py' }
$arguments = @((Join-Path $PSScriptRoot $entrypoint))
if ($Managed) {
    $arguments += @('--profile', $Profile, '--region', $Region, '--evaluator', $Evaluator, '--threshold', $Threshold.ToString([Globalization.CultureInfo]::InvariantCulture))
    foreach ($case in $CaseId) { $arguments += @('--case-id', $case) }
} elseif ($Live) { $arguments += @('--live', '--profile', $Profile, '--region', $Region) }
if ($ModelId) { $arguments += @('--model-id', $ModelId) }
if ($Cases) { $arguments += @('--cases', $Cases) }
if ($Output) { $arguments += @('--output', $Output) }
if ($ComputeOutputs) { $arguments += @('--compute-outputs', $ComputeOutputs) }
Invoke-Checked (Resolve-Program 'python' $PythonPath) $arguments
