param([switch]$SkipTerraform, [string]$TerraformPath = '', [string]$PythonPath = '', [string]$NodePath = '')
. "$PSScriptRoot/Common.ps1"
$python = Resolve-Program 'python' $PythonPath
$node = Resolve-Program 'node' $NodePath
$previousPythonPath = $env:PYTHONPATH
Push-Location $script:ProjectRoot
try {
    $env:PYTHONPATH = Join-Path $script:ProjectRoot 'src'
    Invoke-Checked $python @('scripts/check_repository.py')
    Invoke-Checked $python @('-m', 'unittest', 'discover', '-s', 'tests', '-v')
    Invoke-Checked $node @('tests/web-auth.test.mjs')
    Invoke-Checked $node @('tests/web-evidence.test.mjs')
    Invoke-Checked $node @('tests/web-order-sync.test.mjs')
    Invoke-Checked $node @('tests/web-profiles.test.mjs')
    Invoke-Checked $node @('tests/web-pending.test.mjs')
    Invoke-Checked $node @('tests/web-review.test.mjs')
    foreach ($file in Get-ChildItem -LiteralPath 'web' -Filter '*.js') { Invoke-Checked $node @('--check', $file.FullName) }
    if (-not $SkipTerraform) {
        $terraform = Resolve-Program 'terraform' $TerraformPath
        Invoke-Checked $terraform @('-chdir=infra', 'fmt', '-check', '-recursive')
        foreach ($layer in @('bootstrap', 'foundation', 'data', 'compute')) {
            Invoke-Checked $terraform @("-chdir=infra/$layer", 'init', '-backend=false', '-input=false', '-lockfile=readonly')
            Invoke-Checked $terraform @("-chdir=infra/$layer", 'validate', '-no-color')
        }
        Invoke-Checked $terraform @('-chdir=infra/foundation', 'test', '-no-color')
        Invoke-Checked $terraform @('-chdir=infra/data', 'test', '-no-color')
        Invoke-Checked $terraform @('-chdir=infra/compute', 'test', '-no-color')
    }
} finally { $env:PYTHONPATH = $previousPythonPath; Pop-Location }
