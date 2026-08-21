!define PRODUCT_NAME "Admira IA Cloud Installer"
!define PRODUCT_VERSION "@@VERSION@@"
!define INSTALL_SOURCE "@@STAGING_DIR@@"

Name "${PRODUCT_NAME}"
OutFile "@@EXE_PATH@@"
InstallDir "$LOCALAPPDATA\Admira IA Cloud Installer"
RequestExecutionLevel user
SilentInstall silent
SilentUnInstall silent
AutoCloseWindow true
ShowInstDetails nevershow

Section "Install"
  SetOutPath "$INSTDIR"
  File /r "${INSTALL_SOURCE}\*.*"
  ExecWait '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -STA -File "$INSTDIR\installer\windows\AdmiraCloudInstaller.ps1"'
  CreateShortcut "$DESKTOP\Instalar Admira IA en la nube.lnk" "$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" '-NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -STA -File "$INSTDIR\installer\windows\AdmiraCloudInstaller.ps1"' "$INSTDIR\installer\windows\AdmiraCloudInstaller.ps1" 0 SW_SHOWNORMAL
  CreateShortcut "$SMPROGRAMS\Instalar Admira IA en la nube.lnk" "$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" '-NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -STA -File "$INSTDIR\installer\windows\AdmiraCloudInstaller.ps1"' "$INSTDIR\installer\windows\AdmiraCloudInstaller.ps1" 0 SW_SHOWNORMAL
  WriteUninstaller "$INSTDIR\Desinstalar Admira IA Cloud Installer.exe"
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\Instalar Admira IA en la nube.lnk"
  Delete "$SMPROGRAMS\Instalar Admira IA en la nube.lnk"
  RMDir /r "$INSTDIR"
SectionEnd
