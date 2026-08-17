use framework "Cocoa"
use scripting additions

property parent : class "NSObject"
property buildVersion : "dev"
property installerWindow : missing value
property emailField : missing value
property licenseField : missing value
property tokenField : missing value
property sizePopup : missing value
property regionPopup : missing value
property emailCaption : missing value
property licenseCaption : missing value
property tokenCaption : missing value
property sizeCaption : missing value
property regionCaption : missing value
property installButton : missing value
property progressBar : missing value
property statusLabel : missing value
property detailLabel : missing value
property stepLabel : missing value
property dashboardButton : missing value
property logButton : missing value
property task : missing value
property taskTimer : missing value
property emailValue : ""
property licenseValue : ""
property tokenValue : ""
property sizeValue : "s-1vcpu-1gb"
property regionValue : "nyc3"
property transferRetry : false
property resumeMode : false
property resumeStarted : false
property frontTicks : 0
property stateRoot : ""
property mutedColor : missing value

on run
    try
        set stateRoot to (POSIX path of (path to home folder)) & "Library/Application Support/Admira IA/Cloud Installer"
        set resumeMode to my pendingInstallation()
        current application's NSApp's setActivationPolicy_(current application's NSApplicationActivationPolicyRegular)
        current application's NSApp's activateIgnoringOtherApps_(true)
        my buildInterface()
        current application's NSApp's activateIgnoringOtherApps_(true)
        set runningApp to current application's NSRunningApplication's currentApplication()
        runningApp's activateWithOptions_(current application's NSApplicationActivateIgnoringOtherApps)
        current application's NSApp's |run|()
    on error errorMessage number errorNumber
        do shell script "/usr/bin/printf '%s\\n' " & quoted form of (errorMessage & " (" & errorNumber & ")") & " >> /tmp/admira-cloud-installer-window.log"
    end try
end run

on idle
    if installerWindow is not missing value and frontTicks < 10 then
        installerWindow's orderFrontRegardless()
        set runningApp to current application's NSRunningApplication's currentApplication()
        runningApp's activateWithOptions_(current application's NSApplicationActivateIgnoringOtherApps)
        set frontTicks to frontTicks + 1
    end if
    if resumeMode and not resumeStarted and frontTicks ≥ 3 then
        set resumeStarted to true
        my startResume()
    end if
    return 1
end idle

on pendingInstallation()
    try
        do shell script "/usr/bin/find " & quoted form of (stateRoot & "/jobs") & " -type f -name '*.state' -exec /usr/bin/grep -q '^phase=running$' {} \\; -print -quit | /usr/bin/grep -q ."
        return true
    on error
        return false
    end try
end pendingInstallation

