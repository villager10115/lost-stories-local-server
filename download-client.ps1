param(
    [string]$Destination = (Get-Location).Path,
    [string]$Repository = "villager10115/lost-stories-local-server"
)

$ErrorActionPreference = "Stop"
$releaseUrl = "https://api.github.com/repos/$Repository/releases/latest"
$headers = @{ "User-Agent" = "lost-stories-local-server-installer" }

Write-Host "Checking latest client release..."
$release = Invoke-RestMethod -Uri $releaseUrl -Headers $headers
$assets = @($release.assets)
if ($assets.Count -eq 0) {
    throw "The latest release has no downloadable assets."
}

$parts = @(
    $assets |
        Where-Object { $_.name -match '^LostStories_Japanese_Clean_NoAccount_.*\.zip\.part\d+$' } |
        Sort-Object name
)
$checksumAsset = $assets |
    Where-Object { $_.name -match '^LostStories_Japanese_Clean_NoAccount_.*\.zip\.sha256$' } |
    Select-Object -First 1
if ($parts.Count -eq 0 -or $null -eq $checksumAsset) {
    throw "The release is incomplete: ZIP parts or checksum asset is missing."
}

$expectedText = (Invoke-RestMethod -Uri $checksumAsset.browser_download_url -Headers $headers).ToString().Trim()
$expectedHash = ($expectedText -split '\s+')[0].ToUpperInvariant()
if ($expectedHash -notmatch '^[0-9A-F]{64}$') {
    throw "The release checksum is invalid."
}

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("lost-stories-client-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot | Out-Null
$zipPath = Join-Path $tempRoot "LostStories_Japanese_Clean_NoAccount.zip"

try {
    $partPaths = @()
    $index = 0
    foreach ($asset in $parts) {
        $index++
        $partPath = Join-Path $tempRoot ("part-{0:D3}" -f $index)
        Write-Host ("Downloading {0}/{1}: {2} ({3:N2} GiB)" -f `
            $index, $parts.Count, $asset.name, ($asset.size / 1GB))
        Invoke-WebRequest -Uri $asset.browser_download_url -Headers $headers -OutFile $partPath
        $partPaths += $partPath
    }

    Write-Host "Joining and verifying client archive..."
    $output = [System.IO.File]::Open(
        $zipPath,
        [System.IO.FileMode]::Create,
        [System.IO.FileAccess]::Write,
        [System.IO.FileShare]::None
    )
    try {
        foreach ($partPath in $partPaths) {
            $input = [System.IO.File]::OpenRead($partPath)
            try {
                $input.CopyTo($output)
            }
            finally {
                $input.Dispose()
            }
        }
    }
    finally {
        $output.Dispose()
    }

    $actualHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash
    if ($actualHash -ne $expectedHash) {
        throw "Archive checksum mismatch. Expected $expectedHash, got $actualHash."
    }

    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    Write-Host "Extracting to $Destination ..."
    $tar = Get-Command tar.exe -ErrorAction SilentlyContinue
    if ($null -ne $tar) {
        & $tar.Source -xf $zipPath -C $Destination
        if ($LASTEXITCODE -ne 0) {
            throw "tar.exe failed with exit code $LASTEXITCODE."
        }
    }
    else {
        Expand-Archive -LiteralPath $zipPath -DestinationPath $Destination -Force
    }

    $package = Join-Path $Destination "LostStories_Japanese"
    Write-Host ""
    Write-Host "Client downloaded to: $package"
    Write-Host "No account, save database or browser cache is included."
    Write-Host "Start with: $package\launcher\portable_launcher.py using its packaged Python runtime,"
    Write-Host "or use the packaged shortcut/launcher described in README."
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
