[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$config = Get-Content -LiteralPath (
    Join-Path $root 'config\private-server.json'
) -Raw | ConvertFrom-Json
$client = (Resolve-Path -LiteralPath (Join-Path $root 'Client')).Path
$data = @(Get-ChildItem -LiteralPath $client -Directory -Filter '*_Data')
if ($data.Count -ne 1) {
    throw 'Expected exactly one Unity data directory.'
}
$assemblyPath = Join-Path $data[0].FullName 'Managed\Assembly-CSharp.dll'
$cecil = Join-Path $root 'app\tools\Mono.Cecil.dll'
Add-Type -Path $cecil
$resolver = New-Object Mono.Cecil.DefaultAssemblyResolver
$resolver.AddSearchDirectory((Split-Path -Parent $assemblyPath))
$parameters = New-Object Mono.Cecil.ReaderParameters
$parameters.AssemblyResolver = $resolver
$assembly = [Mono.Cecil.AssemblyDefinition]::ReadAssembly(
    $assemblyPath,
    $parameters
)
try {
    $module = $assembly.MainModule
    $dmm = $module.Types |
        Where-Object FullName -eq 'Zero.Dmm.DmmClientHelper'
    $initialize = $dmm.Methods | Where-Object Name -eq 'Initialize'
    $dmmInitializeInstructions = @($initialize.Body.Instructions)
    if ($dmmInitializeInstructions.Count -ne 1 -or
        $dmmInitializeInstructions[0].OpCode.Code -ne 'Ret') {
        throw 'DmmClientHelper.Initialize is not stripped.'
    }

    $entry = $module.Types |
        Where-Object FullName -eq 'Zero.Common.ApplicationEntryPoint'
    $dmmInit = $entry.Methods |
        Where-Object Name -eq 'InitializeAboutDmmAsync'
    $dmmReferences = @(
        $dmmInit.Body.Instructions |
        Where-Object {
            $_.Operand -and
            $_.Operand.ToString().Contains('OpenArgumentErrorDialog')
        }
    )
    if ($dmmReferences.Count -gt 0) {
        throw 'InitializeAboutDmmAsync still opens the DMM argument dialog.'
    }

    $beforeScene = $entry.Methods |
        Where-Object Name -eq 'OnBeforeSceneLoad'
    $beforeInstructions = @($beforeScene.Body.Instructions)
    if ($beforeInstructions[0].Operand -ne [int]$config.debugPort -or
        $beforeInstructions[1].Operand.Name -ne 'EnableRemoteDebugging') {
        throw 'Remote debugging port mismatch.'
    }

    $environment = $module.Types |
        Where-Object FullName -eq 'Zero.Config.Environment'
    $expectedGetters = [ordered]@{
        get_Scheme = 'http://'
        get_Domain = "127.0.0.1:$($config.pagePort)"
        get_CDNDomain = "127.0.0.1:$($config.pagePort)"
        get_URL = "http://127.0.0.1:$($config.pagePort)/assets"
    }
    $actual = [ordered]@{}
    foreach ($name in @(
        'get_Scheme',
        'get_Domain',
        'get_CDNDomain',
        'get_URL'
    )) {
        $method = $environment.Methods | Where-Object Name -eq $name
        $actual[$name] = $method.Body.Instructions[0].Operand
        if ($actual[$name] -ne $expectedGetters[$name]) {
            throw "Environment getter mismatch: $name"
        }
    }
} finally {
    $assembly.Dispose()
}

function Check-Url([string]$url) {
    try {
        $response = Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

[ordered]@{
    dmmInitializeStripped = $true
    dmmDialogAbsent = $true
    environmentGetters = $actual
    debugPort = $config.debugPort
    pageRunning = Check-Url "http://127.0.0.1:$($config.pagePort)/api/state"
    stateRunning = Check-Url "http://127.0.0.1:$($config.statePort)/api/health"
    debugRunning = Check-Url "http://127.0.0.1:$($config.debugPort)/json/version"
} | ConvertTo-Json -Depth 4
