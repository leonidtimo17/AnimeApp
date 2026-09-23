# Сборка подписанного APK.
# Android Gradle не работает, если в пути есть не-латинские символы (например, «Комп» в имени пользователя),
# поэтому проект копируется в C:\Users\Public\AnimeAppBuild и собирается там.
$ErrorActionPreference = "Stop"
$src = $PSScriptRoot
$work = "C:\Users\Public\AnimeAppBuild"
$env:JAVA_HOME = (Get-ChildItem "C:\Program Files\Microsoft\jdk-21*" -Directory | Select-Object -First 1).FullName
$env:GRADLE_USER_HOME = "$work\gradle-home"
$sdk = "$env:LOCALAPPDATA\Android\Sdk"
# SDK тоже лежит в профиле с кириллицей — даём Gradle латинский путь через ссылку (junction)
$sdkLink = "$work\android-sdk"
New-Item -ItemType Directory -Force "$work\mobile" | Out-Null
if (-not (Test-Path $sdkLink)) { cmd /c mklink /J "$sdkLink" "$sdk" | Out-Null }
$env:ANDROID_HOME = $sdkLink

# Правовые документы кладём в www, чтобы они попали в APK
New-Item -ItemType Directory -Force "$src\www\legal" | Out-Null
Copy-Item "$src\..\TERMS.md", "$src\..\PRIVACY.md" "$src\www\legal" -Force

Push-Location $src
npx cap sync android
Pop-Location

# Копируем проект (без результатов прошлых сборок)
robocopy $src "$work\mobile" /MIR /XD build .gradle /NFL /NDL /NJH /NJS /NP | Out-Null
Set-Content "$work\mobile\android\local.properties" ("sdk.dir=" + ($sdkLink -replace "\\", "/")) -Encoding ascii

Push-Location "$work\mobile\android"
.\gradlew.bat assembleRelease --no-daemon
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { throw "Сборка APK не удалась (код $code)" }

$version = (Get-Content "$src\package.json" | ConvertFrom-Json).version
New-Item -ItemType Directory -Force "$src\dist" | Out-Null
$apk = "$src\dist\AnimeApp-$version.apk"
Copy-Item "$work\mobile\android\app\build\outputs\apk\release\app-release.apk" $apk -Force
Write-Host "Готово: $apk"
