from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = PROJECT_ROOT / "frontend"
PAGES = FRONTEND / "pages"


SMOKE_ROUTES = {
    "/": PAGES / "index.vue",
    "/blog": PAGES / "blog" / "index.vue",
    "/blog/[slug]": PAGES / "blog" / "[slug].vue",
    "/forum": PAGES / "forum" / "index.vue",
    "/forum/[id]": PAGES / "forum" / "[id].vue",
    "/forum/new": PAGES / "forum" / "new.vue",
    "/forum/rules": PAGES / "forum" / "rules.vue",
    "/tools": PAGES / "tools" / "index.vue",
    "/tools/[slug]": PAGES / "tools" / "[slug].vue",
    "/tools/jobs": PAGES / "tools" / "jobs" / "index.vue",
    "/tools/jobs/[job_id]": PAGES / "tools" / "jobs" / "[job_id].vue",
    "/open-source": PAGES / "open-source" / "index.vue",
    "/open-source/[id]": PAGES / "open-source" / "[id].vue",
    "/auth/login": PAGES / "auth" / "login.vue",
    "/auth/register": PAGES / "auth" / "register.vue",
    "/auth/password-reset": PAGES / "auth" / "password-reset.vue",
    "/auth/verify-email": PAGES / "auth" / "verify-email.vue",
    "/user": PAGES / "user" / "index.vue",
    "/legal/terms": PAGES / "legal" / "terms.vue",
    "/legal/privacy": PAGES / "legal" / "privacy.vue",
    "/legal/risk-disclaimer": PAGES / "legal" / "risk-disclaimer.vue",
}

RESPONSIVE_SMOKE_ROUTES = [
    "/",
    "/blog",
    "/forum",
    "/tools",
    "/open-source",
    "/auth/login",
    "/auth/register",
    "/user",
]

RISK_LINK_ROUTES = [
    "/blog/[slug]",
    "/tools/[slug]",
    "/open-source/[id]",
]

STATEFUL_ROUTES = [
    "/blog",
    "/forum",
    "/tools",
    "/tools/jobs",
    "/tools/jobs/[job_id]",
    "/open-source",
]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_frontend_smoke_routes_have_page_components() -> None:
    missing = [f"{route}:{path.relative_to(PROJECT_ROOT)}" for route, path in SMOKE_ROUTES.items() if not path.exists()]

    assert missing == []


def test_frontend_smoke_routes_have_template_and_script_sections() -> None:
    missing = []
    for route, path in SMOKE_ROUTES.items():
        source = read(path)
        if "<template>" not in source:
            missing.append(f"{route}:template")
        if "<script setup" not in source:
            missing.append(f"{route}:script-setup")

    assert missing == []


def test_frontend_responsive_smoke_routes_have_mobile_breakpoints() -> None:
    missing = [route for route in RESPONSIVE_SMOKE_ROUTES if "@media (max-width" not in read(SMOKE_ROUTES[route])]

    assert missing == []


def test_frontend_public_content_routes_link_risk_disclaimer() -> None:
    missing = [route for route in RISK_LINK_ROUTES if "/legal/risk-disclaimer" not in read(SMOKE_ROUTES[route])]

    assert missing == []


def test_frontend_stateful_smoke_routes_have_loading_error_and_empty_states() -> None:
    missing = []
    for route in STATEFUL_ROUTES:
        source = read(SMOKE_ROUTES[route])
        if "pending" not in source:
            missing.append(f"{route}:pending")
        if "error" not in source:
            missing.append(f"{route}:error")
        if "empty-state" not in source and "暂无" not in source and "不存在" not in source:
            missing.append(f"{route}:empty")

    assert missing == []


def test_frontend_error_page_is_global_smoke_fallback() -> None:
    source = read(FRONTEND / "error.vue")

    assert "statusCode.value === 404" in source
    assert "statusCode.value === 401" in source
    assert "statusCode.value === 403" in source
    assert "返回首页" in source
