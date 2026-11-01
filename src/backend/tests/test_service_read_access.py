"""Focused trust-boundary tests for the HTTP service-read directory."""

from dataclasses import FrozenInstanceError

import pytest

from app.services.service_read.access import (
    ReadAccess,
    ServiceReadAccessDirectory,
    ServiceReadAccessError,
)


class _Worker:
    async def read_account(self, account_ref, *, currency=None):
        del account_ref, currency

    async def read_order(self, scope_ref, intent_id):
        del scope_ref, intent_id

    async def read_strategy_health(self, scope_ref):
        del scope_ref


def test_directory_copies_and_freezes_subject_and_selector_configuration():
    worker = _Worker()
    account_refs = {"account-a"}
    source_mapping = {"verified-subject": ReadAccess(worker, allow_account_refs=account_refs)}
    directory = ServiceReadAccessDirectory(source_mapping)
    access = source_mapping["verified-subject"]

    account_refs.add("account-b")
    source_mapping.clear()

    assert directory.resolve_account("verified-subject", "account-a") is access
    with pytest.raises(ServiceReadAccessError) as error:
        directory.resolve_account("verified-subject", "account-b")
    assert error.value.code == "ACCESS_DENIED"
    with pytest.raises(TypeError):
        directory._access_by_subject["another-subject"] = access
    with pytest.raises(FrozenInstanceError):
        access.worker = _Worker()


def test_unknown_subject_and_ungranted_selector_share_one_denial():
    directory = ServiceReadAccessDirectory(
        {"verified-subject": ReadAccess(_Worker(), allow_account_refs={"account-a"})}
    )

    errors = []
    for subject, account_ref in (
        ("missing-subject", "account-a"),
        ("verified-subject", "account-b"),
    ):
        with pytest.raises(ServiceReadAccessError) as error:
            directory.resolve_account(subject, account_ref)
        errors.append(error.value.code)

    assert errors == ["ACCESS_DENIED", "ACCESS_DENIED"]


def test_account_grant_cannot_be_reused_as_order_or_monitor_scope():
    directory = ServiceReadAccessDirectory(
        {
            "verified-subject": ReadAccess(
                _Worker(),
                allow_account_refs={"shared-looking-ref"},
                allow_order_scope_refs={"orders-a"},
                allow_monitor_scope_refs={"health-a"},
            )
        }
    )

    assert directory.resolve_account("verified-subject", "shared-looking-ref")
    for resolver in (directory.resolve_order_scope, directory.resolve_monitor_scope):
        with pytest.raises(ServiceReadAccessError) as error:
            resolver("verified-subject", "shared-looking-ref")
        assert error.value.code == "ACCESS_DENIED"


def test_one_worker_cannot_represent_multiple_subjects():
    worker = _Worker()
    with pytest.raises(ServiceReadAccessError) as error:
        ServiceReadAccessDirectory(
            {
                "subject-a": ReadAccess(worker),
                "subject-b": ReadAccess(worker),
            }
        )

    assert error.value.code == "WORKER_SHARED"


@pytest.mark.parametrize(
    ("subject", "account_ref", "code"),
    (
        ("", "account-a", "INVALID_SUBJECT"),
        ("subject-a", "*", "INVALID_SELECTORS"),
    ),
)
def test_wildcard_and_invalid_subjects_are_rejected(subject, account_ref, code):
    if account_ref == "*":
        with pytest.raises(ServiceReadAccessError) as error:
            ReadAccess(_Worker(), allow_account_refs={account_ref})
    else:
        with pytest.raises(ServiceReadAccessError) as error:
            ServiceReadAccessDirectory({subject: ReadAccess(_Worker())})

    assert error.value.code == code


def test_directory_rejects_a_synchronous_worker():
    class SyncWorker:
        def read_account(self, account_ref, *, currency=None):
            del account_ref, currency

        def read_order(self, scope_ref, intent_id):
            del scope_ref, intent_id

        def read_strategy_health(self, scope_ref):
            del scope_ref

    with pytest.raises(ServiceReadAccessError) as error:
        ReadAccess(SyncWorker())

    assert error.value.code == "INVALID_WORKER"