on buildInterface()
    set aquaColor to current application's NSColor's colorWithCalibratedRed_green_blue_alpha_(0.27, 0.85, 0.74, 1.0)
    set mutedColor to current application's NSColor's colorWithCalibratedRed_green_blue_alpha_(0.67, 0.74, 0.84, 1.0)
    set panelColor to current application's NSColor's colorWithCalibratedRed_green_blue_alpha_(0.075, 0.12, 0.22, 1.0)
    set bgColor to current application's NSColor's colorWithCalibratedRed_green_blue_alpha_(0.035, 0.065, 0.13, 1.0)
    set frameRect to current application's NSMakeRect(0, 0, 760, 680)
    set styleMask to 15
    set installerWindow to current application's NSWindow's alloc()'s initWithContentRect_styleMask_backing_defer_(frameRect, styleMask, current application's NSBackingStoreBuffered, false)
    installerWindow's setTitle_("Admira IA · Instalación en la nube")
    installerWindow's setBackgroundColor_(bgColor)
    installerWindow's setHasShadow_(true)
    installerWindow's setFrameOrigin_(current application's NSMakePoint(110, 150))
    set contentView to installerWindow's contentView()
    contentView's setWantsLayer_(true)

    my addLabel("ADMIRA IA", 27, true, {48, 612, 420, 42}, contentView, {"header"})
    my addLabel("Tu espacio de trabajo, listo en unos minutos.", 14, false, {50, 582, 480, 24}, contentView, {"subtitle"})
    my addLabel("CLOUD INSTALLER · macOS", 11, true, {560, 620, 165, 20}, contentView, {"version"})
    my addLabel("DIGITALOCEAN", 11, true, {50, 548, 160, 20}, contentView, {"provider"})

    set panel to current application's NSView's alloc()'s initWithFrame_(current application's NSMakeRect(38, 72, 684, 458))
    panel's setWantsLayer_(true)
    panel's layer()'s setCornerRadius_(14.0)
    contentView's addSubview_(panel)

    set emailCaption to my addLabel("Correo usado para comprar Admira IA", 12, true, {30, 410, 400, 20}, panel, {})
    set emailField to my addTextField("correo@ejemplo.com", false, {30, 372, 624, 34}, panel)
    set licenseCaption to my addLabel("Licencia de Admira IA", 12, true, {30, 334, 400, 20}, panel, {})
    set licenseField to my addTextField("MAO-…", true, {30, 296, 624, 34}, panel)
    set tokenCaption to my addLabel("Token personal de DigitalOcean", 12, true, {30, 258, 400, 20}, panel, {})
    set tokenField to my addTextField("dop_v1_…", true, {30, 220, 624, 34}, panel)

    set sizeCaption to my addLabel("Tamaño del Droplet", 12, true, {30, 182, 280, 20}, panel, {})
    set sizePopup to current application's NSPopUpButton's alloc()'s initWithFrame_(current application's NSMakeRect(30, 145, 298, 30))
    sizePopup's addItemsWithTitles_({"1 GB · swap de 2 GB", "2 GB · recomendado", "4 GB · rápido"})
    sizePopup's selectItemAtIndex_(1)
    sizePopup's setFont_(current application's NSFont's systemFontOfSize_(13))
    panel's addSubview_(sizePopup)

    set regionCaption to my addLabel("Región del servidor", 12, true, {356, 182, 280, 20}, panel, {})
    set regionPopup to current application's NSPopUpButton's alloc()'s initWithFrame_(current application's NSMakeRect(356, 145, 298, 30))
    regionPopup's addItemsWithTitles_({"New York · NYC3", "San Francisco · SFO3", "Amsterdam · AMS3", "Frankfurt · FRA1", "Singapore · SGP1"})
    regionPopup's selectItemAtIndex_(0)
    regionPopup's setFont_(current application's NSFont's systemFontOfSize_(13))
    panel's addSubview_(regionPopup)

    set installButton to current application's NSButton's alloc()'s initWithFrame_(current application's NSMakeRect(30, 88, 624, 42))
    installButton's setTitle_("Crear mi instalación en la nube")
    installButton's setBezelStyle_(current application's NSBezelStyleRounded)
    -- Keep this a real momentary push button.  The default style can render
    -- correctly while swallowing mouse activation when an AppleScriptObjC
    -- applet is launched by the native DMG wrapper.
    installButton's setButtonType_(current application's NSButtonTypeMomentaryPushIn)
    installButton's setEnabled_(true)
    installButton's setKeyEquivalent_(return)
    installButton's setFont_(current application's NSFont's systemFontOfSize_weight_(15, current application's NSFontWeightSemibold))
    installButton's setContentTintColor_(current application's NSColor's colorWithCalibratedRed_green_blue_alpha_(0.02, 0.10, 0.13, 1.0))
    installButton's setTarget_(me)
    installButton's setAction_("beginInstallation:")
    -- Do not put a custom layer on the control: on some macOS/AppKit
    -- versions a layer-backed NSButton paints normally but misses hit tests.
    installButton's setWantsLayer_(false)
    set installCell to installButton's cell()
    installCell's setTarget_(me)
    installCell's setAction_("beginInstallation:")
    -- Keep the primary control on the window content view itself. This avoids
    -- hit-test differences seen with layer-backed container views on macOS.
    set buttonFrame to current application's NSMakeRect(68, 160, 624, 42)
    installButton's setFrame_(buttonFrame)
    contentView's addSubview_(installButton)

    set statusLabel to my addLabel("Listo para comenzar", 16, true, {30, 50, 480, 24}, panel, {})
    set stepLabel to my addLabel("Paso 1 de 7", 12, false, {550, 51, 104, 20}, panel, {})
    stepLabel's setAlignment_(current application's NSTextAlignmentRight)
    set detailLabel to my addLabel("Se generará una clave SSH local, se creará tu servidor y el dashboard se abrirá en el navegador.", 12, false, {30, 22, 624, 28}, panel, {})
    detailLabel's setMaximumNumberOfLines_(2)
    set progressBar to current application's NSProgressIndicator's alloc()'s initWithFrame_(current application's NSMakeRect(30, 6, 624, 10))
    progressBar's setIndeterminate_(false)
    progressBar's setMinValue_(0)
    progressBar's setMaxValue_(100)
    progressBar's setDoubleValue_(0)
    progressBar's setStyle_(current application's NSProgressIndicatorBarStyle)
    panel's addSubview_(progressBar)

    set dashboardButton to current application's NSButton's alloc()'s initWithFrame_(current application's NSMakeRect(520, 42, 134, 28))
    dashboardButton's setTitle_("Abrir dashboard")
    dashboardButton's setBezelStyle_(current application's NSBezelStyleRounded)
    dashboardButton's setTarget_(me)
    dashboardButton's setAction_("openDashboard:")
    dashboardButton's setHidden_(true)
    panel's addSubview_(dashboardButton)

    set logButton to current application's NSButton's alloc()'s initWithFrame_(current application's NSMakeRect(50, 36, 110, 24))
    logButton's setTitle_("Ver registro")
    logButton's setBezelStyle_(current application's NSBezelStyleInline)
    logButton's setContentTintColor_(mutedColor)
    logButton's setTarget_(me)
    logButton's setAction_("openLogs:")
    contentView's addSubview_(logButton)
    my addLabel("La clave SSH se queda en este Mac. El token de DigitalOcean se elimina al terminar.", 11, false, {200, 38, 510, 20}, contentView, {})
    my addLabel("Admira IA se ejecuta en Docker dentro de tu Droplet; el acceso final es un enlace del navegador.", 11, false, {50, 12, 660, 20}, contentView, {})

    if resumeMode then
        emailCaption's setHidden_(true)
        emailField's setHidden_(true)
        licenseCaption's setHidden_(true)
        licenseField's setHidden_(true)
        tokenCaption's setHidden_(true)
        tokenField's setHidden_(true)
        sizeCaption's setHidden_(true)
        sizePopup's setHidden_(true)
        regionCaption's setHidden_(true)
        regionPopup's setHidden_(true)
        installButton's setTitle_("Continuar instalación")
        statusLabel's setStringValue_("Continuando instalación anterior…")
        detailLabel's setStringValue_("Retomaremos el servidor sin crear un Droplet duplicado. Puedes dejar esta ventana abierta.")
        stepLabel's setStringValue_("Reanudando")
    end if

    installerWindow's setLevel_(current application's NSFloatingWindowLevel)
    installerWindow's makeKeyAndOrderFront_(missing value)
    installerWindow's orderFrontRegardless()
