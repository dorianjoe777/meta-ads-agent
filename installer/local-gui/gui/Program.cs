using System.Diagnostics;
using System.Drawing.Drawing2D;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Windows.Forms;

namespace AdmiraIA.Installer.Gui;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        Application.Run(new InstallerForm(args));
    }
}

internal sealed class InstallerForm : Form
{
    private const string InstallerBuild = "1.0.8";
    private readonly string _stateRoot = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "AdmiraIA", "SelfService");
    private readonly string _localRoot = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "AdmiraIA", "Installer");
    private readonly bool _resume;
    private string _credentialPath = string.Empty;
    private string _guiPath = string.Empty;
    private string _scriptPath = string.Empty;
    private Process? _engine;
    private readonly System.Windows.Forms.Timer _pollTimer;
    private DateTime _runStartedAtUtc = DateTime.MinValue;
    private bool _restartDialogShown;
    private bool _finished;
    private DateTime _engineLaunchStartedAtUtc = DateTime.MinValue;
    private bool _engineStartDiagnosticShown;

    private readonly TextBox _email = new();
    private readonly TextBox _license = new();
    private readonly Button _start = new();
    private readonly ProgressBar _progress = new();
    private readonly Label _stage = new();
    private readonly Label _detail = new();
    private readonly Label _title = new();
    private readonly Label _subtitle = new();
    private readonly Panel _formPanel = new();
    private readonly Panel _progressPanel = new();

    public InstallerForm(string[] args)
    {
        _resume = args.Any(a => a.Equals("-Resume", StringComparison.OrdinalIgnoreCase));
        _credentialPath = ValueAfter(args, "-CredentialFile") ?? Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "AdmiraIA", "SelfService", "license-input.xml");
        _guiPath = ValueAfter(args, "-GuiPath") ?? Path.Combine(_localRoot, "AdmiraIA-Installer.exe");

        Text = $"Admira IA · Instalación v{InstallerBuild}";
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(760, 510);
        MinimumSize = new Size(720, 470);
        BackColor = Color.FromArgb(10, 18, 32);
        ForeColor = Color.White;
        Font = new Font("Segoe UI", 10F, FontStyle.Regular, GraphicsUnit.Point);
        FormBorderStyle = FormBorderStyle.FixedSingle;
        MaximizeBox = false;
        Icon = SystemIcons.Application;

        BuildUi();
        _pollTimer = new System.Windows.Forms.Timer { Interval = 500 };
        _pollTimer.Tick += (_, _) => PollStatus();
        Shown += async (_, _) => await OnShownAsync();
        FormClosing += (_, _) =>
        {
            _pollTimer.Stop();
            if (!_finished && _engine is { HasExited: false })
            {
                try { _engine.Kill(entireProcessTree: true); } catch { }
            }
            _engine?.Dispose();
        };
    }

    private static string? ValueAfter(string[] args, string name)
    {
        for (var i = 0; i < args.Length - 1; i++)
            if (args[i].Equals(name, StringComparison.OrdinalIgnoreCase)) return args[i + 1];
        return null;
    }

    private void BuildUi()
    {
        var accent = Color.FromArgb(74, 224, 191);
        var muted = Color.FromArgb(157, 174, 198);
        var surface = Color.FromArgb(19, 31, 52);
        var line = Color.FromArgb(42, 62, 88);

        var top = new Panel { Dock = DockStyle.Top, Height = 8, BackColor = accent };
        Controls.Add(top);

        _title.Text = "ADMIRA IA";
        _title.Font = new Font("Segoe UI Semibold", 25F, FontStyle.Bold);
        _title.ForeColor = Color.White;
        _title.AutoSize = true;
        _title.Location = new Point(42, 36);
        Controls.Add(_title);

        _subtitle.Text = $"Tu espacio de trabajo, listo en unos minutos.  ·  v{InstallerBuild}";
        _subtitle.Font = new Font("Segoe UI", 11F);
        _subtitle.ForeColor = muted;
        _subtitle.AutoSize = true;
        _subtitle.Location = new Point(45, 82);
        Controls.Add(_subtitle);

        _formPanel.Location = new Point(42, 132);
        _formPanel.Size = new Size(676, 285);
        _formPanel.BackColor = surface;
        _formPanel.Padding = new Padding(28);
        Controls.Add(_formPanel);

        var emailLabel = FieldLabel("Correo de compra", muted);
        emailLabel.Location = new Point(28, 24);
        _formPanel.Controls.Add(emailLabel);
        StyleTextBox(_email, "correo@ejemplo.com", line);
        _email.Location = new Point(28, 52);
        _email.Width = 610;
        _formPanel.Controls.Add(_email);

        var licenseLabel = FieldLabel("Licencia de Admira IA", muted);
        licenseLabel.Location = new Point(28, 104);
        _formPanel.Controls.Add(licenseLabel);
        StyleTextBox(_license, "MAO-...", line);
        _license.UseSystemPasswordChar = true;
        _license.Location = new Point(28, 132);
        _license.Width = 610;
        _formPanel.Controls.Add(_license);

        _start.Text = "Comenzar instalación";
        _start.FlatStyle = FlatStyle.Flat;
        _start.FlatAppearance.BorderSize = 0;
        _start.BackColor = accent;
        _start.ForeColor = Color.FromArgb(6, 25, 31);
        _start.Font = new Font("Segoe UI Semibold", 10.5F, FontStyle.Bold);
        _start.Cursor = Cursors.Hand;
        _start.Size = new Size(205, 42);
        _start.Location = new Point(28, 197);
        _start.Click += async (_, _) => await BeginAsync();
        _formPanel.Controls.Add(_start);

        var note = new Label
        {
            Text = "La licencia se protege localmente y se elimina al completar el proceso.",
            AutoSize = true,
            ForeColor = muted,
            Font = new Font("Segoe UI", 8.5F),
            Location = new Point(254, 211)
        };
        _formPanel.Controls.Add(note);

        _progressPanel.Location = _formPanel.Location;
        _progressPanel.Size = _formPanel.Size;
        _progressPanel.BackColor = surface;
        _progressPanel.Padding = new Padding(28);
        _progressPanel.Visible = false;
        Controls.Add(_progressPanel);

        _stage.Text = "Preparando…";
        _stage.Font = new Font("Segoe UI Semibold", 15F, FontStyle.Bold);
        _stage.AutoSize = true;
        _stage.Location = new Point(28, 30);
        _progressPanel.Controls.Add(_stage);
        _detail.Text = "Puedes seguir trabajando; esta ventana te avisará si hace falta reiniciar.";
        _detail.ForeColor = muted;
        _detail.AutoSize = true;
        _detail.Location = new Point(28, 70);
        _progressPanel.Controls.Add(_detail);
        _progress.Location = new Point(28, 125);
        _progress.Size = new Size(610, 14);
        _progress.Style = ProgressBarStyle.Continuous;
        _progress.ForeColor = accent;
        _progress.BackColor = Color.FromArgb(35, 50, 72);
        _progressPanel.Controls.Add(_progress);
    }

    private static Label FieldLabel(string text, Color color) => new()
    {
        Text = text,
        AutoSize = true,
        ForeColor = color,
        Font = new Font("Segoe UI Semibold", 9.5F, FontStyle.Bold)
    };

    private static void StyleTextBox(TextBox box, string placeholder, Color border)
    {
        box.BorderStyle = BorderStyle.FixedSingle;
        box.BackColor = Color.FromArgb(12, 22, 38);
        box.ForeColor = Color.White;
        box.Font = new Font("Segoe UI", 11F);
        box.Height = 34;
        box.PlaceholderText = placeholder;
    }

    private async Task OnShownAsync()
    {
        try
        {
            PreparePayload();
            if (_resume)
            {
                _formPanel.Visible = false;
                _progressPanel.Visible = true;
                _title.Text = "ADMIRA IA · Continuando";
                await LaunchEngineAsync();
            }
        }
        catch (Exception ex)
        {
            ShowFailure("No se pudo iniciar el instalador", ex.Message);
        }
    }

    private void PreparePayload()
    {
        Directory.CreateDirectory(_localRoot);
        var payload = Path.Combine(AppContext.BaseDirectory, "payload");
        var persistentPayload = Path.Combine(_localRoot, "payload");
        var sourceScript = Path.Combine(payload, "01-Preparar-PC-Admira-IA.ps1");
        var sourceHelper = Path.Combine(payload, "02-Instalar-Admira-IA.ps1");
        if (!File.Exists(sourceScript))
        {
            payload = persistentPayload;
            sourceScript = Path.Combine(payload, "01-Preparar-PC-Admira-IA.ps1");
            sourceHelper = Path.Combine(payload, "02-Instalar-Admira-IA.ps1");
        }
        if (!File.Exists(sourceScript) || !File.Exists(sourceHelper))
            throw new FileNotFoundException("Faltan los componentes internos del instalador.");
        Directory.CreateDirectory(persistentPayload);
        var targetScript = Path.Combine(persistentPayload, "01-Preparar-PC-Admira-IA.ps1");
        var targetHelper = Path.Combine(persistentPayload, "02-Instalar-Admira-IA.ps1");
        if (!Path.GetFullPath(sourceScript).Equals(Path.GetFullPath(targetScript), StringComparison.OrdinalIgnoreCase))
            File.Copy(sourceScript, targetScript, true);
        if (!Path.GetFullPath(sourceHelper).Equals(Path.GetFullPath(targetHelper), StringComparison.OrdinalIgnoreCase))
            File.Copy(sourceHelper, targetHelper, true);
        _scriptPath = Path.Combine(_localRoot, "01-Preparar-PC-Admira-IA.ps1");
        File.Copy(sourceScript, _scriptPath, true);
        File.Copy(sourceHelper, Path.Combine(_localRoot, "02-Instalar-Admira-IA.ps1"), true);
        var currentExe = Environment.ProcessPath;
        if (!string.IsNullOrWhiteSpace(currentExe) && !Path.GetFullPath(currentExe).Equals(Path.GetFullPath(_guiPath), StringComparison.OrdinalIgnoreCase))
        {
            try { File.Copy(currentExe, _guiPath, true); } catch { _guiPath = currentExe; }
        }
    }

    private async Task BeginAsync()
    {
        if (string.IsNullOrWhiteSpace(_email.Text) || !Regex.IsMatch(_email.Text.Trim(), @"^[^@\s]+@[^@\s]+\.[^@\s]+$"))
        {
            MessageBox.Show(this, "Escribe un correo válido.", "Revisa los datos", MessageBoxButtons.OK, MessageBoxIcon.Information);
            _email.Focus();
            return;
        }
        if (string.IsNullOrWhiteSpace(_license.Text))
        {
            MessageBox.Show(this, "Pega la licencia para continuar.", "Revisa los datos", MessageBoxButtons.OK, MessageBoxIcon.Information);
            _license.Focus();
            return;
        }
        _start.Enabled = false;
        _email.Enabled = false;
        _license.Enabled = false;
        _formPanel.Visible = false;
        _progressPanel.Visible = true;
        try
        {
            await SaveCredentialAsync(_email.Text.Trim().ToLowerInvariant(), _license.Text.Trim());
            _license.Clear();
            await LaunchEngineAsync();
        }
        catch (Exception ex)
        {
            ShowFailure("No se pudo iniciar la instalación", ex.Message);
        }
    }

    private async Task SaveCredentialAsync(string email, string license)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(_credentialPath)!);
        var payload = JsonSerializer.Serialize(new { email, license });
        var path64 = Convert.ToBase64String(Encoding.UTF8.GetBytes(_credentialPath));
        var script = @"
