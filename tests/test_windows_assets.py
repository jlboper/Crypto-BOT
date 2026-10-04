import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class WindowsAssetTests(unittest.TestCase):
    def test_windows_scripts_keep_utf8_bom(self):
        for relative in ("scripts/manager_windows.ps1", "scripts/update_windows.ps1", "scripts/refresh_windows_agent.ps1"):
            with self.subTest(relative=relative):
                self.assertTrue((PROJECT_ROOT / relative).read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_status_icons_are_valid_ico_files(self):
        for name in (
            "crypto-ai-trader.ico",
            "crypto-ai-trader-warning.ico",
            "crypto-ai-trader-offline.ico",
        ):
            with self.subTest(name=name):
                payload = (PROJECT_ROOT / "web" / name).read_bytes()
                self.assertTrue(payload.startswith(b"\x00\x00\x01\x00"))
                self.assertGreater(len(payload), 1024)

    def test_manager_updates_locally_with_independent_signed_supervisor(self):
        source = (PROJECT_ROOT / "scripts" / "manager_windows.ps1").read_text(encoding="utf-8-sig")
        self.assertIn(
            '$RemotePortalUrl = "https://crypto-paper-private-portal.jlboper.workers.dev/"',
            source,
        )
        self.assertIn('$openRemoteButton.Add_Click({ Start-Process -FilePath $RemotePortalUrl })', source)
        self.assertIn('$updateButton.Add_Click({ Show-LocalUpdateCenter })', source)
        self.assertIn('$checkUpdatesItem.Add_Click({ Show-LocalUpdateCenter })', source)
        self.assertIn('scripts\\local_update.py', source)
        self.assertIn('--agent-root', source)
        self.assertIn('-ApprovedRelease $verified.release_id', source)
        self.assertNotIn('Start-Process -FilePath $UpdateCenterUrl', source)
        self.assertIn('$notifyMenu.Items.Add("Abrir portal remoto")', source)
        self.assertIn('$notifyMenu.Items.Add("Centro de actualizaciones")', source)
        self.assertIn('$notifyMenu.Items.Add("Reparar conexión del portal")', source)
        self.assertNotIn('$notifyMenu.Items.Add("Verificar GPT-6 Luna")', source)
        self.assertNotIn('$notifyMenu.Items.Add("Verificar Binance Testnet")', source)
        refresh = (PROJECT_ROOT / "scripts" / "refresh_windows_agent.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("agent_self_heal.ps1", refresh)
        self.assertNotIn('Stop-TradingBot', refresh)
        self.assertIn('[switch]$ForceRestart', refresh)
        self.assertIn('function Invoke-PortalAgentWatchdog', source)
        self.assertIn("$pythonPathPattern = '(?i)-PythonPath\\s+\"([^\"]+)\"'", source)
        self.assertIn("if ($taskArguments -match $pythonPathPattern)", source)
        self.assertIn("No se encontró el mismo runtime Python verificado", source)
        self.assertNotIn("Get-Command py.exe", source)
        self.assertIn("Ya estás actualizado. Versión instalada y firma verificada", source)
        self_heal = (PROJECT_ROOT / "scripts" / "agent_self_heal.ps1").read_text(encoding="utf-8-sig")
        install = (PROJECT_ROOT / "scripts" / "install_agent_autostart.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("RestartCount 999", self_heal)
        self.assertIn("AUTO_REFRESH_AGENT", self_heal)
        self.assertIn("refresh_independent_agent.py", self_heal)
        self.assertIn("direct_pythonw", self_heal)
        self.assertIn("$successes -lt 2", self_heal)
        self.assertIn("Write-HealState 'configuring_task'", self_heal)
        self.assertIn("Write-HealState 'starting_agent'", self_heal)
        self.assertIn("Set-ScheduledTask -TaskName $taskName -Action $newTaskAction", self_heal)
        self.assertNotIn("New-ScheduledTaskAction -Execute $powershell", self_heal)
        self.assertIn("RestartCount 999", install)
        self.assertIn("windows_agent.py", install)
        self.assertIn("New-ScheduledTaskAction -Execute $portalPython", install)
        self.assertNotIn("agent_watchdog.ps1", install)
        self.assertNotIn("powershell.exe", install)
        cli = (PROJECT_ROOT / "trader" / "cli.py").read_text(encoding="utf-8")
        self.assertIn("control.await_activation()\n                    _start_windows_agent_self_heal()", cli)
        self.assertIn("$script:AgentHealthFailures -lt 2", source)
        self.assertIn("Stop-ScheduledTask -TaskName 'Crypto Paper Portal Agent'", source)
        self.assertIn("Start-ScheduledTask -TaskName 'Crypto Paper Portal Agent'", source)
        self.assertIn("Invoke-TradingEngineWatchdog", source)

    def test_spot_positions_table_keeps_standard_desktop_typography(self):
        css = (PROJECT_ROOT / "web" / "monitoring.css").read_text(encoding="utf-8")
        self.assertIn(".compact-engine-table table{min-width:760px}", css)
        self.assertIn(".compact-engine-table th,.compact-engine-table td{padding-left:10px;padding-right:10px}", css)
        self.assertNotIn(".compact-engine-table table{min-width:0;table-layout:fixed;font-size:11px}", css)

    def test_portal_motion_is_lightweight_and_respects_reduced_motion(self):
        css = (PROJECT_ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        app = (PROJECT_ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("v0.10.3 — lightweight portal motion layer", css)
        self.assertIn("@media (prefers-reduced-motion:reduce)", css)
        self.assertIn("portalOperationalPulse 2.8s", css)
        self.assertIn("function installPortalMotion()", app)
        self.assertIn("new MutationObserver", app)
        self.assertIn("retriggerMotion(canvas,'motion-chart')", app)
        self.assertNotIn("setInterval(()=>requestAnimationFrame", app)

    def test_release_workflow_uses_owner_approval_before_merge(self):
        workflow = (PROJECT_ROOT / ".github" / "workflows" / "portal-release.yml").read_text(encoding="utf-8")
        self.assertIn("pull_request:", workflow)
        self.assertIn("types: [opened, synchronize, reopened]", workflow)
        self.assertNotIn("pull_request_target:", workflow)
        self.assertIn("startsWith(github.head_ref, 'release/')", workflow)
        self.assertIn("github.event.pull_request.head.sha", workflow)
        self.assertIn("environment: portal-production", workflow)
        self.assertNotIn("push:\n    branches: [main]", workflow)


    def test_options_menu_stays_above_engine_panels(self):
        css = (PROJECT_ROOT / "web" / "portal.css").read_text(encoding="utf-8")
        self.assertIn("header{position:relative;z-index:100;overflow:visible}", css)
        self.assertIn(".header-actions{position:relative;z-index:110;overflow:visible}", css)
        self.assertIn(".options{position:relative;z-index:120}", css)
        self.assertIn(".options-menu{z-index:1000}", css)
        self.assertIn(".engine-workspace,.engine-console{position:relative;z-index:1}", css)

    def test_observation_and_limit_ui_are_homologated(self):
        app = (PROJECT_ROOT / "web" / "app.js").read_text(encoding="utf-8")
        html = (PROJECT_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        css = (PROJECT_ROOT / "web" / "monitoring.css").read_text(encoding="utf-8")
        self.assertIn("PROTECCIONES ACTIVAS", app)
        self.assertIn("activityLabel(spotActivity)", app)
        self.assertIn("Incidentes / intentos / ciclos", html)
        self.assertIn('id="spotHealthReason"', html)
        self.assertIn('id="futuresHealthReason"', html)
        self.assertIn('id="spotConsecutiveErrors"', html)
        self.assertIn('id="spotLastError"', html)
        self.assertIn("UNEXPECTED_VALUE_ERROR", (PROJECT_ROOT / "trader" / "engine.py").read_text(encoding="utf-8"))
        self.assertIn("Expectativa neta / cierre", app)
        self.assertIn("Expectativa de estrategia / cierre", app)
        self.assertIn("PENDIENTE DE TELEMETRÍA", app)
        self.assertIn(".health-reason{", css)
        self.assertNotIn("String(futuresHealth.errors_total||0)+' total'", app)

    def test_manager_retires_sha_only_update_installer(self):
        source = (PROJECT_ROOT / "scripts" / "manager_windows.ps1").read_text(encoding="utf-8-sig")
        self.assertNotIn("raw.githubusercontent.com/jlboper/Crypto-BOT", source)
        self.assertNotIn("Get-RemoteUpdate", source)
        self.assertNotIn("Install-RemoteUpdate", source)
        self.assertNotIn("Get-FileHash", source)
        self.assertNotIn("Invoke-WebRequest", source)
        self.assertNotIn("Instalar actualización local...", source)

    def test_header_logo_is_a_valid_png(self):
        payload = (PROJECT_ROOT / "web" / "crypto-ai-trader-icon.png").read_bytes()
        self.assertTrue(payload.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_portal_includes_installable_research_lab(self):
        html = (PROJECT_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        manifest = (PROJECT_ROOT / "web" / "manifest.webmanifest").read_text(encoding="utf-8")
        script = (PROJECT_ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("EVALUACIÓN HISTÓRICA", html)
        self.assertIn('"display": "standalone"', manifest)
        self.assertIn("/api/research/run", script)
        self.assertIn("serviceWorker", script)
        self.assertIn("Exportar CSV", html)
        self.assertIn("Estrategia fija", html)
        self.assertIn("Selector adaptativo", html)
        self.assertIn("/^[=+\\-@\\t\\r]/", script)
        self.assertIn("Number(row.folds||0)", script)

    def test_portal_brand_keeps_logo_and_title_aligned(self):
        html = (PROJECT_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        css = (PROJECT_ROOT / "web" / "portal.css").read_text(encoding="utf-8")
        shared_css = (PROJECT_ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        app = (PROJECT_ROOT / "web" / "app.js").read_text(encoding="utf-8")
        bridge = (PROJECT_ROOT / "web" / "portal-bridge.js").read_text(encoding="utf-8")
        dashboard = (PROJECT_ROOT / "trader" / "dashboard.py").read_text(encoding="utf-8")
        self.assertIn('<div class="brand">', html)
        self.assertIn('<div class="brand-copy">', html)
        self.assertIn('id="botVersion"', html)
        self.assertIn(".brand{display:flex;align-items:center", css)
        self.assertIn(".brand-mark{float:none;margin:0;flex:0 0 44px}", css)
        self.assertIn(".bot-version{", shared_css)
        self.assertIn("status.installed_version", app)
        self.assertIn("state.snapshot?.installed_version", bridge)
        self.assertIn('"installed_version": tomllib.loads', dashboard)

    def test_portal_declares_multi_asset_forward_positions_before_render(self):
        app = (PROJECT_ROOT / "web" / "app.js").read_text(encoding="utf-8")
        declaration = "const forwardPositions=Array.isArray(futuresForward?.positions)?futuresForward.positions:[];"
        self.assertIn(declaration, app)
        self.assertLess(app.index(declaration), app.index("forwardPositions.length"))

    def test_portal_keeps_spot_and_futures_detail_panels_in_parity(self):
        html = (PROJECT_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        app = (PROJECT_ROOT / "web" / "app.js").read_text(encoding="utf-8")
        css = (PROJECT_ROOT / "web" / "monitoring.css").read_text(encoding="utf-8")
        for value in (
            "Límites Spot", "Límites Futures · DEMO",
            "Posiciones abiertas · Spot", "Posiciones abiertas · Futures",
            "Seguimiento financiero Futures · DEMO",
            'id="futuresTradeRows"', 'id="futuresLimitBudget"',
        ):
            self.assertIn(value, html)
        self.assertIn("function renderFuturesParity", app)
        self.assertIn("futures?.guardrails", app)
        self.assertIn("futures?.position", app)
        self.assertIn(".dual-detail-grid", css)

    def test_portal_renders_futures_pause_diagnostics(self):
        html = (PROJECT_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        app = (PROJECT_ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="futuresForwardPauseReason"', html)
        self.assertIn("pause_diagnostics", app)
        self.assertIn("Motivo de pausa", app)
        self.assertIn("pending_reconciliation", app)

    def test_portal_uses_one_options_menu_and_one_update_search(self):
        html = (PROJECT_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="optionsButton"', html)
        self.assertIn('id="optionsMenu"', html)
        self.assertIn('id="checkAllUpdates"', html)
        self.assertNotIn('id="checkUpdates"', html)
        self.assertNotIn('id="checkBotUpdate"', html)
        self.assertIn('id="updateHeadline"', html)
        self.assertIn('id="updateHero"', html)
        self.assertIn('id="testTestnetExecution"', html)
        self.assertIn('id="testFuturesExecution"', html)
        self.assertIn('id="checkFuturesTestnet"', html)
        self.assertIn('id="reconcileFutures"', html)
        self.assertIn('Respaldo técnico / PAPER', html)
        self.assertIn('USDⓈ-M Futures Demo', html)
        self.assertIn('class="engine-workspace"', html)
        self.assertIn('id="equityChart"', html)
        self.assertIn('id="futuresEquityChart"', html)
        self.assertIn('id="futuresForwardReturn"', html)
        self.assertIn('Motores e IA', html)
        self.assertIn('Diagnóstico avanzado', html)
        bridge = (PROJECT_ROOT / "web" / "portal-bridge.js").read_text(encoding="utf-8")
        self.assertIn("Nueva versión disponible", bridge)
        self.assertIn("Estás actualizado", bridge)
        self.assertIn("checkAllUpdates(false);", bridge)
        self.assertIn("if(location.hash==='#updates')checkAllUpdates(false)", bridge)
        self.assertIn("Instalar v${candidate.version}", bridge)
        self.assertIn("/api/local-update/check", bridge)
        self.assertIn("/api/local-update/install", bridge)

    def test_remote_update_deep_link_opens_the_shared_center(self):
        bridge = (PROJECT_ROOT / "web" / "portal-bridge.js").read_text(encoding="utf-8")
        self.assertIn("location.hash==='#updates'", bridge)
        self.assertIn("Revisar y autorizar publicación en GitHub", bridge)
        self.assertNotIn("/v1/updates/approve", bridge)

    def test_research_runs_outside_the_engine_process(self):
        source = (PROJECT_ROOT / "trader" / "dashboard.py").read_text(encoding="utf-8")
        self.assertIn("subprocess.Popen", source)
        runtime = (PROJECT_ROOT / "trader" / "research_runtime.py").read_text(encoding="utf-8")
        self.assertIn("ResearchScheduler", source)
        self.assertIn("subprocess.Popen", runtime)
        self.assertIn("research_worker.py", runtime)
        self.assertIn("CREATE_NO_WINDOW", runtime)
        updater = (PROJECT_ROOT / "scripts" / "update_windows.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("trader.update_manager apply", updater)
        self.assertNotIn("Stop-Process", updater)

    def test_manager_stays_in_background_until_explicit_exit(self):
        source = (PROJECT_ROOT / "scripts" / "manager_windows.ps1").read_text(encoding="utf-8-sig")
        launcher = (PROJECT_ROOT / "Crypto AI Trader.vbs").read_text(encoding="utf-8-sig")
        self.assertIn("-STA", launcher)
        self.assertIn("[System.Windows.Forms.Application]::Run($form)", source)
        self.assertIn("CloseReason]::UserClosing", source)
        self.assertIn("$eventArgs.Cancel = $true", source)
        self.assertIn("Hide-ManagerWindow", source)
        self.assertIn('$notifyMenu.Items.Add("Salir del indicador")', source)

    def test_windows_uses_branded_icons_and_persistent_startup(self):
        source = (PROJECT_ROOT / "scripts" / "manager_windows.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("SetCurrentProcessExplicitAppUserModelID", source)
        self.assertIn('$form.Icon = $script:FormIcon', source)
        self.assertIn('$notifyIcon.Icon = $script:OperationalIcon', source)
        self.assertIn('$shortcut.IconLocation = $OperationalIconPath + ",0"', source)
        self.assertIn("DISABLE_AUTO_START", source)


if __name__ == "__main__":
    unittest.main()
