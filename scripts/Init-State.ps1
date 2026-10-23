param(
    [ValidateSet('plan','apply')][string]$Action = 'plan',
    [Parameter(Mandatory)][string]$Profile,
    [Parameter(Mandatory)][string]$VarFile,
    [ValidateSet('demo','dev','test')][string]$Environment = 'demo',
    [string]$TerraformPath = ''
)
. "$PSScriptRoot/Common.ps1"
$terraform = Resolve-Program 'terraform' $TerraformPath
$variables = (Get-Item -LiteralPath $VarFile).FullName
$folder = Join-Path $script:ProjectRoot 'infra/bootstrap'
$plans = Join-Path $script:ProjectRoot '.build/plans'
New-Item -ItemType Directory -Force -Path $plans | Out-Null
$plan = Join-Path $plans "$Environment-bootstrap.tfplan"
$previousProfile = $env:AWS_PROFILE
try {
    $env:AWS_PROFILE = $Profile
    Invoke-Checked $terraform @("-chdir=$folder", 'init', '-input=false')
    Invoke-Checked $terraform @("-chdir=$folder", 'plan', '-input=false', "-var-file=$variables", "-var=environment=$Environment", "-out=$plan")
    if ($Action -eq 'apply') {
        Invoke-Checked $terraform @("-chdir=$folder", 'apply', '-input=false', $plan)
        Export-StackOutputs $terraform $folder 'bootstrap'
        $values = Get-Content -LiteralPath (Join-Path $script:ProjectRoot '.build/outputs/bootstrap.json') -Raw | ConvertFrom-Json
        $destination = Join-Path $script:ProjectRoot '.build/backend'
        New-Item -ItemType Directory -Force -Path $destination | Out-Null
        foreach ($layer in @('foundation','data','compute')) {
            $content = "bucket = `"$($values.state_bucket.value)`"`nkey = `"$Environment/$layer/terraform.tfstate`"`nregion = `"$($values.state_region.value)`"`nencrypt = true`nkms_key_id = `"$($values.state_kms_key_arn.value)`"`nuse_lockfile = true`n"
            [IO.File]::WriteAllText((Join-Path $destination "$layer.hcl"), $content, [Text.UTF8Encoding]::new($false))
        }
        Write-Host 'Configuraciones de backend creadas en .build/backend/. Protege también el state local de bootstrap.'
    }
} finally { $env:AWS_PROFILE = $previousProfile }
