use framework "Cocoa"
use scripting additions

property parent : class "NSObject"
property installerWindow : missing value
property emailField : missing value
property licenseField : missing value
property installButton : missing value
property progressBar : missing value
property statusLabel : missing value
property detailLabel : missing value
property stepLabel : missing value
property dashboardButton : missing value
property logButton : missing value
property task : missing value
property emailValue : ""
property licenseValue : ""
property transferRetry : false
property frontTicks : 0
property aquaColor : missing value
property mutedColor : missing value
property panelColor : missing value

on run
    try
        current application's NSApp's setActivationPolicy_(current application's NSApplicationActivationPolicyRegular)
        my buildInterface()
        current application's NSApp's activateIgnoringOtherApps_(true)
        set runningApp to current application's NSRunningApplication's currentApplication()
        runningApp's activateWithOptions_(current application's NSApplicationActivateIgnoringOtherApps)
        current application's NSApp's |run|()
    on error errorMessage number errorNumber
        do shell script "/usr/bin/printf '%s\\n' " & quoted form of (errorMessage & " (" & errorNumber & ")") & " >> /tmp/admira-installer-window.log"
    end try
end run

on idle
    -- LaunchServices may start an applet behind the current app. Bring the
    -- first-run window forward for a few seconds so a double-click never looks
    -- like a no-op, without keeping it permanently above other applications.
    if installerWindow is not missing value and frontTicks < 10 then
        installerWindow's orderFrontRegardless()
        set runningApp to current application's NSRunningApplication's currentApplication()
        runningApp's activateWithOptions_(current application's NSApplicationActivateIgnoringOtherApps)
        set frontTicks to frontTicks + 1
    end if
    return 1
end idle

