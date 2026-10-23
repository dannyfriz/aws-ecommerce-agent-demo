param([Parameter(Mandatory)][string]$Profile, [string]$FoundationOutputs = '', [string]$DataOutputs = '', [switch]$ResetOrders, [switch]$OrdersOnly, [string]$PythonPath = '')
. "$PSScriptRoot/Common.ps1"
$python = Resolve-Program 'python' $PythonPath
$arguments = @((Join-Path $PSScriptRoot 'seed_demo.py'), '--profile', $Profile)
if ($FoundationOutputs) { $arguments += @('--foundation', (Get-Item -LiteralPath $FoundationOutputs).FullName) }
if ($DataOutputs) { $arguments += @('--data', (Get-Item -LiteralPath $DataOutputs).FullName) }
if ($ResetOrders) { $arguments += '--reset-orders' }
if ($OrdersOnly) { $arguments += '--orders-only' }
Invoke-Checked $python $arguments
