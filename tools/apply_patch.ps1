# Patch faylni xavfsiz qo'llaydi: avval tekshiradi, keyin qo'llaydi.
#   .\tools\apply_patch.ps1 changes.patch
param([Parameter(Mandatory=$true)][string]$Patch)

if (-not (Test-Path .git)) {
    Write-Host "Bu papkada git repo yo'q. Avval bir marta:" -ForegroundColor Yellow
    Write-Host "  git init; git add -A; git commit -m 'baseline'"
    exit 1
}

$dirty = git status --porcelain
if ($dirty) {
    Write-Host "Saqlanmagan o'zgarishlar bor. Avval commit qiling:" -ForegroundColor Yellow
    Write-Host "  git add -A; git commit -m 'my changes'"
    Write-Host ""
    git status --short
    exit 1
}

Write-Host "Tekshirilmoqda..." -ForegroundColor Cyan
git apply --check --whitespace=nowarn $Patch
if ($LASTEXITCODE -ne 0) {
    Write-Host "Patch mos kelmadi — fayllaringiz kutilgan holatdan farq qiladi." -ForegroundColor Red
    exit 1
}

git apply --whitespace=nowarn --stat $Patch
git apply --whitespace=nowarn $Patch
Write-Host "Qo'llandi. O'zgarishlarni ko'rish: git diff" -ForegroundColor Green
Write-Host "Qaytarish kerak bo'lsa:      git checkout ." -ForegroundColor DarkGray
