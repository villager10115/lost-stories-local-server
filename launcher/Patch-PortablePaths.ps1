param([Parameter(Mandatory=$true)][string]$Root)
$ErrorActionPreference = 'Stop'
$rootPath = (Resolve-Path -LiteralPath $Root).Path
Add-Type -Path (Join-Path $rootPath 'app\tools\Mono.Cecil.dll')
$managed = Join-Path (@(Get-ChildItem (Join-Path $rootPath 'Client') -Directory -Filter '*_Data')[0].FullName) 'Managed'
$backup = Join-Path $rootPath ('snapshots\portable-path-patch-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $backup -ErrorAction Stop | Out-Null
function Get-AllTypes($types) {
    foreach ($type in $types) {
        $type
        if ($type.HasNestedTypes) { Get-AllTypes $type.NestedTypes }
    }
}
$records = @()
$resolver = [Mono.Cecil.DefaultAssemblyResolver]::new()
$resolver.AddSearchDirectory($managed)
$parameters = [Mono.Cecil.ReaderParameters]::new()
$parameters.AssemblyResolver = $resolver
foreach ($file in Get-ChildItem -LiteralPath $managed -Filter '*.dll') {
    $assembly = [Mono.Cecil.AssemblyDefinition]::ReadAssembly($file.FullName, $parameters)
    try {
        $module = $assembly.MainModule
        $sites = @()
        foreach ($type in @(Get-AllTypes $module.Types)) {
            foreach ($method in $type.Methods) {
                if (-not $method.HasBody) { continue }
                foreach ($instruction in $method.Body.Instructions) {
                    if ($instruction.OpCode.Code -eq 'Call' -and
                        $instruction.Operand -is [Mono.Cecil.MethodReference] -and
                        $instruction.Operand.FullName -eq 'System.String UnityEngine.Application::get_persistentDataPath()') {
                        $sites += [pscustomobject]@{Instruction=$instruction; Method=$method.FullName}
                    }
                }
            }
        }
        if ($sites.Count -eq 0) { continue }
        if ($module.Types | Where-Object FullName -eq 'LocalPortable.Paths') { throw 'Already patched' }
        $before = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
        Copy-Item -LiteralPath $file.FullName -Destination (Join-Path $backup $file.Name)
        $type = [Mono.Cecil.TypeDefinition]::new('LocalPortable', 'Paths',
            [Mono.Cecil.TypeAttributes]385, $module.TypeSystem.Object)
        $module.Types.Add($type)
        $helper = [Mono.Cecil.MethodDefinition]::new('GetDataRoot',
            [Mono.Cecil.MethodAttributes]22, $module.TypeSystem.String)
        $type.Methods.Add($helper)
        $dataPath = [Mono.Cecil.MethodReference]::new('get_dataPath', $module.TypeSystem.String, $sites[0].Instruction.Operand.DeclaringType)
        $combineInfo = [IO.Path].GetMethod('Combine', [type[]]@([string],[string]))
        $fullInfo = [IO.Path].GetMethod('GetFullPath', [type[]]@([string]))
        $combine = $module.ImportReference([System.Reflection.MethodBase]$combineInfo)
        $full = $module.ImportReference([System.Reflection.MethodBase]$fullInfo)
        $il = $helper.Body.GetILProcessor()
        $il.Append($il.Create([Mono.Cecil.Cil.OpCodes]::Call, $dataPath))
        $il.Append($il.Create([Mono.Cecil.Cil.OpCodes]::Ldstr, '../../data/native'))
        $il.Append($il.Create([Mono.Cecil.Cil.OpCodes]::Call, $combine))
        $il.Append($il.Create([Mono.Cecil.Cil.OpCodes]::Call, $full))
        $il.Append($il.Create([Mono.Cecil.Cil.OpCodes]::Ret))
        foreach ($site in $sites) { $site.Instruction.Operand = $helper }
        $temporary = $file.FullName + '.portable'
        $assembly.Write($temporary)
        $records += [pscustomobject]@{file=$file.Name; inputSha256=$before;
            outputSha256=(Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash;
            callCount=$sites.Count; methods=@($sites | ForEach-Object {$_.Method})}
    } finally { $assembly.Dispose() }
}
$resolver.Dispose()
if ($records.Count -eq 0) { throw 'No persistent data path calls found' }
try {
    foreach ($record in $records) {
        $destination = Join-Path $managed $record.file
        if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ne $record.inputSha256) {
            throw ('Input changed: ' + $record.file)
        }
        Move-Item -LiteralPath ($destination + '.portable') -Destination $destination -Force
        if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ne $record.outputSha256) {
            throw ('Output mismatch: ' + $record.file)
        }
    }
} catch {
    foreach ($record in $records) {
        Copy-Item -LiteralPath (Join-Path $backup $record.file) -Destination (Join-Path $managed $record.file) -Force
    }
    throw
}
$records | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $rootPath 'reports\portable-path-patch.json') -Encoding UTF8
$records | Select-Object file,callCount | Format-Table
