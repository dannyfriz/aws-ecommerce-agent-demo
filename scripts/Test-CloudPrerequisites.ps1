param(
    [Parameter(Mandatory)][string]$Profile,
    [Parameter(Mandatory)][ValidatePattern('^[0-9]{12}$')][string]$AccountId,
    [Parameter(Mandatory)][string]$CertificateArn,
    [Parameter(Mandatory)][ValidatePattern('^[a-z0-9-]+(\.[a-z0-9-]+)+$')][string]$FrontendDomain,
    [string]$AwsPath = ''
)
. "$PSScriptRoot/Common.ps1"
$aws = Resolve-Program 'aws' $AwsPath
$manifest = Get-Content (Join-Path $script:ProjectRoot 'toolchain.versions.json') -Raw | ConvertFrom-Json
$version = & $aws --version
if ($LASTEXITCODE -ne 0 -or $version -notmatch ('^aws-cli/' + [regex]::Escape($manifest.aws_cli.version) + '\s')) {
    throw "Se requiere AWS CLI $($manifest.aws_cli.version), versión estable verificada en el manifiesto."
}
if ($CertificateArn -notmatch "^arn:aws:acm:us-east-1:${AccountId}:certificate/[a-f0-9-]+$") {
    throw 'CloudFront requiere un certificado ACM en us-east-1 y en la cuenta indicada.'
}
$identityJson = & $aws sts get-caller-identity --profile $Profile --output json --no-cli-pager
if ($LASTEXITCODE -ne 0) { throw 'No se pudo verificar la sesión AWS. Revisar el perfil y su autenticación.' }
$identity = ($identityJson -join "`n") | ConvertFrom-Json
if ($identity.Account -ne $AccountId) { throw 'El perfil apunta a otra cuenta; se interrumpió la verificación.' }
$certificateJson = & $aws acm describe-certificate --certificate-arn $CertificateArn --region us-east-1 --profile $Profile --output json --no-cli-pager
if ($LASTEXITCODE -ne 0) { throw 'No se pudo consultar el certificado ACM.' }
$certificate = (($certificateJson -join "`n") | ConvertFrom-Json).Certificate
if ($certificate.Status -ne 'ISSUED') { throw 'El certificado ACM no está emitido.' }
if ([DateTimeOffset]::Parse($certificate.NotAfter) -le [DateTimeOffset]::UtcNow) { throw 'El certificado está vencido.' }
$covered = $false
foreach ($name in $certificate.SubjectAlternativeNames) {
    if ($name -ieq $FrontendDomain) { $covered = $true }
    elseif ($name.StartsWith('*.')) {
        $suffix = $name.Substring(2)
        $wildcard = '^[^.]+\.' + [regex]::Escape($suffix) + '$'
        if ($FrontendDomain -imatch $wildcard) { $covered = $true }
    }
}
if (-not $covered) { throw 'El hostname no está cubierto por los SAN del certificado. El wildcard cubre un solo nivel.' }
Write-Host 'Cuenta, sesión, región, emisión, vigencia y cobertura del certificado: verificadas mediante consultas de lectura.'
Write-Host 'Esta comprobación no crea recursos ni modifica DNS.'