on buildInterface()
    set aquaColor to current application's NSColor's colorWithCalibratedRed_green_blue_alpha_(0.27, 0.85, 0.74, 1.0)
    set mutedColor to current application's NSColor's colorWithCalibratedRed_green_blue_alpha_(0.67, 0.74, 0.84, 1.0)
    set panelColor to current application's NSColor's colorWithCalibratedRed_green_blue_alpha_(0.075, 0.12, 0.22, 1.0)
    set bgColor to current application's NSColor's colorWithCalibratedRed_green_blue_alpha_(0.035, 0.065, 0.13, 1.0)
    set frameRect to current application's NSMakeRect(0, 0, 680, 590)
    -- Include resizing explicitly; the literal mask is more reliable in
    -- AppleScriptObjC applets than bridging the individual enum constants.
    set styleMask to 15
    set installerWindow to current application's NSWindow's alloc()'s initWithContentRect_styleMask_backing_defer_(frameRect, styleMask, current application's NSBackingStoreBuffered, false)
    installerWindow's setTitle_("Admira IA · Instalación")
    installerWindow's setFrameOrigin_(current application's NSMakePoint(120, 130))
    installerWindow's setBackgroundColor_(bgColor)
    set contentView to installerWindow's contentView()
    contentView's setWantsLayer_(true)

    my addLabel("ADMIRA IA", 31, true, {46, 532, 400, 42}, contentView, {"header"})
    my addLabel("Tu espacio de trabajo, listo en unos minutos.", 15, false, {46, 500, 480, 24}, contentView, {"subtitle"})
    my addLabel("INSTALADOR PARA macOS", 11, true, {510, 540, 130, 20}, contentView, {"version"})

    set panel to current application's NSView's alloc()'s initWithFrame_(current application's NSMakeRect(38, 82, 604, 385))
    panel's setWantsLayer_(true)
    panel's layer()'s setCornerRadius_(12.0)
    contentView's addSubview_(panel)

    my addLabel("Correo usado para comprar Admira IA", 13, true, {28, 330, 400, 22}, panel, {})
    set emailField to my addTextField("correo@ejemplo.com", false, {28, 291, 548, 34}, panel)
    my addLabel("Licencia de Admira IA", 13, true, {28, 254, 400, 22}, panel, {})
    set licenseField to my addTextField("MAO-…", true, {28, 215, 548, 34}, panel)

    set installButton to current application's NSButton's alloc()'s initWithFrame_(current application's NSMakeRect(28, 160, 548, 42))
    installButton's setTitle_("Comenzar instalación")
    installButton's setBezelStyle_(current application's NSBezelStyleRounded)
    installButton's setFont_(current application's NSFont's systemFontOfSize_weight_(15, current application's NSFontWeightSemibold))
    installButton's setContentTintColor_(current application's NSColor's colorWithCalibratedRed_green_blue_alpha_(0.02, 0.10, 0.13, 1.0))
    installButton's setTarget_(me)
    installButton's setAction_("beginInstallation:")
    installButton's setWantsLayer_(true)
    installButton's layer()'s setCornerRadius_(6.0)
    panel's addSubview_(installButton)

    set statusLabel to my addLabel("Listo para instalar", 16, true, {28, 119, 390, 25}, panel, {})
    set stepLabel to my addLabel("Paso 1 de 4", 12, false, {480, 120, 96, 22}, panel, {})
    stepLabel's setAlignment_(current application's NSTextAlignmentRight)
    set detailLabel to my addLabel("Docker Desktop y Admira IA se instalarán en tu Mac. El dashboard se abrirá en el navegador.", 13, false, {28, 80, 548, 36}, panel, {})
    detailLabel's setMaximumNumberOfLines_(2)
    set progressBar to current application's NSProgressIndicator's alloc()'s initWithFrame_(current application's NSMakeRect(28, 52, 548, 12))
    progressBar's setIndeterminate_(false)
    progressBar's setMinValue_(0)
    progressBar's setMaxValue_(100)
    progressBar's setDoubleValue_(0)
    progressBar's setStyle_(current application's NSProgressIndicatorBarStyle)
    panel's addSubview_(progressBar)

    set dashboardButton to current application's NSButton's alloc()'s initWithFrame_(current application's NSMakeRect(440, 10, 136, 30))
    dashboardButton's setTitle_("Abrir dashboard")
    dashboardButton's setBezelStyle_(current application's NSBezelStyleRounded)
    dashboardButton's setTarget_(me)
    dashboardButton's setAction_("openDashboard:")
    dashboardButton's setHidden_(true)
    panel's addSubview_(dashboardButton)

    set logButton to current application's NSButton's alloc()'s initWithFrame_(current application's NSMakeRect(46, 50, 100, 22))
    logButton's setTitle_("Ver registro")
    logButton's setBezelStyle_(current application's NSBezelStyleInline)
    logButton's setContentTintColor_(mutedColor)
    logButton's setTarget_(me)
    logButton's setAction_("openLogs:")
    contentView's addSubview_(logButton)
    my addLabel("La licencia se guarda de forma segura durante la instalación y se elimina al finalizar.", 11, false, {46, 17, 580, 22}, contentView, {})
    my addLabel("Admira IA funciona dentro de Docker; el acceso final es un enlace del navegador.", 11, false, {46, 3, 580, 22}, contentView, {})
    -- AppleScript applets can be launched without becoming the active macOS app.
    -- A normal makeKeyAndOrderFront_ call then leaves the window behind whatever
    -- the user was doing (which looks like the installer opened and immediately
    -- disappeared). Keep the setup window visible until the user finishes.
    installerWindow's setLevel_(current application's NSFloatingWindowLevel)
    installerWindow's makeKeyAndOrderFront_(missing value)
    installerWindow's orderFrontRegardless()
end

on addLabel(theText, fontSize, isBold, frameValues, parentView, tagValue)
    set label to current application's NSTextField's labelWithString_(theText)
    label's setFrame_(current application's NSMakeRect(item 1 of frameValues, item 2 of frameValues, item 3 of frameValues, item 4 of frameValues))
    if isBold then
        label's setFont_(current application's NSFont's systemFontOfSize_weight_(fontSize, current application's NSFontWeightSemibold))
    else
        label's setFont_(current application's NSFont's systemFontOfSize_(fontSize))
    end if
    label's setTextColor_(mutedColor)
    if fontSize > 20 then label's setTextColor_(current application's NSColor's whiteColor())
    if fontSize = 11 then label's setTextColor_(mutedColor)
    parentView's addSubview_(label)
    return label
end

