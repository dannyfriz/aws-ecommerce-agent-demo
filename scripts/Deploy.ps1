param(
    [Parameter(Mandatory)][ValidateSet('foundation','data','compute')][string]$Layer,
    [ValidateSet('plan','apply')][string]$Action = 'plan',
    [Parameter(Mandatory)][string]$Profile,
    [Parameter(Mandatory)][string]$BackendConfig,
    [Parameter(Mandatory)][string]$VarFile,
    [ValidateSet('demo','dev','test')][string]$Environment = 'demo',
    [string]$TerraformPath = ''
)
. "$PSScriptRoot/Common.ps1"
$terraform = Resolve-Program 'terraform' $TerraformPath
$backend = (Get-Item -LiteralPath $BackendConfig).FullName
$variables = (Get-Item -LiteralPath $VarFile).FullName
$folder = Join-Path $script:ProjectRoot "infra/$Layer"
$plans = Join-Path $script:ProjectRoot '.build/plans'
New-Item -ItemType Directory -Force -Path $plans | Out-Null
$plan = Join-Path $plans "$Environment-$Layer.tfplan"
$previousProfile = $env:AWS_PROFILE
try {
    $env:AWS_PROFILE = $Profile
    Invoke-Checked $terraform @("-chdir=$folder", 'init', '-input=false', '-reconfigure', "-backend-config=$backend")
    Invoke-Checked $terraform @("-chdir=$folder", 'validate')
    Invoke-Checked $terraform @("-chdir=$folder", 'plan', '-input=false', "-var-file=$variables", "-var=environment=$Environment", "-out=$plan")
    if ($Action -eq 'apply') {
        Invoke-Checked $terraform @("-chdir=$folder", 'apply', '-input=false', $plan)
        Export-StackOutputs $terraform $folder $Layer
    } else { Write-Host 'Plan generado. Revisa los cambios antes de invocar este script con -Action apply.' }
} finally { $env:AWS_PROFILE = $previousProfile }
