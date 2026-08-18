from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DOC_PATH = ROOT / "docs" / "GIGACHAT_SMOKE_TEST.md"


def test_gigachat_smoke_doc_covers_required_manual_checks() -> None:
    content = DOC_PATH.read_text(encoding="utf-8")

    required_phrases = (
        "OAuth",
        "List Models",
        "Token Count",
        "Structured Response",
        "Invalid Schema Behavior",
        "413 Re-Chunk",
        "Rate Limit Behavior",
        "Token Refresh",
    )
    for phrase in required_phrases:
        assert phrase in content


def test_gigachat_smoke_doc_keeps_credentials_and_prompts_out_of_ci() -> None:
    content = DOC_PATH.read_text(encoding="utf-8")

    assert "must not run in CI" in content
    assert "CI must run only fake-provider automated tests" in content
    assert "GIGACHAT_CREDENTIALS" in content
    assert "Do not commit `.env`, access tokens, request bodies, raw prompts, or source fragments." in content
    assert "LOG_SOURCE_CONTENT=false" in content
    assert "raw provider payloads" in content


def test_readme_links_manual_gigachat_smoke_doc() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "docs/GIGACHAT_SMOKE_TEST.md" in readme
