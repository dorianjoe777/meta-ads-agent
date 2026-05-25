!define PRODUCT_NAME "Meta Ads Agent"
!define PRODUCT_VERSION "@@VERSION@@"
!define INSTALL_SOURCE "@@STAGING_DIR@@"

Name "${PRODUCT_NAME}"
OutFile "@@EXE_PATH@@"
InstallDir "$LOCALAPPDATA\Meta Ads Agent"
RequestExecutionLevel user
ShowInstDetails show

Page directory
Page instfiles

Section "Install"
  SetOutPath "$INSTDIR"
  File /r "${INSTALL_SOURCE}\*.*"

  CreateShortcut "$DESKTOP\Meta Ads Agent.lnk" "$INSTDIR\Instalar en Windows.bat" "" "$INSTDIR\Instalar en Windows.bat" 0
  CreateShortcut "$SMPROGRAMS\Meta Ads Agent.lnk" "$INSTDIR\Instalar en Windows.bat" "" "$INSTDIR\Instalar en Windows.bat" 0

  WriteUninstaller "$INSTDIR\Desinstalar Meta Ads Agent.exe"
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\Meta Ads Agent.lnk"
  Delete "$SMPROGRAMS\Meta Ads Agent.lnk"
  RMDir /r "$INSTDIR"
SectionEnd
