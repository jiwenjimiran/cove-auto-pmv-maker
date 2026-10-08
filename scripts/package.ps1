$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$source = Join-Path $repo 'src/PmvMaker'
$ui = Join-Path $repo 'frontend'
$artifact = Join-Path $repo 'artifacts/AutoPmvMaker'
$companion = Join-Path $repo 'artifacts/AutoPmvMakerCompanion'

Push-Location $ui
try { npm run build; if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' } }
finally { Pop-Location }

dotnet build (Join-Path $source 'PmvMaker.csproj') -c Release
if ($LASTEXITCODE -ne 0) { throw 'Extension build failed.' }

New-Item -ItemType Directory -Force $artifact, (Join-Path $artifact 'dist'), $companion | Out-Null
New-Item -ItemType Directory -Force (Join-Path $companion 'patches') | Out-Null
Copy-Item (Join-Path $source 'extension.json') $artifact -Force
Copy-Item (Join-Path $source 'bin/Release/net10.0/Cove.PmvMaker.dll') $artifact -Force
Copy-Item (Join-Path $source 'dist/*') (Join-Path $artifact 'dist') -Force
Copy-Item (Join-Path $repo 'companion/*.py') $companion -Force
Copy-Item (Join-Path $repo 'companion/requirements.txt') $companion -Force
Copy-Item (Join-Path $repo 'README.md') $companion -Force
Copy-Item (Join-Path $repo 'patches/cove-ui.patch') (Join-Path $companion 'patches') -Force
Compress-Archive -Path (Join-Path $artifact '*') -DestinationPath (Join-Path $repo 'artifacts/AutoPmvMaker.zip') -Force
Compress-Archive -Path (Join-Path $companion '*') -DestinationPath (Join-Path $repo 'artifacts/AutoPmvMakerCompanion.zip') -Force
Write-Host "Packaged extension and Windows companion under $repo/artifacts"
