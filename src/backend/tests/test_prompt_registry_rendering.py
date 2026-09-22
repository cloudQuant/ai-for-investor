from unittest.mock import MagicMock

import pytest

from app.models.prompt_template import PromptTemplate
from app.services.prompt_registry.registry import PromptRegistryService


def test_render_template_preserves_substitution_and_missing_variable_tracking() -> None:
    template = PromptTemplate(
        id="prompt-template-1",
        name="knowledge_qa",
        version="v1",
        content="Hello {{ name }}; optional={{ optional }}; required={{ required }}",
        variables=["name", "required"],
    )

    result = PromptRegistryService(MagicMock()).render_template(
        template,
        {"name": "Ada", "optional": None},
    )

    assert result.rendered_prompt == "Hello Ada; optional=; required="
    assert result.missing_variables == ["optional", "required"]


def test_render_template_rejects_non_string_persisted_content() -> None:
    template = PromptTemplate(
        id="prompt-template-2",
        name="knowledge_qa",
        version="v1",
        content=None,
        variables=[],
    )

    with pytest.raises(TypeError, match="Prompt template content must be a string"):
        PromptRegistryService(MagicMock()).render_template(template, {})