$json = [Console]::In.ReadToEnd() | ConvertFrom-Json
$path = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('PATH_B64'))
$secure = ConvertTo-SecureString ([string]$json.license) -AsPlainText -Force
$credential = New-Object -TypeName System.Management.Automation.PSCredential -ArgumentList ([string]$json.email), $secure
$credential | Export-Clixml -LiteralPath $path -Force
".Replace("PATH_B64", path64);
        var encoded = Convert.ToBase64String(Encoding.Unicode.GetBytes(script));
        var psi = HiddenPowerShell($"-NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand {encoded}");
        using var process = new Process { StartInfo = psi };
        process.Start();
        await process.StandardInput.WriteAsync(payload);
        process.StandardInput.Close();
        await process.WaitForExitAsync();
        if (process.ExitCode != 0) throw new InvalidOperationException("Windows no pudo proteger los datos de la licencia.");
    }

    private async Task LaunchEngineAsync()
    {
        if (!File.Exists(_scriptPath)) PreparePayload();
        if (!_resume)
        {
            // A previous successful install leaves a complete state file behind.
            // Remove only the transient status files before a new run so the GUI
            // cannot mistake the old result for the current installation.
            TryDelete(Path.Combine(_stateRoot, "prepare-state.json"));
            TryDelete(Path.Combine(_stateRoot, "install-result.json"));
        }
        _runStartedAtUtc = DateTime.UtcNow;
        _engineLaunchStartedAtUtc = DateTime.UtcNow;
        _engineStartDiagnosticShown = false;
        var args = $"-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File {Quote(_scriptPath)} -CredentialFile {Quote(_credentialPath)} -Gui -GuiPath {Quote(_guiPath)}";
        // Ask for elevation at the GUI boundary so Windows shows a normal UAC
        // prompt. The previous design launched a hidden non-admin PowerShell,
        // which then requested UAC behind the window and could leave the bar at
        // zero with no state or log when the prompt was dismissed.
        var psi = new ProcessStartInfo
        {
            FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe"),
            Arguments = args,
            UseShellExecute = true,
            Verb = "runas",
            WindowStyle = ProcessWindowStyle.Hidden,
            WorkingDirectory = Path.GetDirectoryName(_scriptPath) ?? AppContext.BaseDirectory
        };
        try
        {
            _engine = new Process { StartInfo = psi, EnableRaisingEvents = true };
            _engine.Exited += (_, _) => BeginInvoke(new Action(() =>
            {
                if (_finished || _engineStartDiagnosticShown) return;
                var state = ReadJson(Path.Combine(_stateRoot, "prepare-state.json"));
                if (state is null)
                {
                    var exitCode = _engine?.ExitCode.ToString() ?? "desconocido";
                    var bootstrapPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "AdmiraIA", "SelfService", "bootstrap.log");
                    var bootstrap = File.Exists(bootstrapPath) ? File.ReadAllText(bootstrapPath).Trim() : "No se creó bootstrap.log.";
                    if (bootstrap.Length > 900) bootstrap = bootstrap[^900..];
                    ShowFailure("El motor no inició", $"Windows cerró el proceso antes de crear su estado (código {exitCode}).\n\n{bootstrap}");
                }
            }));
            if (!_engine.Start()) throw new InvalidOperationException("Windows no pudo iniciar el proceso elevado.");
        }
        catch (System.ComponentModel.Win32Exception ex) when (ex.NativeErrorCode == 1223)
        {
            ShowFailure("Permisos cancelados", "La instalación necesita permisos de administrador. Acepta la ventana de Control de cuentas de usuario para continuar.");
            return;
        }
        catch (Exception ex)
        {
            ShowFailure("No se pudo iniciar la instalación", ex.Message);
            return;
        }
        _pollTimer.Start();
        await Task.CompletedTask;
    }

    private static ProcessStartInfo HiddenPowerShell(string arguments) => new()
    {
        FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe"),
        Arguments = arguments,
        UseShellExecute = false,
        CreateNoWindow = true,
        WindowStyle = ProcessWindowStyle.Hidden,
        RedirectStandardInput = true,
        RedirectStandardOutput = true,
        RedirectStandardError = true
    };

    private static string Quote(string value) => "\"" + value.Replace("\"", "\\\"") + "\"";

    private void PollStatus()
    {
        var statePath = Path.Combine(_stateRoot, "prepare-state.json");
        if (!_resume && File.Exists(statePath) && File.GetLastWriteTimeUtc(statePath) < _runStartedAtUtc.AddSeconds(-1)) return;
        var state = ReadJson(statePath);
        if (state is null)
        {
            if (!_engineStartDiagnosticShown && _engineLaunchStartedAtUtc != DateTime.MinValue && DateTime.UtcNow - _engineLaunchStartedAtUtc > TimeSpan.FromSeconds(90))
            {
                ShowFailure("El instalador no inició", "No se recibió el estado de PowerShell después de 90 segundos. Acepta la ventana de permisos de Windows y vuelve a ejecutar el instalador.");
            }
            return;
        }
        var status = GetString(state, "status");
        var stage = GetString(state, "stage");
        var code = GetString(state, "code");
        UpdateProgress(stage, status);

        if (status.Equals("waiting_for_restart", StringComparison.OrdinalIgnoreCase) && !_restartDialogShown)
        {
            _restartDialogShown = true;
            _pollTimer.Stop();
            var answer = MessageBox.Show(this,
                "Windows debe reiniciarse para terminar la instalación. ¿Quieres reiniciar ahora?\n\nSi eliges No, Admira IA continuará automáticamente cuando vuelvas a iniciar sesión.",
                "Reinicio necesario", MessageBoxButtons.YesNo, MessageBoxIcon.Information);
            if (answer == DialogResult.Yes)
            {
                Process.Start(new ProcessStartInfo("shutdown.exe", "/r /t 0") { UseShellExecute = false, CreateNoWindow = true });
            }
            else
            {
                _stage.Text = "Pausa segura";
                _detail.Text = "La instalación continuará automáticamente después del próximo inicio de sesión.";
                _finished = true;
            }
            return;
        }

        if (status.Equals("error", StringComparison.OrdinalIgnoreCase) || status.Equals("blocked", StringComparison.OrdinalIgnoreCase))
        {
            _pollTimer.Stop();
            var detail = GetString(state, "message");
            var result = ReadJson(Path.Combine(_stateRoot, "install-result.json"));
            var resultMessage = result is null ? string.Empty : GetString(result, "message");
            if (resultMessage.Length > 0 && (detail.Length == 0 || detail.Contains("código 99", StringComparison.OrdinalIgnoreCase))) detail = resultMessage;
            ShowFailure(code.Length == 0 ? "La instalación se detuvo" : code, detail);
            return;
        }

        if (status.Equals("complete", StringComparison.OrdinalIgnoreCase) && !_finished)
        {
            _finished = true;
            _pollTimer.Stop();
            _progress.Value = 100;
            _stage.Text = "Instalación completada";
            _detail.Text = "Admira IA está lista. Abriendo el dashboard…";
            var result = ReadJson(Path.Combine(_stateRoot, "install-result.json"));
            var url = result is null ? "http://localhost:7871" : GetString(result, "dashboard_url");
            if (Uri.TryCreate(url, UriKind.Absolute, out var uri)) Process.Start(new ProcessStartInfo(uri.ToString()) { UseShellExecute = true });
            MessageBox.Show(this, "Admira IA quedó instalada y se iniciará automáticamente con Windows.", "Todo listo", MessageBoxButtons.OK, MessageBoxIcon.Information);
            Close();
        }
    }

    private void UpdateProgress(string stage, string status)
    {
        var (value, text) = stage.ToLowerInvariant() switch
        {
            "preflight" => (8, "Comprobando compatibilidad del equipo…"),
            "windows_features" => (20, "Habilitando componentes de Windows…"),
            "wsl_update" => (38, "Instalando o actualizando WSL2…"),
            "docker_desktop" => (62, "Instalando y arrancando Docker Desktop…"),
            "installing_admira" => (68, "Preparando la instalación de Admira IA…"),
            "license_release" => (72, "Validando la licencia y preparando la descarga…"),
            "download_release" => (78, "Descargando y verificando Admira IA…"),
            "build_container" => (86, "Construyendo el contenedor de Admira IA…"),
            "health_check" => (94, "Comprobando que el dashboard responde…"),
            "autostart" => (97, "Configurando el arranque automático…"),
            "complete" => (100, "Instalación completada"),
            _ => (_progress.Value, "Trabajando…")
        };
        _progress.Value = Math.Clamp(value, 0, 100);
        _stage.Text = text;
        _detail.Text = status.Equals("running", StringComparison.OrdinalIgnoreCase)
            ? "No cierres esta ventana. Algunas etapas pueden tardar varios minutos."
            : "Puedes seguir trabajando; te avisaremos si se necesita reiniciar.";
    }

    private static Dictionary<string, JsonElement>? ReadJson(string path)
    {
        try
        {
            if (!File.Exists(path)) return null;
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            return doc.RootElement.EnumerateObject().ToDictionary(p => p.Name, p => p.Value.Clone(), StringComparer.OrdinalIgnoreCase);
        }
        catch { return null; }
    }

    private static void TryDelete(string path)
    {
        try { if (File.Exists(path)) File.Delete(path); } catch { }
    }

    private static string GetString(Dictionary<string, JsonElement> values, string name) =>
        values.TryGetValue(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() ?? string.Empty : string.Empty;

    private void ShowFailure(string title, string detail)
    {
        if (_engineStartDiagnosticShown) return;
        _engineStartDiagnosticShown = true;
        _pollTimer.Stop();
        _stage.Text = "La instalación necesita atención";
        _detail.Text = detail.Length > 160 ? detail[..160] + "…" : detail;
        MessageBox.Show(this, detail, title, MessageBoxButtons.OK, MessageBoxIcon.Warning);
    }
}
