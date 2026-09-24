import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class WindowsAssetTests(unittest.TestCase):
    def test_windows_scripts_keep_utf8_bom(self):
        for relative in ("scripts/manager_windows.ps1", "scripts/update_windows.ps1"):
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

    def test_manager_routes_remote_portal_and_updates_through_public_portal(self):
        source = (PROJECT_ROOT / "scripts" / "manager_windows.ps1").read_text(encoding="utf-8-sig")
        self.assertIn(
            '$RemotePortalUrl = "https://crypto-paper-private-portal.jlboper.workers.dev/"',
            source,
        )
        self.assertIn('$UpdateCenterUrl = $RemotePortalUrl + "#updates"', source)
        self.assertIn('$openRemoteButton.Add_Click({ Start-Process -FilePath $RemotePortalUrl })', source)
        self.assertIn('$updateButton.Add_Click({ Start-Process -FilePath $UpdateCenterUrl })', source)
        self.assertIn('$notifyMenu.Items.Add("Abrir portal remoto")', source)
        self.assertIn('$notifyMenu.Items.Add("Centro de actualizaciones")', source)

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
        self.assertIn("EVALUACIÓN HISTÓRICA · V0.6.10", html)
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
        self.assertIn('<div class="brand">', html)
        self.assertIn('<div class="brand-copy">', html)
        self.assertIn(".brand{display:flex;align-items:center", css)
        self.assertIn(".brand-mark{float:none;margin:0;flex:0 0 44px}", css)

    def test_portal_uses_one_options_menu_and_one_update_search(self):
        html = (PROJECT_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="optionsButton"', html)
        self.assertIn('id="optionsMenu"', html)
        self.assertIn('id="checkAllUpdates"', html)
        self.assertNotIn('id="checkUpdates"', html)
        self.assertNotIn('id="checkBotUpdate"', html)

    def test_remote_update_deep_link_opens_the_shared_center(self):
        bridge = (PROJECT_ROOT / "web" / "portal-bridge.js").read_text(encoding="utf-8")
        self.assertIn("location.hash==='#updates'", bridge)
        self.assertIn("Revisar y autorizar publicación en GitHub", bridge)
        self.assertNotIn("/v1/updates/approve", bridge)

    def test_research_runs_outside_the_engine_process(self):
        source = (PROJECT_ROOT / "trader" / "dashboard.py").read_text(encoding="utf-8")
        self.assertIn("subprocess.Popen", source)
        self.assertIn('"-m", "trader", "research"', source)
        self.assertIn("CREATE_NO_WINDOW", source)
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
