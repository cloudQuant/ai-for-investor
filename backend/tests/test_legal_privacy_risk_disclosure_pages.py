from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = PROJECT_ROOT / "frontend"
PAGES = FRONTEND / "pages"
LEGAL = PAGES / "legal"


def read(path: Path) -> str:
    return path.read_text()


def test_story_7_3_legal_pages_exist() -> None:
    assert (LEGAL / "terms.vue").exists()
    assert (LEGAL / "privacy.vue").exists()
    assert (LEGAL / "risk-disclaimer.vue").exists()


def test_story_7_3_risk_disclaimer_states_mvp_boundaries() -> None:
    source = read(LEGAL / "risk-disclaimer.vue")

    assert "仅供教育与研究目的" in source
    assert "不提供投资建议" in source
    assert "不接入真实交易 API" in source
    assert "不连接券商或交易所账户" in source
    assert "不托管用户资金" in source
    assert "不允许任意用户代码执行" in source
    assert "过往表现不代表未来收益" in source


def test_story_7_3_user_agreement_and_privacy_policy_include_required_boundaries() -> None:
    terms = read(LEGAL / "terms.vue")
    privacy = read(LEGAL / "privacy.vue")

    assert "不构成投资建议" in terms
    assert "不提供真实交易 API" in terms
    assert "不托管用户资金" in terms
    assert "不允许任意用户代码执行" in terms
    assert "券商账号" in privacy
    assert "交易所 API Key" in privacy
    assert "真实交易凭证" in privacy


def test_story_7_3_global_footer_links_to_legal_pages() -> None:
    layout = read(FRONTEND / "layouts" / "default.vue")

    assert "/legal/terms" in layout
    assert "/legal/privacy" in layout
    assert "/legal/risk-disclaimer" in layout
    assert "不构成投资建议" in layout


def test_story_7_3_public_content_and_tool_pages_link_disclaimers() -> None:
    required_pages = [
        PAGES / "index.vue",
        PAGES / "blog" / "[slug].vue",
        PAGES / "tools" / "index.vue",
        PAGES / "tools" / "[slug].vue",
        PAGES / "open-source" / "[id].vue",
    ]
    missing = [str(path.relative_to(PROJECT_ROOT)) for path in required_pages if "/legal/risk-disclaimer" not in read(path)]

    assert missing == []
