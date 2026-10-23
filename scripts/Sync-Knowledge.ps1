param(
    [Parameter(Mandatory)][ValidatePattern('^[0-9]{12}$')][string]$ExpectedAccountId,
    [string]$Profile = 'default',
    [string]$ComputeOutputs = '',
    [ValidatePattern('^[a-z][a-z0-9-]{2,24}$')][string]$Project = 'ecommerce-agent',
    [ValidateSet('demo', 'dev', 'test')][string]$Environment = 'demo',
    [string]$Region = 'us-east-1',
    [ValidateRange(1, 180)][int]$TimeoutSeconds = 180,
    [ValidateRange(1, 10)][int]$PollIntervalSeconds = 5,
    [switch]$NoWait,
    [string]$PythonPath = ''
)
. "$PSScriptRoot/Common.ps1"
$python = Resolve-Program 'python' $PythonPath
$arguments = @((Join-Path $PSScriptRoot 'sync_knowledge.py'), '--expected-account-id', $ExpectedAccountId,
    '--profile', $Profile, '--project', $Project, '--environment', $Environment, '--region', $Region,
    '--timeout', $TimeoutSeconds.ToString(), '--poll-interval', $PollIntervalSeconds.ToString())
if ($ComputeOutputs) { $arguments += @('--outputs', (Get-Item -LiteralPath $ComputeOutputs).FullName) }
if (-not $NoWait) { $arguments += '--wait' }
Invoke-Checked $python $arguments
