"""Conservative identity normalization for reserved usernames."""

import unicodedata


def normalize_reserved_username(username: str) -> str:
    """Normalize case, compatibility forms, accents, and trailing spaces.

    This is used only to protect the configured bootstrap administrator name.
    It deliberately errs on the side of rejecting a registration/bootstrap
    collision; it does not change the application's general username rules.
    """
    decomposed = unicodedata.normalize("NFKD", username.casefold().rstrip())
    return "".join(character for character in decomposed if not unicodedata.combining(character))
