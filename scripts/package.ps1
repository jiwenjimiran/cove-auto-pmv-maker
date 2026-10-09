$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$source = Join-Path $repo 'src/PmvMaker'
$ui = Join-Path $repo 'frontend'
$artifact = Join-Path $repo 'artifacts/AutoPmvMaker'
$companion = Join-Path $repo 'artifacts/AutoPmvMakerCompanion'
$companionZip = Join-Path $repo 'artifacts/AutoPmvMakerCompanion.zip'

Push-Location $ui
try { npm run build; if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' } }
finally { Pop-Location }

dotnet build (Join-Path $source 'PmvMaker.csproj') -c Release
if ($LASTEXITCODE -ne 0) { throw 'Extension build failed.' }

New-Item -ItemType Directory -Force $artifact, (Join-Path $artifact 'dist'), (Join-Path $artifact 'companion'), $companion | Out-Null
New-Item -ItemType Directory -Force (Join-Path $companion 'patches') | Out-Null
Copy-Item (Join-Path $source 'extension.json') $artifact -Force
Copy-Item (Join-Path $source 'bin/Release/net10.0/Cove.PmvMaker.dll') $artifact -Force
Copy-Item (Join-Path $source 'dist/*') (Join-Path $artifact 'dist') -Force
Copy-Item (Join-Path $repo 'companion/*.py') $companion -Force
Copy-Item (Join-Path $repo 'companion/requirements.txt') $companion -Force
Copy-Item (Join-Path $repo 'companion/face_detection_yunet_2023mar.onnx') $companion -Force
Copy-Item (Join-Path $repo 'companion/face_detection_yunet_LICENSE.txt') $companion -Force
Copy-Item (Join-Path $repo 'companion/face_recognition_sface_2021dec.onnx') $companion -Force
Copy-Item (Join-Path $repo 'companion/face_recognition_sface_LICENSE.txt') $companion -Force
Copy-Item (Join-Path $repo 'companion/Start-Companion.ps1') $companion -Force
Copy-Item (Join-Path $repo 'companion/Start Companion.cmd') $companion -Force
Copy-Item (Join-Path $repo 'companion/Start Companion Docker.cmd') $companion -Force
Copy-Item (Join-Path $repo 'companion/Validate Resolve.cmd') $companion -Force
Copy-Item (Join-Path $repo 'companion/Pick Folder.ps1') $companion -Force
Copy-Item (Join-Path $repo 'README.md') $companion -Force
Copy-Item (Join-Path $repo 'patches/cove-ui.patch') (Join-Path $companion 'patches') -Force
$companionFiles = @('engine.py', 'advanced_edit.py', 'source_picker.py', 'music_analysis.py', 'face_analysis.py', 'face_detection_yunet_2023mar.onnx', 'face_detection_yunet_LICENSE.txt', 'face_recognition_sface_2021dec.onnx', 'face_recognition_sface_LICENSE.txt', 'resolve_adapter.py', 'server.py', 'smoke.py', 'requirements.txt',
    'Start-Companion.ps1', 'Start Companion.cmd', 'Start Companion Docker.cmd', 'Validate Resolve.cmd', 'Pick Folder.ps1', 'README.md') |
    ForEach-Object { Join-Path $companion $_ }
$companionFiles += Join-Path $companion 'patches'
Compress-Archive -LiteralPath $companionFiles -DestinationPath $companionZip -Force
Copy-Item $companionZip (Join-Path $artifact 'companion/AutoPmvMakerCompanion.zip') -Force
Compress-Archive -Path (Join-Path $artifact '*') -DestinationPath (Join-Path $repo 'artifacts/AutoPmvMaker.zip') -Force
Write-Host "Packaged one installable extension ZIP with the Windows companion inside $repo/artifacts"
