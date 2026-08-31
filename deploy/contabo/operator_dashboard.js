(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);
  const accounts = ["primary", "secondary"];
  const accountLabels = { primary: "Primaria", secondary: "Secundaria" };
  const allowedAuthHosts = new Set(["auth.openai.com", "openai.com", "chatgpt.com"]);
  const terminalPhases = new Set(["completed", "complete", "connected", "ready", "failed", "cancelled", "expired"]);
  const successfulPhases = new Set(["completed", "complete", "connected", "ready"]);
  const numberFormat = new Intl.NumberFormat("es-CO");
  const dateFormat = new Intl.DateTimeFormat("es-CO", { dateStyle: "medium", timeStyle: "short" });
  const state = {
    csrf: "",
    authenticated: false,
    gemini: null,
    codex: null,
    geminiError: false,
    codexError: false,
    geminiRequest: null,
    codexRequest: null,
    accountBusy: new Set(),
    device: null,
    confirmResolve: null,
    sessionVersion: 0,
  };

  function textElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    element.textContent = text;
    return element;
  }

  function messageFor(error, fallback) {
    const messages = {
      authentication_required: "La sesión caducó. Inicia sesión de nuevo.",
      csrf_required: "La sesión de seguridad cambió. Vuelve a iniciar sesión.",
      login_failed: "No se pudo iniciar sesión. Comprueba la contraseña o espera un momento antes de reintentar.",
      invalid_login: "No se pudo iniciar sesión. Comprueba la contraseña.",
      login_backoff: "Se han realizado varios intentos. Espera un momento e inténtalo de nuevo.",
      setup_unavailable: "No se pudo completar la configuración. Recarga la página para comprobar el estado de acceso.",
      invalid_setup_password: "La contraseña debe tener al menos 16 caracteres y coincidir con la confirmación.",
      rate_limited: "Se han realizado demasiadas operaciones. Espera unos segundos e inténtalo de nuevo.",
      invalid_capacity: "La capacidad debe ser un número entero entre 1 y 10.000.",
      invalid_project_ref: "Comprueba la referencia del proyecto.",
      invalid_gemini_key: "La clave Gemini no tiene un formato válido. Introdúcela de nuevo.",
      gemini_health_check_failed: "Gemini no validó la clave. Revisa sus permisos y vuelve a introducirla.",
      gemini_registration_failed: "La clave no pudo registrarse. Revisa el servicio de control e inténtalo de nuevo.",
      gemini_status_unavailable: "No se pudo consultar el inventario Gemini. Vuelve a intentarlo.",
      codex_cli_unavailable: "El servicio de autenticación Codex no está disponible. Revisa la instalación del servidor.",
      codex_login_in_progress: "Esta cuenta tiene una autenticación en curso. Cancélala antes de desconectar.",
      codex_disconnect_failed: "No se pudo desconectar la cuenta. Su estado no fue modificado.",
      login_job_not_found: "La autenticación ya no está disponible. Inicia una nueva conexión.",
      request_timeout: "El servidor tardó demasiado en responder. Consulta el estado antes de reintentar.",
      network_error: "No hay respuesta del servidor. Comprueba el túnel de acceso y vuelve a intentarlo.",
      invalid_response: "El servidor devolvió una respuesta no válida. Vuelve a intentarlo.",
      operator_unavailable: "El servicio de operaciones no está disponible. Comprueba su estado en el servidor e inténtalo de nuevo.",
    };
    if (error?.status === 429) return messages.rate_limited;
    return messages[error?.code] || fallback || "No se pudo completar la operación. Inténtalo de nuevo.";
  }

  function setNotice(message, kind = "info") {
    $("#notice").hidden = !message;
    $("#notice").dataset.kind = kind;
    $("#notice-text").textContent = message || "";
    if (kind === "error" && message) $("#assertive-status").textContent = message;
  }

  function setBusy(button, busy, label = "Procesando…") {
    if (!button) return;
    const labelElement = button.querySelector(".button-label") || button;
    if (busy) {
      if (!button.dataset.originalLabel) button.dataset.originalLabel = labelElement.textContent;
      labelElement.textContent = label;
    } else if (button.dataset.originalLabel) {
      labelElement.textContent = button.dataset.originalLabel;
      delete button.dataset.originalLabel;
    }
    button.disabled = busy;
    button.setAttribute("aria-busy", String(busy));
  }

  function setFormBusy(form, busy) {
    form.setAttribute("aria-busy", String(busy));
    form.querySelectorAll("input, .reveal-button").forEach((control) => {
      control.disabled = busy;
    });
  }

  function clearInvalid(form) {
    form.querySelectorAll("[aria-invalid]").forEach((input) => input.removeAttribute("aria-invalid"));
  }

  function invalidField(input, errorElement, message) {
    input.setAttribute("aria-invalid", "true");
    errorElement.textContent = message;
    input.focus();
  }

  function validateForm(form, errorElement) {
    clearInvalid(form);
    errorElement.textContent = "";
    const invalid = Array.from(form.querySelectorAll("input")).find((input) => !input.validity.valid);
    if (!invalid) return true;
    let message = "Completa los campos obligatorios.";
    if (invalid.validity.rangeUnderflow || invalid.validity.rangeOverflow || invalid.validity.stepMismatch) {
      message = "La capacidad debe ser un número entero entre 1 y 10.000.";
    } else if (invalid.validity.tooShort) {
      message = "Usa una contraseña de al menos 16 caracteres.";
    }
    invalidField(invalid, errorElement, message);
    return false;
  }

  function resetSecret(input) {
    input.value = "";
    input.type = "password";
    const toggle = document.querySelector('[data-password-toggle="' + input.id + '"]');
    if (toggle) {
      toggle.textContent = "Mostrar";
      toggle.setAttribute("aria-pressed", "false");
      toggle.setAttribute("aria-label", toggle.dataset.showLabel);
    }
  }

  function clearSensitiveInputs() {
    ["#setup-secret", "#setup-confirm", "#login-secret", "#gemini-key"].forEach((selector) => {
      resetSecret($(selector));
    });
  }

  function normalizeResult(payload) {
    return payload?.result ?? payload?.data ?? payload;
  }

  async function request(path, options = {}) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 35000);
    const headers = {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    };
    if (state.csrf && options.method && options.method !== "GET") {
      headers["X-CSRF-Token"] = state.csrf;
    }
    try {
      const response = await fetch(path, {
        ...options,
        credentials: "include",
        cache: "no-store",
        headers,
        signal: controller.signal,
      });
      let payload;
      try {
        payload = await response.json();
      } catch (_) {
        throw Object.assign(new Error("invalid_response"), { code: "invalid_response", status: response.status });
      }
      if (!response.ok || payload?.ok === false) {
        const error = Object.assign(new Error("operator_request_failed"), {
          code: typeof payload?.error_code === "string" ? payload.error_code : "operator_operation_failed",
          status: response.status,
        });
        if ((response.status === 401 || error.code === "csrf_required") && state.authenticated) {
          endSession(messageFor(error));
        }
        throw error;
      }
      return normalizeResult(payload);
    } catch (error) {
      if (error.code) throw error;
      throw Object.assign(new Error("operator_network_error"), {
        code: error.name === "AbortError" ? "request_timeout" : "network_error",
      });
    } finally {
      window.clearTimeout(timeout);
    }
  }

  function showView(view, focusSelector) {
    ["boot", "setup", "login", "dashboard"].forEach((name) => {
      $("#" + name + "-view").classList.toggle("hidden", name !== view);
    });
    $("#session-tools").classList.toggle("hidden", view !== "dashboard");
    if (focusSelector) requestAnimationFrame(() => $(focusSelector)?.focus());
  }

  function stopDeviceTimers(device = state.device) {
    if (!device) return;
    window.clearTimeout(device.pollTimer);
    window.clearInterval(device.ttlTimer);
    device.pollTimer = null;
    device.ttlTimer = null;
  }

  function clearDevice() {
    stopDeviceTimers();
    if ($("#device-dialog").open) $("#device-dialog").close();
    if (state.device) {
      state.device.code = "";
      state.device.url = "";
      state.device.id = "";
    }
    state.device = null;
    $("#device-code").textContent = "Esperando…";
    $("#device-url").removeAttribute("href");
    $("#device-url").classList.add("hidden");
    $("#copy-code").disabled = true;
  }

  function endSession(message = "") {
    state.sessionVersion += 1;
    state.authenticated = false;
    state.csrf = "";
    state.gemini = null;
    state.codex = null;
    state.accountBusy.clear();
    clearDevice();
    if ($("#confirm-dialog").open) finishConfirmation(false);
    clearSensitiveInputs();
    setNotice("");
    $("#login-error").textContent = message;
    $("#login-notice").hidden = true;
    showView("login", "#login-secret");
  }

  function showDashboard(session, notice = "") {
    state.authenticated = true;
    state.csrf = session?.csrf_token || session?.csrf || state.csrf;
    $("#operator-label").textContent = "Operador";
    showView("dashboard", "#page-title");
    if (notice) setNotice(notice, "success");
  }

  async function loadSession() {
    try {
      const data = await request("/api/operator/session");
      state.csrf = data?.csrf_token || data?.csrf || "";
      if (data?.setup_required) {
        showView("setup", "#setup-secret");
      } else if (data?.authenticated || data?.logged_in || data?.role === "operator") {
        showDashboard(data);
        await refreshAll();
      } else {
        showView("login", "#login-secret");
      }
    } catch (error) {
      showView("login", "#login-secret");
      if (error.status !== 401) $("#login-error").textContent = messageFor(error, "No se pudo comprobar la sesión. Puedes volver a intentar el acceso.");
    }
  }

  async function setup(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const errorElement = $("#setup-error");
    if (form.getAttribute("aria-busy") === "true" || !validateForm(form, errorElement)) return;
    const password = $("#setup-secret").value;
    const confirmation = $("#setup-confirm").value;
    if (password.length < 16) {
      invalidField($("#setup-secret"), errorElement, "Usa una contraseña de al menos 16 caracteres.");
      return;
    }
    if (password !== confirmation) {
      invalidField($("#setup-confirm"), errorElement, "Las contraseñas no coinciden.");
      return;
    }
    setBusy($("#setup-submit"), true, "Creando acceso…");
    setFormBusy(form, true);
    const body = JSON.stringify({ password, confirmation, password_confirm: confirmation });
    resetSecret($("#setup-secret"));
    resetSecret($("#setup-confirm"));
    try {
      const data = await request("/api/operator/setup", { method: "POST", body });
      state.csrf = data?.csrf_token || data?.csrf || state.csrf;
      if (data?.authenticated || data?.role === "operator") {
        showDashboard(data, "Acceso seguro creado. La consola está lista para preparar las cuentas.");
        await refreshAll();
      } else {
        state.csrf = "";
        showView("login", "#login-secret");
        $("#login-error").textContent = "";
        $("#login-notice").textContent = "Contraseña creada. Inicia sesión con ella para entrar a la consola.";
        $("#login-notice").hidden = false;
      }
    } catch (error) {
      errorElement.textContent = messageFor(error, "No se pudo guardar la contraseña. Vuelve a intentarlo.");
      requestAnimationFrame(() => $("#setup-secret").focus());
    } finally {
      setFormBusy(form, false);
      setBusy($("#setup-submit"), false);
    }
  }

  async function login(event) {
    event.preventDefault();
    const form = event.currentTarget;
    if (form.getAttribute("aria-busy") === "true" || !validateForm(form, $("#login-error"))) return;
    const body = JSON.stringify({ password: $("#login-secret").value });
    $("#login-notice").hidden = true;
    resetSecret($("#login-secret"));
    setBusy($("#login-submit"), true, "Verificando acceso…");
    setFormBusy(form, true);
    try {
      const data = await request("/api/operator/login", { method: "POST", body });
      showDashboard(data);
      await refreshAll();
    } catch (error) {
      $("#login-error").textContent = messageFor(error, "No se pudo iniciar sesión. Comprueba la contraseña e inténtalo de nuevo.");
      requestAnimationFrame(() => $("#login-secret").focus());
    } finally {
      setFormBusy(form, false);
      setBusy($("#login-submit"), false);
    }
  }

  async function logout() {
    if (state.device && !terminalPhases.has(state.device.phase)) {
      const confirmed = await confirmAction({
        title: "¿Cerrar sesión?",
        description: "Hay una autenticación en curso. Se cancelará antes de cerrar tu sesión de operador.",
        accept: "Cancelar y cerrar sesión",
        danger: true,
      });
      if (!confirmed || !await cancelDevice(false)) return;
    }
    setBusy($("#logout-button"), true, "Saliendo…");
    try {
      await request("/api/operator/logout", { method: "POST", body: "{}" });
      endSession();
    } catch (error) {
      if (state.authenticated) setNotice(messageFor(error, "No se pudo cerrar la sesión. Inténtalo de nuevo."), "error");
    } finally {
      setBusy($("#logout-button"), false);
    }
  }

  function healthInfo(item) {
    const health = String(item?.health || item?.status || "").toLowerCase();
    if (["healthy", "ready", "verified"].includes(health)) return { label: "Saludable", tone: "ready", healthy: true };
    if (["unhealthy", "failed", "error", "revoked", "invalid"].includes(health)) return { label: "Revisar", tone: "error", healthy: false };
    if (["cooldown", "rate_limited", "exhausted"].includes(health)) return { label: "En pausa", tone: "pending", healthy: false };
    return { label: "Pendiente", tone: "pending", healthy: false };
  }

  function badge(label, tone) {
    const element = document.createElement("span");
    element.className = "status-badge status-" + tone;
    const dot = textElement("span", "status-dot", "");
    dot.setAttribute("aria-hidden", "true");
    element.append(dot, textElement("span", "", label));
    return element;
  }

  function setBadge(element, label, tone) {
    element.className = "status-badge status-" + tone;
    element.replaceChildren(...badge(label, tone).childNodes);
  }

  function formatDate(value) {
    if (!value || value === "None") return "Sin revisión";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "Sin revisión" : dateFormat.format(date);
  }

  function renderOverview() {
    const projects = state.gemini || [];
    const healthy = projects.filter((project) => healthInfo(project).healthy).length;
    const connected = accounts.filter((account) => accountInfo(account).connected).length;
    const duplicate = accounts.some((account) => accountInfo(account).duplicate);
    const geminiLoaded = state.gemini !== null;
    const codexLoaded = state.codex !== null;
    const activeLogin = accounts.some((account) => accountInfo(account).active);
    const allReady = geminiLoaded && codexLoaded && healthy > 0 && connected === 2 && !duplicate && !activeLogin && !state.geminiError && !state.codexError;

    $("#summary-gemini").textContent = state.geminiError ? "No disponible" : geminiLoaded ? (projects.length ? healthy + " / " + projects.length + " saludables" : "Sin proyectos") : "Consultando…";
    $("#summary-gemini-detail").textContent = state.geminiError ? "Inventario no verificado" : geminiLoaded ? (projects.length ? numberFormat.format(projects.reduce((sum, project) => sum + (Number(project.capacity ?? project.max_trial_assignments) || 0), 0)) + " plazas configuradas · límite local" : "Registra una clave para comenzar") : "Verificando proyectos";
    $("#summary-gemini-signal").className = "summary-signal " + (state.geminiError ? "error" : healthy ? "ready" : "pending");
    $("#summary-codex").textContent = state.codexError ? "No disponible" : codexLoaded ? connected + " / 2 conectadas" : "Consultando…";
    $("#summary-codex-detail").textContent = state.codexError ? "Autenticación no verificada" : duplicate ? "Cuenta repetida: conecta dos cuentas distintas" : connected === 2 ? "Conexiones guardadas; imágenes sin probar" : "Se requieren dos cuentas independientes";
    $("#summary-codex-signal").className = "summary-signal " + (state.codexError || duplicate ? "error" : connected === 2 ? "ready" : "pending");
    $("#summary-broker").textContent = allReady ? "Prueba pendiente" : "Faltan cuentas";
    $("#summary-broker-detail").textContent = "Prueba real fuera del panel · servicio de imágenes no activado";
    $("#summary-broker-signal").className = "summary-signal " + (allReady ? "ready" : "pending");
    const label = state.geminiError || state.codexError ? "Hay estados sin verificar" : duplicate ? "Conecta dos cuentas distintas" : !geminiLoaded || !codexLoaded ? "Cargando estado" : allReady ? "Falta la prueba real de imágenes" : "Preparación incompleta";
    const tone = state.geminiError || state.codexError || duplicate ? "error" : !geminiLoaded || !codexLoaded ? "loading" : allReady ? "ready" : "pending";
    setBadge($("#global-status"), label, tone);
  }

  function renderGemini() {
    const rows = $("#gemini-rows");
    rows.replaceChildren();
    if (state.geminiError || !state.gemini?.length) {
      const row = document.createElement("tr");
      const cell = textElement("td", state.geminiError ? "error-cell" : "empty-cell", state.geminiError ? "Inventario no disponible. Usa «Actualizar inventario» para reintentar." : "Sin proyectos registrados. Valida una clave para crear el primer registro.");
      cell.colSpan = 4;
      row.append(cell);
      rows.append(row);
    } else {
      state.gemini.forEach((project) => {
        const row = document.createElement("tr");
        const health = healthInfo(project);
        const healthCell = document.createElement("td");
        healthCell.append(textElement("span", "health-cell " + health.tone, health.label));
        row.append(
          textElement("td", "", String(project.project_ref || "Sin referencia")),
          textElement("td", "", numberFormat.format(Number(project.capacity ?? project.max_trial_assignments) || 0)),
          healthCell,
          textElement("td", "", formatDate(project.health_checked_at || project.updated_at))
        );
        rows.append(row);
      });
    }
    const healthy = state.gemini?.filter((project) => healthInfo(project).healthy).length || 0;
    setBadge($("#gemini-health"), state.geminiError ? "Sin verificar" : healthy ? "Pool saludable" : "Pendiente", state.geminiError ? "error" : healthy ? "ready" : "pending");
    renderOverview();
  }

  async function refreshGemini({ announce = false } = {}) {
    if (state.geminiRequest) return state.geminiRequest;
    const sessionVersion = state.sessionVersion;
    $("#gemini-section").setAttribute("aria-busy", "true");
    setBusy($("#gemini-refresh"), true, "Consultando…");
    state.geminiRequest = (async () => {
      try {
        const data = await request("/api/operator/gemini/status");
        if (!state.authenticated || sessionVersion !== state.sessionVersion) return false;
        const projects = data?.projects || data?.items || data?.pool || [];
        state.gemini = Array.isArray(projects) ? projects : [];
        state.geminiError = false;
        $("#gemini-error").textContent = "";
        renderGemini();
        if (announce) setNotice("Inventario Gemini actualizado. Sólo se muestran metadatos redactados.", "success");
        return true;
      } catch (error) {
        if (!state.authenticated || sessionVersion !== state.sessionVersion) return false;
        state.geminiError = true;
        $("#gemini-error").textContent = messageFor(error, "No se pudo consultar el pool Gemini.");
        renderGemini();
        return false;
      } finally {
        $("#gemini-section").setAttribute("aria-busy", "false");
        setBusy($("#gemini-refresh"), false);
        state.geminiRequest = null;
      }
    })();
    return state.geminiRequest;
  }

  async function registerGemini(event) {
    event.preventDefault();
    const form = event.currentTarget;
    if (form.getAttribute("aria-busy") === "true" || !validateForm(form, $("#gemini-error"))) return;
    const project = $("#gemini-project").value.trim();
    const capacity = Number($("#gemini-capacity").value);
    if (!project) {
      invalidField($("#gemini-project"), $("#gemini-error"), "Escribe una referencia válida para el proyecto.");
      return;
    }
    if (!Number.isInteger(capacity) || capacity < 1 || capacity > 10000) {
      invalidField($("#gemini-capacity"), $("#gemini-error"), "La capacidad debe ser un número entero entre 1 y 10.000.");
      return;
    }
    const body = JSON.stringify({ project_ref: project, capacity, api_key: $("#gemini-key").value.trim() });
    resetSecret($("#gemini-key"));
    setFormBusy(form, true);
    setBusy($("#gemini-submit"), true, "Validando clave…");
    try {
      await request("/api/operator/gemini/register", { method: "POST", body });
      if (!state.authenticated) return;
      setNotice("Clave validada, disponible en el pool y borrada del formulario. No se crearon clientes ni se cambiaron sus claves actuales.", "success");
      await refreshGemini();
    } catch (error) {
      if (!state.authenticated) return;
      $("#gemini-error").textContent = messageFor(error, "No se pudo validar y registrar la clave. Se borró del formulario; introdúcela de nuevo para reintentar.");
      requestAnimationFrame(() => $("#gemini-key").focus());
    } finally {
      resetSecret($("#gemini-key"));
      setFormBusy(form, false);
      setBusy($("#gemini-submit"), false);
    }
  }

  function accountInfo(account) {
    const list = state.codex?.accounts || state.codex?.slots || state.codex?.items || state.codex || [];
    const item = Array.isArray(list) ? list.find((entry) => entry?.account === account || entry?.slot === account || entry?.id === account) || {} : list[account] || {};
    const raw = String(item.status || item.health || "").toLowerCase();
    const connected = item.authenticated === true || ["connected", "ready", "healthy", "verified"].includes(raw);
    const pendingJob = typeof item.job_id === "string" && raw === "connecting" ? item.job_id : "";
    const active = (state.device?.slot === account && !terminalPhases.has(state.device.phase)) || Boolean(pendingJob);
    const duplicate = item.duplicate_account === true;
    const common = { item, connected, active, duplicate, pendingJob };
    if (state.codexError) return { ...common, connected: false, label: "Sin verificar", tone: "error", detail: "No se pudo verificar la cuenta. Consulta su estado antes de operar." };
    if (active) return { ...common, label: "Autorizando", tone: "pending", detail: "Hay una autenticación activa. Abre su código temporal para completarla o cancelarla." };
    if (duplicate) return { ...common, label: "Cuenta repetida", tone: "error", detail: "Los dos perfiles usan la misma cuenta. Reconecta uno con otra cuenta antes de ejecutar la prueba real de imágenes." };
    if (connected) return { ...common, label: "Conexión guardada", tone: "ready", detail: "Autenticación guardada. La generación y la cuota disponible aún deben comprobarse con una prueba real de imágenes." };
    if (["cooldown", "rate_limited"].includes(raw)) return { ...common, label: "En pausa", tone: "pending", detail: "La cuenta alcanzó un límite temporal. Consulta de nuevo antes de la prueba real de imágenes." };
    return { ...common, label: "No conectada", tone: "pending", detail: "Autoriza esta cuenta en el portal oficial. No pegues contraseñas ni archivos de autenticación." };
  }

  function accountButton(action, account, text, style, disabled = false) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button " + style;
    button.dataset.slotAction = action;
    button.dataset.slot = account;
    button.disabled = disabled;
    button.setAttribute("aria-label", text + " · cuenta " + accountLabels[account]);
    button.append(textElement("span", "button-label", text));
    return button;
  }

  function renderCodex() {
    const focus = document.activeElement;
    const focusAction = focus?.dataset?.slotAction;
    const focusSlot = focus?.dataset?.slot;
    const container = $("#codex-slots");
    container.replaceChildren();
    accounts.forEach((account, index) => {
      const info = accountInfo(account);
      const busy = state.accountBusy.has(account);
      const card = document.createElement("article");
      card.className = "account-card" + (info.connected ? " is-connected" : "") + (info.tone === "error" ? " is-error" : "");
      card.setAttribute("aria-labelledby", "account-title-" + account);
      const head = textElement("div", "account-card-head", "");
      const identity = textElement("div", "account-identity", "");
      const indexElement = textElement("span", "account-index", String(index + 1).padStart(2, "0"));
      indexElement.setAttribute("aria-hidden", "true");
      const titleBlock = document.createElement("div");
      const title = textElement("h3", "", accountLabels[account]);
      title.id = "account-title-" + account;
      titleBlock.append(title, textElement("p", "account-role", account === "primary" ? "PRIMARY / PERFIL 01" : "SECONDARY / PERFIL 02"));
      identity.append(indexElement, titleBlock);
      head.append(identity, badge(info.label, info.tone));
      const actions = textElement("div", "account-actions", "");
      const unavailable = busy || (!state.codex && !state.codexError);
      if (info.active) {
        actions.append(accountButton("resume", account, "Ver autorización", "button-primary", unavailable));
      } else {
        actions.append(accountButton("connect", account, info.connected ? "Reconectar" : "Conectar cuenta", info.connected ? "button-quiet" : "button-primary", unavailable));
      }
      actions.append(accountButton("status", account, "Revisar estado", "button-quiet", busy));
      if (info.connected && !info.active) {
        actions.append(accountButton("disconnect", account, "Desconectar", "button-danger", unavailable));
      }
      card.append(head, textElement("p", "account-detail", info.detail), textElement("p", "account-meta", "PERFIL AISLADO · CREDENCIALES OCULTAS"), actions);
      container.append(card);
    });
    if (focusAction && focusSlot && !$("#device-dialog").open && !$("#confirm-dialog").open) {
      container.querySelector('[data-slot="' + focusSlot + '"][data-slot-action="' + focusAction + '"]')?.focus({ preventScroll: true });
    }
    renderOverview();
  }

  async function refreshCodex({ announce = false, account = "" } = {}) {
    if (state.codexRequest) return state.codexRequest;
    const sessionVersion = state.sessionVersion;
    $("#codex-section").setAttribute("aria-busy", "true");
    setBusy($("#codex-refresh"), true, "Revisando…");
    state.codexRequest = (async () => {
      try {
        const data = await request("/api/operator/codex/status");
        if (!state.authenticated || sessionVersion !== state.sessionVersion) return false;
        state.codex = data || {};
        state.codexError = false;
        $("#codex-error").textContent = "";
        renderCodex();
        if (announce) {
          const message = account ? accountLabels[account] + ": " + accountInfo(account).label.toLowerCase() + "." : "Estado de ambas cuentas actualizado.";
          setNotice(message, "success");
        }
        return true;
      } catch (error) {
        if (!state.authenticated || sessionVersion !== state.sessionVersion) return false;
        state.codexError = true;
        $("#codex-error").textContent = messageFor(error, "No se pudo consultar el estado de las cuentas. Vuelve a intentarlo.");
        renderCodex();
        return false;
      } finally {
        $("#codex-section").setAttribute("aria-busy", "false");
        setBusy($("#codex-refresh"), false);
        state.codexRequest = null;
      }
    })();
    return state.codexRequest;
  }

  function finishConfirmation(accepted) {
    const resolve = state.confirmResolve;
    state.confirmResolve = null;
    if ($("#confirm-dialog").open) $("#confirm-dialog").close();
    if (resolve) resolve(accepted);
  }

  function confirmAction({ title, description, accept, danger = false }) {
    if (state.confirmResolve) return Promise.resolve(false);
    const dialog = $("#confirm-dialog");
    $("#confirm-title").textContent = title;
    $("#confirm-description").textContent = description;
    $("#confirm-accept").textContent = accept;
    $("#confirm-accept").className = "button " + (danger ? "button-danger" : "button-primary");
    dialog.dataset.tone = danger ? "danger" : "default";
    return new Promise((resolve) => {
      state.confirmResolve = resolve;
      dialog.showModal();
      $("#confirm-cancel").focus();
    });
  }

  function safeAuthUrl(raw) {
    if (!raw || typeof raw !== "string") return "";
    try {
      const url = new URL(raw);
      if (url.protocol !== "https:" || !allowedAuthHosts.has(url.hostname) || url.username || url.password || url.port) return "";
      return url.href;
    } catch (_) {
      return "";
    }
  }

  function showDeviceDialog() {
    if (!state.device) return;
    const dialog = $("#device-dialog");
    if (!dialog.open) dialog.showModal();
    if (state.device.code) $("#copy-code").focus();
    else $("#device-close").focus();
  }

  function hideDeviceDialog() {
    if ($("#device-dialog").open) $("#device-dialog").close();
    if (state.device && !terminalPhases.has(state.device.phase)) {
      setNotice("La autenticación de " + accountLabels[state.device.slot] + " sigue activa. Usa «Ver autorización» para volver al código.");
      const trigger = $('[data-slot="' + state.device.slot + '"][data-slot-action="resume"]');
      trigger?.focus({ preventScroll: true });
    } else if (state.device) {
      $('[data-slot="' + state.device.slot + '"][data-slot-action="connect"]')?.focus({ preventScroll: true });
    }
  }

  async function resumeSlot(account) {
    if (!accounts.includes(account)) return;
    if (state.device?.slot === account && !terminalPhases.has(state.device.phase)) {
      showDeviceDialog();
      return;
    }
    const pendingJob = accountInfo(account).pendingJob;
    if (!pendingJob) {
      await refreshCodex({ announce: true, account });
      return;
    }
    if (state.device && !terminalPhases.has(state.device.phase)) {
      const replace = await confirmAction({
        title: "¿Cambiar la autorización visible?",
        description: "Se cancelará la autorización de " + accountLabels[state.device.slot] + " antes de recuperar la de " + accountLabels[account] + ".",
        accept: "Cancelar y recuperar",
        danger: true,
      });
      if (!replace || !await cancelDevice(false)) return;
    }
    clearDevice();
    const device = {
      slot: account, id: pendingJob, code: "", url: "", phase: "running",
      expiresAt: Date.now() + 600000, pollTimer: null, ttlTimer: null, pollFailures: 0,
    };
    state.device = device;
    $("#device-error").textContent = "";
    renderDevice(device);
    updateDeviceTimer(device);
    renderCodex();
    showDeviceDialog();
    device.ttlTimer = window.setInterval(() => updateDeviceTimer(device), 1000);
    await pollDevice(device);
  }

  function updateDeviceTimer(device) {
    if (state.device !== device) return;
    const remaining = Math.max(0, Math.ceil((device.expiresAt - Date.now()) / 1000));
    $("#device-ttl").textContent = Math.floor(remaining / 60) + ":" + String(remaining % 60).padStart(2, "0");
    if (!remaining && !terminalPhases.has(device.phase)) {
      device.phase = "expired";
      stopDeviceTimers(device);
      device.code = "";
      device.url = "";
      renderDevice(device);
      $("#device-error").textContent = "La ventana de autenticación terminó. Cierra esta ventana e inicia una nueva conexión.";
      $("#assertive-status").textContent = "El código de " + accountLabels[device.slot] + " caducó.";
      renderCodex();
      if (device.id) request("/api/operator/codex/login/" + encodeURIComponent(device.id) + "/cancel", { method: "POST", body: "{}" }).catch(() => {});
    }
  }

  function updateDevice(data, device) {
    if (state.device !== device) return;
    device.id = String(data?.job_id || data?.job || device.id || "");
    device.phase = String(data?.phase || data?.status || device.phase || "starting").toLowerCase();
    const code = data?.code || data?.user_code || data?.login_code;
    if (typeof code === "string" && /^[A-Za-z0-9 -]{4,40}$/.test(code)) device.code = code;
    const rawUrl = data?.url || data?.device_url || data?.verification_uri;
    if (rawUrl) {
      device.url = safeAuthUrl(rawUrl);
      if (!device.url) $("#device-error").textContent = "El servidor no devolvió un enlace oficial válido. Cancela y vuelve a intentarlo.";
    }
    const ttl = Number(data?.ttl_seconds ?? data?.expires_in);
    if (Number.isFinite(ttl) && ttl >= 0) device.expiresAt = Math.min(device.expiresAt, Date.now() + ttl * 1000);
    const expiresAt = Date.parse(data?.expires_at);
    if (Number.isFinite(expiresAt)) device.expiresAt = Math.min(device.expiresAt, expiresAt);
    if (data?.authenticated === true) device.phase = "completed";
    renderDevice(device);
    updateDeviceTimer(device);
  }

  function renderDevice(device) {
    const terminal = terminalPhases.has(device.phase);
    const phaseLabels = {
      starting: "Iniciando proceso",
      running: "Esperando código del proveedor",
      waiting_for_operator: "Esperando tu autorización",
      pending: "Esperando tu autorización",
      completed: "Autenticación completada",
      failed: "La autenticación no terminó",
      cancelled: "Autenticación cancelada",
      expired: "Ventana caducada",
    };
    $("#device-title").textContent = "Conectar cuenta " + accountLabels[device.slot];
    $("#device-code").textContent = terminal ? "No disponible" : device.code || "Esperando…";
    $("#copy-code").disabled = !device.code || terminal;
    $("#device-phase").textContent = phaseLabels[device.phase] || "Comprobando autenticación";
    $("#cancel-login").disabled = terminal || !device.id;
    if (device.url && !terminal) {
      $("#device-url").href = device.url;
      $("#device-url").classList.remove("hidden");
    } else {
      $("#device-url").removeAttribute("href");
      $("#device-url").classList.add("hidden");
    }
    $("#device-done").textContent = terminal ? "Cerrar ventana" : "Ocultar y seguir revisando";
  }

  async function finishDevice(device) {
    if (state.device !== device) return;
    stopDeviceTimers(device);
    const success = successfulPhases.has(device.phase);
    device.code = "";
    device.url = "";
    renderDevice(device);
    if (success) {
      if ($("#device-dialog").open) $("#device-dialog").close();
      setNotice(accountLabels[device.slot] + " completó la autenticación. Haz una prueba real de imágenes antes de habilitar el servicio de imágenes.", "success");
      state.device = null;
    } else {
      const messages = {
        expired: "El código caducó. Cierra esta ventana y vuelve a conectar la cuenta.",
        cancelled: "La autenticación fue cancelada. Puedes iniciar una conexión nueva.",
        failed: "El proveedor no completó la autenticación. Cierra esta ventana y vuelve a intentarlo.",
      };
      $("#device-error").textContent = messages[device.phase] || "La autenticación terminó sin confirmar la cuenta.";
    }
    await refreshCodex();
    if (success) $('[data-slot="' + device.slot + '"][data-slot-action="status"]')?.focus({ preventScroll: true });
  }

  async function pollDevice(device) {
    if (state.device !== device || !device.id || terminalPhases.has(device.phase) || !state.authenticated) return;
    try {
      const data = await request("/api/operator/codex/login/" + encodeURIComponent(device.id));
      if (state.device !== device) return;
      device.pollFailures = 0;
      $("#device-error").textContent = "";
      updateDevice(data, device);
      if (terminalPhases.has(device.phase)) {
        await finishDevice(device);
        return;
      }
      device.pollTimer = window.setTimeout(() => pollDevice(device), 1800);
    } catch (error) {
      if (state.device !== device || !state.authenticated) return;
      device.pollFailures += 1;
      if (error.status === 404) {
        device.phase = "failed";
        await finishDevice(device);
        return;
      }
      $("#device-error").textContent = messageFor(error, "No se pudo revisar la autorización. Se volverá a intentar mientras el código siga vigente.");
      device.pollTimer = window.setTimeout(() => pollDevice(device), Math.min(10000, 2500 * device.pollFailures));
    }
  }

  async function connectSlot(account) {
    if (!accounts.includes(account) || state.accountBusy.has(account)) return;
    if (state.device?.slot === account && !terminalPhases.has(state.device.phase)) {
      showDeviceDialog();
      return;
    }
    if (state.device && !terminalPhases.has(state.device.phase)) {
      const replace = await confirmAction({
        title: "Hay otra autorización activa",
        description: "Primero se cancelará la conexión de " + accountLabels[state.device.slot] + ". Después podrás conectar " + accountLabels[account] + ".",
        accept: "Cancelar y continuar",
        danger: true,
      });
      if (!replace || !await cancelDevice(false)) return;
    }
    const connected = accountInfo(account).connected;
    const confirmed = await confirmAction({
      title: (connected ? "¿Reconectar " : "¿Conectar ") + accountLabels[account] + "?",
      description: connected ? "Se iniciará una nueva autorización para este perfil. Usa la cuenta prevista para " + accountLabels[account] + "; no compartas el código temporal." : "Se abrirá una autorización por dispositivo en el portal oficial. Usa una cuenta independiente de la otra ranura y no compartas su código.",
      accept: connected ? "Iniciar reconexión" : "Iniciar autorización",
    });
    if (!confirmed || !state.authenticated) return;
    clearDevice();
    state.accountBusy.add(account);
    const device = {
      slot: account, id: "", code: "", url: "", phase: "starting",
      expiresAt: Date.now() + 600000, pollTimer: null, ttlTimer: null, pollFailures: 0,
    };
    state.device = device;
    $("#device-error").textContent = "";
    renderDevice(device);
    updateDeviceTimer(device);
    renderCodex();
    showDeviceDialog();
    device.ttlTimer = window.setInterval(() => updateDeviceTimer(device), 1000);
    try {
      const data = await request("/api/operator/codex/login", { method: "POST", body: JSON.stringify({ account }) });
      if (state.device !== device || !state.authenticated) return;
      updateDevice(data, device);
      if (!device.id && !terminalPhases.has(device.phase)) {
        throw Object.assign(new Error("invalid_response"), { code: "invalid_response" });
      }
      if (terminalPhases.has(device.phase)) await finishDevice(device);
      else device.pollTimer = window.setTimeout(() => pollDevice(device), 600);
    } catch (error) {
      if (state.device !== device || !state.authenticated) return;
      device.phase = "failed";
      stopDeviceTimers(device);
      device.code = "";
      device.url = "";
      renderDevice(device);
      $("#device-error").textContent = messageFor(error, "No se pudo iniciar la autenticación. Cierra esta ventana y vuelve a intentarlo.");
    } finally {
      state.accountBusy.delete(account);
      if (state.authenticated) renderCodex();
    }
  }

  async function cancelDevice(ask = true) {
    const device = state.device;
    if (!device || terminalPhases.has(device.phase)) return true;
    if (!device.id) {
      setNotice("La autenticación todavía está iniciando. Espera a que el servidor responda para cancelarla.");
      return false;
    }
    if (ask && !await confirmAction({
      title: "¿Cancelar esta autenticación?",
      description: "El código temporal de " + accountLabels[device.slot] + " dejará de funcionar. Podrás iniciar otra conexión cuando lo necesites.",
      accept: "Cancelar autenticación",
      danger: true,
    })) return false;
    setBusy($("#cancel-login"), true, "Cancelando…");
    try {
      await request("/api/operator/codex/login/" + encodeURIComponent(device.id) + "/cancel", { method: "POST", body: "{}" });
      if (state.device !== device) return true;
      const account = device.slot;
      clearDevice();
      setNotice("Autenticación de " + accountLabels[account] + " cancelada.");
      await refreshCodex();
      $('[data-slot="' + account + '"][data-slot-action="connect"]')?.focus({ preventScroll: true });
      return true;
    } catch (error) {
      if (state.authenticated) $("#device-error").textContent = messageFor(error, "No se pudo confirmar la cancelación. Reinténtalo antes de iniciar otra conexión.");
      return false;
    } finally {
      setBusy($("#cancel-login"), false);
    }
  }

  async function disconnectSlot(account) {
    if (!accounts.includes(account) || state.accountBusy.has(account)) return;
    const confirmed = await confirmAction({
      title: "¿Desconectar " + accountLabels[account] + "?",
      description: "Se eliminará la credencial local de este perfil. No se borrará la cuenta ChatGPT. El servicio de imágenes perderá esta opción hasta que vuelvas a autorizarla.",
      accept: "Desconectar cuenta",
      danger: true,
    });
    if (!confirmed || !state.authenticated) return;
    state.accountBusy.add(account);
    renderCodex();
    try {
      await request("/api/operator/codex/disconnect", { method: "POST", body: JSON.stringify({ account }) });
      if (!state.authenticated) return;
      setNotice(accountLabels[account] + " desconectada. Su credencial local fue retirada.", "success");
      await refreshCodex();
    } catch (error) {
      if (state.authenticated) setNotice(messageFor(error, "No se pudo desconectar la cuenta. Revisa su estado antes de reintentar."), "error");
    } finally {
      state.accountBusy.delete(account);
      if (state.authenticated) renderCodex();
    }
  }

  async function copyDeviceCode() {
    const device = state.device;
    if (!device?.code || terminalPhases.has(device.phase)) return;
    try {
      await navigator.clipboard.writeText(device.code);
      $("#device-error").textContent = "";
      $("#assertive-status").textContent = "Código temporal copiado. Pégalo únicamente en el portal oficial.";
      const label = $("#copy-code .button-label");
      label.textContent = "Copiado";
      window.setTimeout(() => { label.textContent = "Copiar código"; }, 2000);
    } catch (_) {
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents($("#device-code"));
      selection?.removeAllRanges();
      selection?.addRange(range);
      $("#device-code").focus();
      $("#device-error").textContent = "No se pudo copiar automáticamente. El código está seleccionado: cópialo con el teclado.";
    }
  }

  async function refreshAll() {
    await Promise.all([refreshGemini(), refreshCodex()]);
  }

  document.querySelectorAll("[data-password-toggle]").forEach((button) => {
    button.dataset.showLabel = button.getAttribute("aria-label");
    button.addEventListener("click", () => {
      const input = document.getElementById(button.dataset.passwordToggle);
      const visible = input.type === "password";
      input.type = visible ? "text" : "password";
      button.textContent = visible ? "Ocultar" : "Mostrar";
      button.setAttribute("aria-pressed", String(visible));
      button.setAttribute("aria-label", visible ? button.dataset.showLabel.replace("Mostrar", "Ocultar") : button.dataset.showLabel);
    });
  });

  document.querySelectorAll("input").forEach((input) => {
    input.addEventListener("input", () => input.removeAttribute("aria-invalid"));
  });

  $("#setup-form").addEventListener("submit", setup);
  $("#login-form").addEventListener("submit", login);
  $("#logout-button").addEventListener("click", logout);
  $("#gemini-form").addEventListener("submit", registerGemini);
  $("#gemini-refresh").addEventListener("click", () => refreshGemini({ announce: true }));
  $("#codex-refresh").addEventListener("click", () => refreshCodex({ announce: true }));
  $("#notice-close").addEventListener("click", () => setNotice(""));
  $("#codex-slots").addEventListener("click", (event) => {
    const button = event.target.closest("[data-slot-action]");
    if (!button || button.disabled) return;
    const account = button.dataset.slot;
    if (!accounts.includes(account)) return;
    if (button.dataset.slotAction === "connect") connectSlot(account);
    else if (button.dataset.slotAction === "resume") resumeSlot(account);
    else if (button.dataset.slotAction === "disconnect") disconnectSlot(account);
    else if (button.dataset.slotAction === "status") refreshCodex({ announce: true, account });
  });
  $("#device-close").addEventListener("click", hideDeviceDialog);
  $("#device-done").addEventListener("click", hideDeviceDialog);
  $("#device-dialog").addEventListener("cancel", (event) => {
    event.preventDefault();
    hideDeviceDialog();
  });
  $("#cancel-login").addEventListener("click", () => cancelDevice());
  $("#copy-code").addEventListener("click", copyDeviceCode);
  $("#confirm-cancel").addEventListener("click", () => finishConfirmation(false));
  $("#confirm-accept").addEventListener("click", () => finishConfirmation(true));
  $("#confirm-dialog").addEventListener("cancel", (event) => {
    event.preventDefault();
    finishConfirmation(false);
  });
  window.addEventListener("pagehide", () => {
    clearSensitiveInputs();
    clearDevice();
    state.csrf = "";
  });
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) {
      state.authenticated = false;
      showView("boot");
      loadSession();
    }
  });

  loadSession();
})();