end buildInterface

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
    parentView's addSubview_(label)
    return label
end addLabel

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
end addTextField

on beginInstallation_(sender)
    if resumeMode then
        my startResume()
        return
    end if
    set emailValue to my trimText((emailField's stringValue()) as text)
    set licenseValue to my upperText(my trimText((licenseField's stringValue()) as text))
    set tokenValue to my trimText((tokenField's stringValue()) as text)
    set emailValue to my lowerText(emailValue)
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
    if tokenValue is "" then
        my showAlert("Token requerido", "Pega tu token personal de DigitalOcean para crear el Droplet.")
        return
    end if
    set selectedSize to (sizePopup's titleOfSelectedItem()) as text
    if selectedSize starts with "1 GB" then
        set sizeValue to "s-1vcpu-1gb"
    else if selectedSize starts with "2 GB" then
        set sizeValue to "s-1vcpu-2gb"
    else
        set sizeValue to "s-2vcpu-4gb"
    end if
    set selectedRegion to (regionPopup's titleOfSelectedItem()) as text
    if selectedRegion contains "SFO3" then
        set regionValue to "sfo3"
    else if selectedRegion contains "AMS3" then
        set regionValue to "ams3"
    else if selectedRegion contains "FRA1" then
        set regionValue to "fra1"
    else if selectedRegion contains "SGP1" then
        set regionValue to "sgp1"
    else
        set regionValue to "nyc3"
    end if
    installButton's setEnabled_(false)
    emailField's setEnabled_(false)
    licenseField's setEnabled_(false)
    tokenField's setEnabled_(false)
    sizePopup's setEnabled_(false)
    regionPopup's setEnabled_(false)
    statusLabel's setStringValue_("Preparando la instalación…")
    detailLabel's setStringValue_("No cierres esta ventana. La creación del Droplet puede tardar varios minutos.")
    progressBar's setDoubleValue_(2)
    my launchEngine(false)
end beginInstallation_

on startResume()
    installButton's setEnabled_(false)
    progressBar's setIndeterminate_(true)
    progressBar's startAnimation_(me)
    my launchEngine(true)
end startResume

on launchEngine(isResume)
    set currentAppPath to POSIX path of (path to me)
    set installedPath to (POSIX path of (path to home folder)) & "Applications/Admira IA Cloud Installer.app"
    if currentAppPath does not start with installedPath then
        do shell script "/bin/mkdir -p " & quoted form of ((POSIX path of (path to home folder)) & "Applications") & "; /usr/bin/ditto " & quoted form of currentAppPath & " " & quoted form of installedPath
    end if
    set enginePath to installedPath & "/Contents/Resources/admira-mac-cloud-engine.sh"
    set task to current application's NSTask's alloc()'s init()
    task's setLaunchPath_("/bin/bash")
    if isResume then
        task's setArguments_({enginePath, "--resume"})
    else
        task's setArguments_({enginePath, "--gui"})
    end if
    set env to current application's NSMutableDictionary's dictionaryWithDictionary_(current application's NSProcessInfo's processInfo()'s environment())
    if not isResume then
        env's setObject_forKey_(emailValue, "ADMIRA_INSTALLER_EMAIL")
        env's setObject_forKey_(licenseValue, "ADMIRA_INSTALLER_LICENSE")
        env's setObject_forKey_(tokenValue, "ADMIRA_DO_TOKEN")
        env's setObject_forKey_(sizeValue, "ADMIRA_DO_SIZE")
        env's setObject_forKey_(regionValue, "ADMIRA_DO_REGION")
        if transferRetry then env's setObject_forKey_("true", "ADMIRA_TRANSFER_DEVICE")
    end if
    task's setEnvironment_(env)
    task's |launch|()
    -- Never wait synchronously here. The engine can take several minutes;
    -- keeping the wait loop on the AppKit thread made the window look frozen
    -- and prevented the log button from receiving clicks.
    set taskTimer to current application's NSTimer's scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(1.0, me, "pollTask:", missing value, true)
end launchEngine

on pollTask_(timer)
    my pollStatus(missing value)
    try
        if not (task's |isRunning|() as boolean) then
            timer's invalidate()
            set taskTimer to missing value
            my pollStatus(missing value)
            my taskFinished(missing value)
        end if
    on error
        timer's invalidate()
        set taskTimer to missing value
        my taskFinished(missing value)
    end try
end pollTask_

on pollStatus_(timer)
    set statusPath to stateRoot & "/status.txt"
    try
        set statusText to do shell script "/bin/cat " & quoted form of statusPath
        set rows to paragraphs of statusText
        if (count rows) ≥ 3 then my consumeStatus(item 1 of rows, item 2 of rows, item 3 of rows)
    end try
end pollStatus_

on consumeStatus(stageName, percentText, messageText)
    try
        progressBar's setDoubleValue_(percentText as real)
    end try
    detailLabel's setStringValue_(messageText)
    if stageName is "prepare" then
        statusLabel's setStringValue_("Preparando la instalación…")
        stepLabel's setStringValue_("Paso 1 de 7")
    else if stageName is "license" then
        statusLabel's setStringValue_("Comprobando la licencia…")
        stepLabel's setStringValue_("Paso 2 de 7")
    else if stageName is "download" then
        statusLabel's setStringValue_("Preparando el paquete…")
        stepLabel's setStringValue_("Paso 3 de 7")
    else if stageName is "do" then
        statusLabel's setStringValue_("Creando tu servidor…")
        stepLabel's setStringValue_("Paso 4 de 7")
    else if stageName is "ssh" or stageName is "firewall" then
        statusLabel's setStringValue_("Configurando acceso seguro…")
        stepLabel's setStringValue_("Paso 5 de 7")
    else if stageName is "transfer" then
        statusLabel's setStringValue_("Subiendo Admira IA…")
        stepLabel's setStringValue_("Paso 6 de 7")
    else if stageName is "container" then
        statusLabel's setStringValue_("Construyendo y arrancando Admira IA…")
        stepLabel's setStringValue_("Paso 7 de 7")
    else if stageName is "complete" then
        statusLabel's setStringValue_("Instalación completada")
        dashboardButton's setHidden_(false)
        stepLabel's setStringValue_("Listo")
    else if stageName is "error" then
        statusLabel's setStringValue_("La instalación necesita atención")
    end if
end consumeStatus

on taskFinished(notification)
    progressBar's stopAnimation_(me)
    progressBar's setIndeterminate_(false)
    set exitStatus to task's terminationStatus() as integer
    if exitStatus = 42 then
        set alertResult to my askTransfer()
        if alertResult then
            set transferRetry to true
            set resumeMode to false
            my launchEngine(false)
        else
            my resetFields()
        end if
    else if exitStatus = 0 then
        progressBar's setDoubleValue_(100)
        statusLabel's setStringValue_("Instalación completada")
        detailLabel's setStringValue_("El dashboard está listo. Se abrió en tu navegador y se creó un acceso directo en el Escritorio.")
        dashboardButton's setHidden_(false)
        stepLabel's setStringValue_("Listo")
    else
        my resetFields()
        my showAlert("La instalación necesita atención", "No se pudo completar. Pulsa «Ver registro» para consultar el diagnóstico.")
    end if
end taskFinished

on askTransfer()
    set alertDialog to current application's NSAlert's alloc()'s init()
    alertDialog's setMessageText_("La licencia ya está vinculada a otro equipo")
    alertDialog's setInformativeText_("¿Quieres transferirla a este Mac? Esto desconectará la instalación anterior según las reglas de tu licencia.")
    alertDialog's addButtonWithTitle_("Transferir y continuar")
    alertDialog's addButtonWithTitle_("Cancelar")
    return (alertDialog's runModal() as integer) = (current application's NSAlertFirstButtonReturn as integer)
end askTransfer

on resetFields()
    installButton's setEnabled_(true)
    emailField's setEnabled_(true)
    licenseField's setEnabled_(true)
    tokenField's setEnabled_(true)
    sizePopup's setEnabled_(true)
    regionPopup's setEnabled_(true)
end resetFields

on openDashboard_(sender)
    set urlPath to stateRoot & "/dashboard-url.txt"
    try
        set urlValue to do shell script "/bin/cat " & quoted form of urlPath
        open location urlValue
    on error
        my showAlert("Dashboard todavía no disponible", "La instalación aún no ha guardado su enlace.")
    end try
end openDashboard_

on openLogs_(sender)
    set logPath to stateRoot & "/install.log"
    do shell script "/bin/mkdir -p " & quoted form of stateRoot & "; /usr/bin/touch " & quoted form of logPath
    tell application "Finder" to open POSIX file logPath
end openLogs_

on showAlert(alertTitle, alertMessage)
    set alertDialog to current application's NSAlert's alloc()'s init()
    alertDialog's setMessageText_(alertTitle)
    alertDialog's setInformativeText_(alertMessage)
    alertDialog's addButtonWithTitle_("OK")
    alertDialog's runModal()
end showAlert

on trimText(theText)
    repeat while theText begins with space or theText begins with tab or theText begins with return or theText begins with linefeed
        set theText to text 2 thru -1 of theText
    end repeat
    repeat while theText ends with space or theText ends with tab or theText ends with return or theText ends with linefeed
        set theText to text 1 thru -2 of theText
    end repeat
    return theText
end trimText

on lowerText(theText)
    return (current application's NSString's stringWithString_(theText))'s lowercaseString() as text
end lowerText

on upperText(theText)
    return (current application's NSString's stringWithString_(theText))'s uppercaseString() as text
end upperText
