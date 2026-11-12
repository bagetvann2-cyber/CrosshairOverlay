param(
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'

$AppName  = 'CrosshairOverlay'
$Subject  = 'CN=CrosshairOverlay Local Signing'
$Target   = Join-Path $env:ProgramFiles $AppName
$ExePath  = Join-Path $Target 'CrosshairOverlay.exe'
$StartLnk = Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs\CrosshairOverlay.lnk'
$DeskLnk  = Join-Path ([Environment]::GetFolderPath('Desktop')) 'CrosshairOverlay.lnk'

# 1. Проверка прав администратора
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'Запусти PowerShell от имени администратора' -ForegroundColor Red
    exit 1
}

function Stop-App {
    Get-Process -Name $AppName -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

if ($Uninstall) {
    Stop-App
    if (Test-Path $Target) { Remove-Item -Path $Target -Recurse -Force -ErrorAction SilentlyContinue }
    foreach ($lnk in @($StartLnk, $DeskLnk)) {
        if (Test-Path $lnk) { Remove-Item -Path $lnk -Force -ErrorAction SilentlyContinue }
    }
    foreach ($store in @('Cert:\LocalMachine\Root', 'Cert:\LocalMachine\TrustedPublisher', 'Cert:\CurrentUser\My')) {
        Get-ChildItem $store -ErrorAction SilentlyContinue |
            Where-Object { $_.Subject -eq $Subject } |
            ForEach-Object { Remove-Item -Path $_.PSPath -Force -ErrorAction SilentlyContinue }
    }
    Write-Host 'CrosshairOverlay удалён: папка, ярлыки и сертификат.' -ForegroundColor Green
    exit 0
}

# 2. Источник
# Ищем программу: рядом со скриптом (архив из релиза) или в dist (после сборки из исходников)
$Source = @(
    (Join-Path $PSScriptRoot 'CrosshairOverlay'),
    (Join-Path $PSScriptRoot 'dist\CrosshairOverlay')
) | Where-Object { Test-Path (Join-Path $_ 'CrosshairOverlay.exe') } | Select-Object -First 1
if (-not $Source) {
    Write-Host 'Не найдена папка CrosshairOverlay с программой рядом со скриптом.' -ForegroundColor Red
    Write-Host 'Распакуй архив целиком или сначала собери exe.' -ForegroundColor Red
    exit 1
}

# 3. Останавливаем запущенный процесс
Stop-App

# 4. Сертификат
$cert = Get-ChildItem Cert:\CurrentUser\My |
    Where-Object { $_.Subject -eq $Subject -and $_.HasPrivateKey -and $_.NotAfter -gt (Get-Date) } |
    Sort-Object NotAfter -Descending |
    Select-Object -First 1
if (-not $cert) {
    Write-Host 'Создаю сертификат подписи...'
    $cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject $Subject `
        -CertStoreLocation Cert:\CurrentUser\My -KeyExportPolicy NonExportable `
        -NotAfter (Get-Date).AddYears(10)
}

# 5. Доверие к сертификату
$trusted = Get-ChildItem Cert:\LocalMachine\Root | Where-Object { $_.Thumbprint -eq $cert.Thumbprint }
if (-not $trusted) {
    Write-Host 'Добавляю сертификат в доверенные...'
    $cer = Join-Path $env:TEMP 'CrosshairOverlay_signing.cer'
    try {
        Export-Certificate -Cert $cert -FilePath $cer -Type CERT | Out-Null
        Import-Certificate -FilePath $cer -CertStoreLocation Cert:\LocalMachine\Root | Out-Null
        Import-Certificate -FilePath $cer -CertStoreLocation Cert:\LocalMachine\TrustedPublisher | Out-Null
    } finally {
        if (Test-Path $cer) { Remove-Item $cer -Force -ErrorAction SilentlyContinue }
    }
}

# 6. Копирование в Program Files
New-Item -ItemType Directory -Path $Target -Force | Out-Null
$internal = Join-Path $Target '_internal'
if (Test-Path $internal) { Remove-Item -Path $internal -Recurse -Force }
Copy-Item -Path (Join-Path $Source '*') -Destination $Target -Recurse -Force

# 7. Подпись
$sig = Set-AuthenticodeSignature -FilePath $ExePath -Certificate $cert -HashAlgorithm SHA256
if ($sig.Status -ne 'Valid') {
    Write-Host "Ошибка подписи: $($sig.Status). $($sig.StatusMessage)" -ForegroundColor Red
    exit 1
}

# 8. Ярлыки
$shell = New-Object -ComObject WScript.Shell
foreach ($lnk in @($StartLnk, $DeskLnk)) {
    $s = $shell.CreateShortcut($lnk)
    $s.TargetPath = $ExePath
    $s.WorkingDirectory = $Target
    $s.Save()
}

# 9. Итог
Write-Host ''
Write-Host "Готово. Установлено в: $Target" -ForegroundColor Green
Write-Host 'Запускай ярлык (рабочий стол или меню Пуск) или exe из Program Files.'
Write-Host 'Exe из папки dist теперь сам по себе не запустится, это нормально.'
Write-Host 'После каждой пересборки запускай этот скрипт снова.'
