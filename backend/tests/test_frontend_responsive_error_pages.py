from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = PROJECT_ROOT / "frontend"
PAGES = FRONTEND / "pages"


RESPONSIVE_PAGES = [
    PAGES / "index.vue",
    PAGES / "blog" / "index.vue",
    PAGES / "forum" / "index.vue",
    PAGES / "tools" / "index.vue",
    PAGES / "open-source" / "index.vue",
    PAGES / "auth" / "login.vue",
    PAGES / "auth" / "register.vue",
    PAGES / "auth" / "password-reset.vue",
    PAGES / "user" / "index.vue",
]

KEY_STATE_PAGES = [
    PAGES / "blog" / "index.vue",
    PAGES / "forum" / "index.vue",
    PAGES / "tools" / "index.vue",
    PAGES / "open-source" / "index.vue",
    PAGES / "tools" / "jobs" / "index.vue",
    PAGES / "tools" / "jobs" / "[job_id].vue",
]


def read(path: Path) -> str:
    return path.read_text()


def test_story_7_2_has_project_level_404_and_generic_error_page() -> None:
    error_page = FRONTEND / "error.vue"
    source = read(error_page)

    assert "statusCode.value === 404" in source
    assert "页面不存在" in source
    assert "页面暂时不可用" in source
    assert "返回首页" in source


def test_story_7_2_core_pages_have_responsive_rules() -> None:
    missing = [str(path.relative_to(PROJECT_ROOT)) for path in RESPONSIVE_PAGES if "@media (max-width" not in read(path)]

    assert missing == []


def test_story_7_2_unauthorized_and_forbidden_states_have_next_actions() -> None:
    error_page = read(FRONTEND / "error.vue")
    forum_new = read(PAGES / "forum" / "new.vue")
    user_center = read(PAGES / "user" / "index.vue")

    assert "statusCode.value === 401" in error_page
    assert "statusCode.value === 403" in error_page
    assert "没有访问权限" in error_page
    assert "登录" in forum_new and "注册" in forum_new
    assert "需要登录" in user_center and "/auth/login?redirect=/user" in user_center


def test_story_7_2_key_frontend_pages_have_loading_empty_and_error_states() -> None:
    missing = []
    for path in KEY_STATE_PAGES:
        source = read(path)
        if "pending" not in source or "error" not in source:
            missing.append(f"{path.relative_to(PROJECT_ROOT)}:loading-or-error")
        if "empty-state" not in source and "暂无" not in source and "不存在" not in source:
            missing.append(f"{path.relative_to(PROJECT_ROOT)}:empty")

    assert missing == []


def test_story_7_2_frontend_uses_defined_error_color_token() -> None:
    offenders = []
    for path in FRONTEND.rglob("*.vue"):
        if "node_modules" in path.parts:
            continue
        if "var(--color-error)" in read(path):
            offenders.append(str(path.relative_to(PROJECT_ROOT)))

    assert offenders == []
