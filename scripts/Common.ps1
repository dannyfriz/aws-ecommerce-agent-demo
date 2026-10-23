$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$script:ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
function Resolve-Program([string]$Name, [string]$Override = '') {
    if ($Override) { return (Get-Item -LiteralPath $Override).FullName }
    $command = Get-Command $Name -ErrorAction Stop
    return $command.Source
}
function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "El programa $Program terminó con código $LASTEXITCODE." }
}
function Export-StackOutputs([string]$Terraform, [string]$Folder, [string]$Layer) {
    $destination = Join-Path $script:ProjectRoot '.build/outputs'
    New-Item -ItemType Directory -Force -Path $destination | Out-Null
    $content = & $Terraform "-chdir=$Folder" output -json
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron exportar los outputs.' }
    [IO.File]::WriteAllText((Join-Path $destination "$Layer.json"), ($content -join "`n"), [Text.UTF8Encoding]::new($false))
    Write-Host "Outputs guardados en .build/outputs/$Layer.json; no se versionan."
}
