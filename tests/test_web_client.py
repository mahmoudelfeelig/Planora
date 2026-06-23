from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_web_client_assets_and_typescript_contract_exist():
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "web" / "src" / "react" / "App.tsx").read_text(encoding="utf-8")
    shell = (ROOT / "web" / "src" / "react" / "components" / "AppShell.tsx").read_text(encoding="utf-8")
    board = (ROOT / "web" / "src" / "react" / "components" / "ScheduleBoard.tsx").read_text(encoding="utf-8")
    login = (ROOT / "web" / "src" / "react" / "components" / "LoginPanel.tsx").read_text(encoding="utf-8")
    parity = (ROOT / "web" / "src" / "react" / "components" / "ParityPanel.tsx").read_text(encoding="utf-8")
    react_styles = (ROOT / "web" / "src" / "react" / "styles.css").read_text(encoding="utf-8")
    typescript = (ROOT / "web" / "src" / "main.ts").read_text(encoding="utf-8")
    javascript = (ROOT / "web" / "src" / "main.js").read_text(encoding="utf-8")
    styles = (ROOT / "web" / "src" / "styles.css").read_text(encoding="utf-8")
    result_module = (ROOT / "web" / "src" / "modules" / "results.ts").read_text(encoding="utf-8")
    view_module = (ROOT / "web" / "src" / "modules" / "workspace_views.ts").read_text(encoding="utf-8")

    assert 'id="root"' in index
    assert 'src="/src/react/main.tsx"' in index
    assert "createRoot" in (ROOT / "web" / "src" / "react" / "main.tsx").read_text(encoding="utf-8")
    assert "AppShell" in app
    assert "ScheduleBoard" in app
    assert "ReviewPanel" in app
    assert "ProjectsPanel" in app
    assert "AdminPanel" in app
    assert "LoginPanel" in app
    assert "privacyContent" in app
    assert "/privacy" in app
    assert "/system/email-test" in app
    assert "/analytics/summary" in app
    assert "ParityPanel" in app
    assert "move-target" in board
    assert "delta-badge" in board
    assert "Confirmation code" in login
    assert "Register" in login
    assert "Desktop / Backend / Web Parity" in parity
    assert "/auth/whoami" in app
    assert "/auth/login" in app
    assert "/auth/config" in app
    assert "/auth/register" in app
    assert "/audit" in app
    assert "/system" in app
    assert "/parity" in app
    assert "/jobs/improve" in app
    assert "hard_constraints:" in app
    assert "force_repeat_weekly_pattern: settings.forceRepeatWeeklyPattern" in app
    assert "VITE_PLANORA_API_URL" in app
    assert 'fetchJson("/sessions"' in typescript
    assert 'fetchJson("/jobs/solve"' in typescript
    assert 'fetchJson("/import/csv"' in typescript
    assert 'sessionAction("improve"' in typescript
    assert 'sessionAction("cp-polish"' in typescript
    assert 'sessionAction("export-csv"' in typescript
    assert 'sessionAction("move"' in typescript
    assert 'sessionAction("move-deltas"' in typescript
    assert "type Instance" in typescript
    assert "force_repeat_weekly_pattern" in typescript
    assert 'from "./modules/results.js"' in typescript
    assert 'from "./modules/workspace_views.js"' in typescript
    assert "fetchJson(\"/sessions\"" in javascript
    assert "fetchJson(\"/capabilities\"" in javascript
    assert "sessionAction(\"move-deltas\"" in javascript
    assert "window.open(endpoint(\"/openapi.json\")" in javascript
    assert 'from "./modules/results.js"' in javascript
    assert 'from "./modules/workspace_views.js"' in javascript
    assert "renderPenaltyDrivers" in result_module
    assert "renderReadableDiagnostics" in result_module
    assert "WORKSPACE_VIEWS" in view_module
    assert "Recalculate score" in (ROOT / "web" / "src" / "react" / "components" / "OperationsPanel.tsx").read_text(encoding="utf-8")
    assert "Import CSV with mapping" in (ROOT / "web" / "src" / "react" / "components" / "OperationsPanel.tsx").read_text(encoding="utf-8")
    assert "Repair Workflow" in (ROOT / "web" / "src" / "react" / "components" / "ReviewPanel.tsx").read_text(encoding="utf-8")
    assert "Role permission summary" in (ROOT / "web" / "src" / "react" / "components" / "AccessPanel.tsx").read_text(encoding="utf-8")
    assert ".workspace > * { min-height: 0; }" in styles
    assert ".main-pane {" in styles
    assert ".schedule-shell {" in styles
    assert "overflow: auto;" in styles
    assert ".results-view {" in styles
    assert ".pane-view {" in styles
    assert ".settings-grid" in styles
    assert ".hold-strip" in styles
    assert ".move-target.viable" in styles
    assert ".delta-badge" in styles
    assert ".app-layout" in react_styles
    assert ".navigation-rail" in react_styles
    assert ".identity-controls" in react_styles
    assert ".dashboard-grid" in react_styles
    assert ".operation-sections" in react_styles
    assert ".raw-panel pre" in styles


