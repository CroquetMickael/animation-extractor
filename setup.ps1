# One-shot installer: everything lands inside this folder (Python, packages, models, caches).
# Usage:  powershell -ExecutionPolicy Bypass -File setup.ps1 [-GtaFolder "D:\GTAV"]
param([string]$GtaFolder = "")

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Tools = Join-Path $Root ".tools"
$env:UV_CACHE_DIR = Join-Path $Tools "uv-cache"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Tools "python"
$Uv = Join-Path $Tools "uvpkg\bin\uv.exe"
$Py = Join-Path $Root ".venv\Scripts\python.exe"

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Yellow }

Step "uv (gestionnaire Python)"
if (-not (Test-Path $Uv)) {
    New-Item -ItemType Directory -Force $Tools | Out-Null
    py -3 -m pip install --quiet --target (Join-Path $Tools "uvpkg") uv
}

Step "Python 3.10 + environnement isolé"
if (-not (Test-Path $Py)) { & $Uv venv --python 3.10 (Join-Path $Root ".venv") }

Step "PyTorch CUDA 12.8"
& $Uv pip install --python $Py torch torchvision --index-url https://download.pytorch.org/whl/cu128

Step "Dépendances"
& $Uv pip install --python $Py -r (Join-Path $Root "requirements.txt")

Step "Configuration"
if ($GtaFolder -ne "") {
    @{ gta_folder = $GtaFolder; default_ped = "mp_m_freemode_01" } | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $Root "config.json")
}

Step "CodeWalker + gtabridge (.NET 8)"
$Cw = Join-Path $Root "third_party\CodeWalker"
if (-not (Test-Path $Cw)) { git clone --depth 1 https://github.com/dexyfex/CodeWalker.git $Cw }
dotnet build (Join-Path $Root "bridge\GtaBridge.csproj") -c Release --nologo -v quiet

Step "Peds freemode extraits de GTA V"
& $Py -m animx peds
& $Py -m animx handposes

Step "Modèles MediaPipe (Google)"
$Models = Join-Path $Root "assets\models"
New-Item -ItemType Directory -Force $Models | Out-Null
$mp = @{
    "pose_landmarker_heavy.task" = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task"
    "hand_landmarker.task"       = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
}
foreach ($name in $mp.Keys) {
    $target = Join-Path $Models $name
    if (-not (Test-Path $target)) { curl.exe -sfL -o $target $mp[$name] }
}

Step "GVHMR + poids"
$Gv = Join-Path $Root "third_party\GVHMR"
if (-not (Test-Path $Gv)) { git clone --depth 1 https://github.com/zju3dv/GVHMR.git $Gv }
$Ck = Join-Path $Gv "inputs\checkpoints"
foreach ($dir in "gvhmr", "hmr2", "vitpose", "yolo", "body_models\smpl", "body_models\smplx") { New-Item -ItemType Directory -Force (Join-Path $Ck $dir) | Out-Null }
$weights = @{
    "gvhmr\gvhmr_siga24_release.ckpt"   = "https://huggingface.co/camenduru/GVHMR/resolve/main/gvhmr/gvhmr_siga24_release.ckpt"
    "hmr2\epoch=10-step=25000.ckpt"     = "https://huggingface.co/camenduru/GVHMR/resolve/main/hmr2/epoch=10-step=25000.ckpt"
    "vitpose\vitpose-h-multi-coco.pth"  = "https://huggingface.co/camenduru/GVHMR/resolve/main/vitpose/vitpose-h-multi-coco.pth"
    "yolo\yolov8x.pt"                   = "https://github.com/ultralytics/assets/releases/download/v8.2.0/yolov8x.pt"
}
foreach ($rel in $weights.Keys) {
    $target = Join-Path $Ck $rel
    if (-not (Test-Path $target)) { curl.exe -sfL --retry 3 -o $target $weights[$rel] }
}

Step "Interface"
Push-Location (Join-Path $Root "ui")
npm install --no-fund --no-audit
npx vite build
Pop-Location

Step "Vérification"
& $Py -m animx doctor
$Smplx = Join-Path $Ck "body_models\smplx\SMPLX_NEUTRAL.npz"
if (-not (Test-Path $Smplx)) {
    Write-Host "`nGVHMR : il reste a deposer SMPLX_NEUTRAL.npz (compte gratuit sur https://smpl-x.is.tue.mpg.de) dans :" -ForegroundColor Cyan
    Write-Host "  $(Split-Path $Smplx)" -ForegroundColor Cyan
}
Write-Host "`nInstallation terminee. Lancer : animx.bat" -ForegroundColor Green
