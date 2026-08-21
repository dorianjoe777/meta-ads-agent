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

  CreateShortcut "$DESKTOP\Admira IA.lnk" "$WINDIR\System32\wscript.exe" '"$INSTDIR\Abrir Admira IA.vbs"' "$WINDIR\System32\wscript.exe" 0 SW_SHOWNORMAL
  CreateShortcut "$SMPROGRAMS\Admira IA.lnk" "$WINDIR\System32\wscript.exe" '"$INSTDIR\Abrir Admira IA.vbs"' "$WINDIR\System32\wscript.exe" 0 SW_SHOWNORMAL

  WriteUninstaller "$INSTDIR\Desinstalar Meta Ads Agent.exe"
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\Admira IA.lnk"
  Delete "$SMPROGRAMS\Admira IA.lnk"
  Delete "$DESKTOP\Meta Ads Agent.lnk"
  Delete "$SMPROGRAMS\Meta Ads Agent.lnk"
  RMDir /r "$INSTDIR"
SectionEnd
