from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_TESTS = PROJECT_ROOT / "backend" / "tests"
FRONTEND_PAGES = PROJECT_ROOT / "frontend" / "pages"


CORE_PATH_COVERAGE = {
    "visitor_homepage_and_blog": {
        "files": [
            FRONTEND_PAGES / "index.vue",
            FRONTEND_PAGES / "blog" / "index.vue",
            FRONTEND_PAGES / "blog" / "[slug].vue",
            BACKEND_TESTS / "test_public_blog.py",
        ],
        "tests": [
            "test_public_blog_list_returns_published_post_shape",
            "test_public_blog_detail_returns_content_and_increments_view_count",
        ],
    },
    "registration_verification_login": {
        "files": [
            BACKEND_TESTS / "test_registration_policy.py",
            BACKEND_TESTS / "test_email_verification_flow.py",
            BACKEND_TESTS / "test_login_session_flow.py",
        ],
        "tests": [
            "test_registration_accepts_email_password_and_does_not_leak_sensitive_data",
            "test_verify_email_accepts_valid_token_marks_user_verified_and_deletes_token",
            "test_login_returns_bearer_tokens_and_updates_last_login",
            "test_current_user_returns_identity_roles_and_verification_state",
        ],
    },
    "forum_posting_and_replying": {
        "files": [
            BACKEND_TESTS / "test_forum_thread_reply_creation.py",
        ],
        "tests": [
            "test_verified_user_can_create_sanitized_thread",
            "test_verified_user_can_create_sanitized_reply",
        ],
    },
    "tool_job_creation_and_viewing": {
        "files": [
            BACKEND_TESTS / "test_tool_job_creation_ownership.py",
            BACKEND_TESTS / "test_tool_result_display_history.py",
            FRONTEND_PAGES / "tools" / "jobs" / "index.vue",
            FRONTEND_PAGES / "tools" / "jobs" / "[job_id].vue",
        ],
        "tests": [
            "test_verified_user_can_create_owned_job_with_valid_manifest_parameters",
            "test_user_job_history_returns_only_current_users_safe_jobs",
            "test_user_job_detail_limits_result_output_and_filters_sensitive_information",
        ],
    },
    "admin_publishing_and_moderation": {
        "files": [
            BACKEND_TESTS / "test_admin_blog_workflow.py",
            BACKEND_TESTS / "test_forum_moderation_reporting.py",
        ],
        "tests": [
            "test_author_can_publish_and_unpublish_post",
            "test_only_moderator_can_pin_lock_feature_and_hide_threads",
            "test_moderator_can_list_and_handle_reports",
        ],
    },
}


def read_test_sources() -> str:
    return "\n".join(path.read_text() for path in BACKEND_TESTS.glob("test_*.py"))


def test_story_7_1_core_path_files_exist() -> None:
    missing = []
    for coverage in CORE_PATH_COVERAGE.values():
        missing.extend(str(path.relative_to(PROJECT_ROOT)) for path in coverage["files"] if not path.exists())

    assert missing == []


def test_story_7_1_acceptance_criteria_have_named_automated_coverage() -> None:
    sources = read_test_sources()
    missing = []
    for criterion, coverage in CORE_PATH_COVERAGE.items():
        for test_name in coverage["tests"]:
            if f"def {test_name}" not in sources and f"async def {test_name}" not in sources:
                missing.append(f"{criterion}:{test_name}")

    assert missing == []


def test_story_7_1_coverage_maps_all_acceptance_criteria() -> None:
    assert set(CORE_PATH_COVERAGE) == {
        "visitor_homepage_and_blog",
        "registration_verification_login",
        "forum_posting_and_replying",
        "tool_job_creation_and_viewing",
        "admin_publishing_and_moderation",
    }
