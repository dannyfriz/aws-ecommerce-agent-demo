param([string]$PythonPath = '', [string]$TrivyPath = '')
. "$PSScriptRoot/Common.ps1"
$python = Resolve-Program 'python' $PythonPath
Push-Location $script:ProjectRoot
try {
    if ($TrivyPath) {
        $scanner = (Get-Item -LiteralPath $TrivyPath).FullName
        Invoke-Checked $python @('scripts/security_scan.py', '--trivy-path', $scanner)
    } else {
        Invoke-Checked $python @('scripts/install_trivy.py')
        Invoke-Checked $python @('scripts/security_scan.py')
    }
} finally { Pop-Location }
