from app.content.forum_seed import (
    ARTICLE_THREAD_LINKING_GUIDANCE,
    COMMUNITY_QUESTION_GUIDANCE,
    COMMUNITY_RULES,
    DEFAULT_FORUM_CATEGORIES,
    SEED_DISCUSSION_TOPICS,
)


def test_community_rules_cover_required_prohibited_content() -> None:
    rule_text = " ".join(rule["description"] for rule in COMMUNITY_RULES).lower()

    assert "investment advice" in rule_text
    assert "spam" in rule_text
    assert "abusive" in rule_text
    assert "unsafe tool claims" in rule_text


def test_default_categories_cover_required_forum_areas() -> None:
    slugs = {category["slug"] for category in DEFAULT_FORUM_CATEGORIES}

    assert "project-discussion" in slugs
    assert "strategy-research" in slugs
    assert "tools" in slugs
    assert "data-backtesting" in slugs
    assert "beginner-qna" in slugs
    assert "site-feedback" in slugs


def test_seed_discussion_topics_have_at_least_twenty_prepared_topics() -> None:
    assert len(SEED_DISCUSSION_TOPICS) >= 20
    assert all(topic["title"] and topic["category_slug"] and topic["prompt"] for topic in SEED_DISCUSSION_TOPICS)
    assert {topic["category_slug"] for topic in SEED_DISCUSSION_TOPICS}.issubset({category["slug"] for category in DEFAULT_FORUM_CATEGORIES})


def test_article_thread_linking_guidance_supports_associated_threads() -> None:
    assert ARTICLE_THREAD_LINKING_GUIDANCE["front_matter_field"] == "discussion_thread_id"
    assert "article" in ARTICLE_THREAD_LINKING_GUIDANCE["usage"].lower()
    assert "thread" in ARTICLE_THREAD_LINKING_GUIDANCE["usage"].lower()


def test_question_guidance_explains_strategy_and_tool_questions() -> None:
    guidance = " ".join(COMMUNITY_QUESTION_GUIDANCE).lower()

    assert "strategy" in guidance
    assert "tool" in guidance
    assert "data" in guidance
    assert "risk" in guidance