def test_web_has_typescript_build_scaffold():
    package_json = (ROOT / "web" / "package.json").read_text(encoding="utf-8")
    vite_config = (ROOT / "web" / "vite.config.ts").read_text(encoding="utf-8")
    playwright_config = (ROOT / "web" / "playwright.config.ts").read_text(encoding="utf-8")
    e2e_spec = (ROOT / "web" / "tests" / "e2e" / "public-flow.spec.ts").read_text(encoding="utf-8")
    assert '"typecheck": "tsc --noEmit"' in package_json
    assert '"e2e": "playwright test"' in package_json
    assert '"@playwright/test"' in package_json
    assert '"vite"' in package_json
    assert '"react"' in package_json
    assert '"@vitejs/plugin-react"' in package_json
    assert "defineConfig" in vite_config
    tsconfig = (ROOT / "web" / "tsconfig.json").read_text(encoding="utf-8")
    assert '"src/**/*.ts"' in tsconfig
    assert '"src/**/*.tsx"' in tsconfig
    assert '"jsx": "react-jsx"' in tsconfig
    assert "vite/client" in (ROOT / "web" / "src" / "vite-env.d.ts").read_text(encoding="utf-8")
    assert "Pixel 7" in playwright_config
    assert "public pages are navigable" in e2e_spec


def test_deployment_scaffold_exists():
    dockerfile = (ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
    prod_compose = (ROOT / "deploy" / "docker-compose.prod.yml").read_text(encoding="utf-8")
    env_example = (ROOT / "deploy" / ".env.example").read_text(encoding="utf-8")
    web_dockerfile = (ROOT / "deploy" / "web.Dockerfile").read_text(encoding="utf-8")
    caddyfile = (ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")
    assert "python:3.13-slim" in dockerfile
    assert "api.server" in dockerfile
    assert "planora-api" in compose
    assert "planora-web" in compose
    assert "planora-data" in compose
    assert "planora-web" in prod_compose
    assert "planora-caddy-data" in prod_compose
    assert "caddy:2.9-alpine" in web_dockerfile
    assert "PLANORA_DOMAIN" in caddyfile
    assert "PLANORA_DB_PATH" in env_example
    assert "VITE_PLANORA_API_URL" in env_example
    assert "PLANORA_SMTP_HOST" in env_example
    assert "PLANORA_REGISTRATION_ENABLED" in env_example
    assert "PLANORA_AUTH_SECRET" in env_example
    assert "PLANORA_TOKEN_PEPPER" in env_example
    assert "PLANORA_SMTP_PASSWORD" in env_example
    assert "PLANORA_AUTH_SECRET_FILE" not in prod_compose
    assert "method='HEAD'" in prod_compose


def test_web_client_uses_root_application_logo():
    root_logo = (ROOT / "app_icon.png").read_bytes()
    web_logo = (ROOT / "web" / "public" / "app-icon.png").read_bytes()
    assert hashlib.sha256(root_logo).digest() == hashlib.sha256(web_logo).digest()


def test_registration_flow_handles_immediate_auth_payload():
    app = (ROOT / "web" / "src" / "react" / "App.tsx").read_text(encoding="utf-8")
    login = (ROOT / "web" / "src" / "react" / "components" / "LoginPanel.tsx").read_text(encoding="utf-8")

    assert "if (payload.token && payload.principal)" in app
    assert 'return false;' in app
    assert "onRegister(): boolean | Promise<boolean>" in login
    assert "if (await onRegister())" in login