on addTextField(placeholderText, isSecure, frameValues, parentView)
    if isSecure then
        set field to current application's NSSecureTextField's alloc()'s initWithFrame_(current application's NSMakeRect(item 1 of frameValues, item 2 of frameValues, item 3 of frameValues, item 4 of frameValues))
    else
        set field to current application's NSTextField's alloc()'s initWithFrame_(current application's NSMakeRect(item 1 of frameValues, item 2 of frameValues, item 3 of frameValues, item 4 of frameValues))
    end if
    field's setPlaceholderString_(placeholderText)
    field's setFont_(current application's NSFont's systemFontOfSize_(14))
    field's setTextColor_(current application's NSColor's whiteColor())
    field's setBackgroundColor_(current application's NSColor's colorWithCalibratedWhite_alpha_(0.08, 1.0))
    field's setBezeled_(true)
    field's setEditable_(true)
    parentView's addSubview_(field)
    return field
end

on beginInstallation_(sender)
    set emailValue to ((emailField's stringValue()) as text)
    set licenseValue to ((licenseField's stringValue()) as text)
    set emailValue to my trimText(emailValue)
    set licenseValue to my trimText(licenseValue)
    set emailValue to my lowerText(emailValue)
    set licenseValue to my upperText(licenseValue)
    set emailRange to (current application's NSString's stringWithString_(emailValue))'s rangeOfString_options_("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$", current application's NSRegularExpressionSearch)
    if (emailRange's |location|() as integer) = (current application's NSNotFound as integer) then
        my showAlert("Correo no válido", "Escribe el correo utilizado para comprar Admira IA.")
        return
    end if
    set licenseRange to (current application's NSString's stringWithString_(licenseValue))'s rangeOfString_options_("^[A-Z0-9][A-Z0-9-]{7,120}$", current application's NSRegularExpressionSearch)
    if (licenseRange's |location|() as integer) = (current application's NSNotFound as integer) then
        my showAlert("Licencia no válida", "Pega la licencia completa, por ejemplo MAO-…")
        return
    end if
    installButton's setEnabled_(false)
    emailField's setEnabled_(false)
    licenseField's setEnabled_(false)
    statusLabel's setStringValue_("Preparando la instalación…")
    detailLabel's setStringValue_("No cierres esta ventana. Docker Desktop puede tardar unos minutos la primera vez.")
    progressBar's setIndeterminate_(true)
    progressBar's startAnimation_(me)
    my launchEngine()
end

on launchEngine()
    set currentAppPath to POSIX path of (path to me)
    set installedPath to (POSIX path of (path to home folder)) & "Applications/Admira IA Installer.app"
    if currentAppPath does not start with installedPath then
        do shell script "/bin/mkdir -p " & quoted form of ((POSIX path of (path to home folder)) & "Applications") & "; /usr/bin/ditto " & quoted form of currentAppPath & " " & quoted form of installedPath
    end if
    set enginePath to installedPath & "/Contents/Resources/admira-mac-engine.sh"
    set task to current application's NSTask's alloc()'s init()
    task's setLaunchPath_("/bin/bash")
    task's setArguments_({enginePath, "--gui"})
    set env to current application's NSMutableDictionary's dictionaryWithDictionary_(current application's NSProcessInfo's processInfo()'s environment())
    env's setObject_forKey_(emailValue, "ADMIRA_INSTALLER_EMAIL")
    env's setObject_forKey_(licenseValue, "ADMIRA_INSTALLER_LICENSE")
    if transferRetry then env's setObject_forKey_("true", "ADMIRA_TRANSFER_DEVICE")
    task's setEnvironment_(env)
    task's |launch|()
    repeat while task's |isRunning|()
        my pollStatus(missing value)
        delay 1
    end repeat
    my pollStatus(missing value)
    my taskFinished_(missing value)
end

on pollStatus_(timer)
    set statusPath to (POSIX path of (path to home folder)) & "Library/Application Support/Admira IA/Installer/status.txt"
    try
        set statusText to do shell script "/bin/cat " & quoted form of statusPath
        set rows to paragraphs of statusText
        if (count rows) ≥ 3 then my consumeStatus(item 1 of rows, item 2 of rows, item 3 of rows)
    end try
end

on consumeStatus(stageName, percentText, messageText)
    try
        progressBar's setDoubleValue_(percentText as real)
    end try
    detailLabel's setStringValue_(messageText)
    if stageName is "docker" then
        statusLabel's setStringValue_("Preparando Docker Desktop…")
        stepLabel's setStringValue_("Paso 1 de 4")
    else if stageName is "license" then
        statusLabel's setStringValue_("Comprobando la licencia…")
        stepLabel's setStringValue_("Paso 2 de 4")
    else if stageName is "download" or stageName is "configure" then
        statusLabel's setStringValue_("Preparando Admira IA…")
        stepLabel's setStringValue_("Paso 3 de 4")
    else if stageName is "container" then
        statusLabel's setStringValue_("Construyendo Admira IA…")
        stepLabel's setStringValue_("Paso 4 de 4")
    else if stageName is "complete" then
        statusLabel's setStringValue_("Instalación completada")
        dashboardButton's setHidden_(false)
        stepLabel's setStringValue_("Listo")
    else if stageName is "error" then
        statusLabel's setStringValue_("La instalación necesita atención")
    end if
end

on taskFinished_(notification)
    progressBar's stopAnimation_(me)
    progressBar's setIndeterminate_(false)
    set exitStatus to task's terminationStatus() as integer
    if exitStatus = 42 then
        set alertResult to my askTransfer()
        if alertResult then
            set transferRetry to true
            my launchEngine()
        else
            my resetFields()
        end if
    else if exitStatus = 0 then
        progressBar's setDoubleValue_(100)
        statusLabel's setStringValue_("Instalación completada")
        detailLabel's setStringValue_("El dashboard está listo y se abrirá en tu navegador. También hay un acceso directo en el Escritorio.")
        dashboardButton's setHidden_(false)
        stepLabel's setStringValue_("Listo")
    else
        my resetFields()
        my showAlert("La instalación necesita atención", "No se pudo completar. Pulsa «Ver registro» para consultar el diagnóstico.")
    end if
end

on askTransfer()
    set alertDialog to current application's NSAlert's alloc()'s init()
    alertDialog's setMessageText_("La licencia ya está vinculada a otro equipo")
    alertDialog's setInformativeText_("¿Quieres transferirla a este Mac? Esto desconectará la instalación anterior según las reglas de tu licencia.")
    alertDialog's addButtonWithTitle_("Transferir y continuar")
    alertDialog's addButtonWithTitle_("Cancelar")
    return (alertDialog's runModal() as integer) = (current application's NSAlertFirstButtonReturn as integer)
end

on resetFields()
    installButton's setEnabled_(true)
    emailField's setEnabled_(true)
    licenseField's setEnabled_(true)
end

on openDashboard_(sender)
    set portValue to "7871"
    try
        set portValue to do shell script "/bin/cat " & quoted form of ((POSIX path of (path to home folder)) & "Library/Application Support/Admira IA/Installer/port.txt")
    end try
    open location ("http://127.0.0.1:" & portValue & "/")
end

on openLogs_(sender)
    set logPath to (POSIX path of (path to home folder)) & "Library/Application Support/Admira IA/Installer/install.log"
    do shell script "/bin/mkdir -p " & quoted form of ((POSIX path of (path to home folder)) & "Library/Application Support/Admira IA/Installer") & "; /usr/bin/touch " & quoted form of logPath
    tell application "Finder" to open POSIX file logPath
end

on showAlert(alertTitle, alertMessage)
    set alertDialog to current application's NSAlert's alloc()'s init()
    alertDialog's setMessageText_(alertTitle)
    alertDialog's setInformativeText_(alertMessage)
    alertDialog's addButtonWithTitle_("OK")
    alertDialog's runModal()
end

on trimText(theText)
    set whitespaceSet to {space, tab, return, linefeed}
    repeat while theText begins with space or theText begins with tab or theText begins with return or theText begins with linefeed
        set theText to text 2 thru -1 of theText
    end repeat
    repeat while theText ends with space or theText ends with tab or theText ends with return or theText ends with linefeed
        set theText to text 1 thru -2 of theText
    end repeat
    return theText
end

on lowerText(theText)
    return (current application's NSString's stringWithString_(theText))'s lowercaseString() as text
end

on upperText(theText)
    return (current application's NSString's stringWithString_(theText))'s uppercaseString() as text
end
