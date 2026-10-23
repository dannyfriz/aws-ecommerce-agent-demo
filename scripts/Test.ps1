param(
    [switch]$Full,
    [string]$BaseRef = '',
    [string[]]$ChangedFiles = @(),
    [switch]$PlanOnly,
    [string]$ImpactOutput = '.build/test-impact.json',
    [switch]$SkipTerraform,
    [string]$TerraformPath = '',
    [string]$PythonPath = '',
    [string]$NodePath = ''
)
. "$PSScriptRoot/Common.ps1"
$python = Resolve-Program 'python' $PythonPath
$previousPythonPath = $env:PYTHONPATH
Push-Location $script:ProjectRoot
try {
    if ($BaseRef -and $ChangedFiles.Count) { throw 'Usa BaseRef o ChangedFiles, no ambos.' }
    $selection = @((Join-Path $PSScriptRoot 'test_impact.py'), '--output', $ImpactOutput)
    if ($Full) { $selection += '--full' }
    if ($BaseRef) { $selection += @('--base', $BaseRef) }
    if ($ChangedFiles.Count) { $selection += '--files'; $selection += $ChangedFiles }
    Invoke-Checked $python $selection
    $impact = Get-Content -LiteralPath $ImpactOutput -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($impact.schema_version -ne 1) { throw 'El selector devolvió una versión de plan incompatible.' }
    $modeLabel = if ($impact.mode -eq 'full') { 'completa' } else { 'diferencial' }
    Write-Host "Validación ${modeLabel}: $(@($impact.python_tests).Count) suites Python, $(@($impact.frontend_tests).Count) suites frontend y $(@($impact.terraform_layers).Count) capas Terraform."
    foreach ($reason in $impact.reasons) { Write-Host "  $reason" }
    Write-Host "Detalle de selección: $ImpactOutput"
    if ($PlanOnly) { return }

    # Un único proceso conserva los imports de helpers compartidos entre suites seleccionadas.
    $env:PYTHONPATH = (Join-Path $script:ProjectRoot 'src') + [IO.Path]::PathSeparator + (Join-Path $script:ProjectRoot 'tests')
    Invoke-Checked $python @((Join-Path $PSScriptRoot 'check_repository.py'))
    if (@($impact.python_tests).Count) {
        $modules = @()
        foreach ($file in $impact.python_tests) {
            if ($file -notmatch '^tests/(test_[A-Za-z0-9_]+)\.py$') { throw 'El plan contiene una suite Python inesperada.' }
            $modules += $Matches[1]
        }
        Invoke-Checked $python (@('-m', 'unittest', '-v') + $modules)
    }
    if (@($impact.frontend_tests).Count -or @($impact.javascript_checks).Count) {
        $node = Resolve-Program 'node' $NodePath
        foreach ($file in $impact.frontend_tests) {
            if ($file -notmatch '^tests/web-[A-Za-z0-9_-]+\.test\.mjs$') { throw 'El plan contiene una suite frontend inesperada.' }
            Invoke-Checked $node @($file)
        }
        foreach ($file in $impact.javascript_checks) {
            if ($file -notmatch '^web/[A-Za-z0-9_./-]+\.js$' -or $file.Contains('..')) { throw 'El plan contiene un JavaScript inesperado.' }
            Invoke-Checked $node @('--check', $file)
        }
    }
    if (@($impact.terraform_layers).Count -and -not $SkipTerraform) {
        $terraform = Resolve-Program 'terraform' $TerraformPath
        foreach ($layer in $impact.terraform_layers) {
            if ($layer -notin @('bootstrap', 'foundation', 'data', 'compute')) { throw 'El plan contiene una capa Terraform inesperada.' }
            Invoke-Checked $terraform @("-chdir=infra/$layer", 'fmt', '-check', '-recursive')
            Invoke-Checked $terraform @("-chdir=infra/$layer", 'init', '-backend=false', '-input=false', '-lockfile=readonly')
            Invoke-Checked $terraform @("-chdir=infra/$layer", 'validate', '-no-color')
            if (Test-Path -LiteralPath "infra/$layer/tests" -PathType Container) {
                Invoke-Checked $terraform @("-chdir=infra/$layer", 'test', '-no-color')
            }
        }
    } elseif ($SkipTerraform -and @($impact.terraform_layers).Count) {
        Write-Host 'Terraform omitido por la opción explícita SkipTerraform.'
    }
} finally { $env:PYTHONPATH = $previousPythonPath; Pop-Location }
