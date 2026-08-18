from app.infrastructure.repository.secret_redactor import SecretKind, SecretRedactor


def test_redactor_masks_private_keys_and_preserves_line_ranges() -> None:
    original = (
        "before\n"
        "-----BEGIN PRIVATE KEY-----\n"
        "abc123\n"
        "-----END PRIVATE KEY-----\n"
        "after"
    )

    result = SecretRedactor().redact(relative_path="key.pem", text=original)

    assert "abc123" not in result.redacted_text
    assert result.redacted_text.count("\n") == original.count("\n")
    assert result.events[0].kind == SecretKind.PRIVATE_KEY
    assert result.events[0].line_start == 2
    assert result.events[0].line_end == 4
    assert "abc123" not in repr(result.events[0])
    assert original.splitlines()[2] == "abc123"


def test_redactor_masks_certificate_bodies() -> None:
    text = "-----BEGIN CERTIFICATE-----\nMIICsecret\n-----END CERTIFICATE-----\n"

    result = SecretRedactor().redact(relative_path="cert.pem", text=text)

    assert "MIICsecret" not in result.redacted_text
    assert result.events[0].kind == SecretKind.CERTIFICATE_BODY
    assert result.events[0].line_start == 1
    assert result.events[0].line_end == 3


def test_redactor_masks_bearer_tokens() -> None:
    text = "token = Bearer abcdefghijklmnopqrstuvwxyz0123456789"

    result = SecretRedactor().redact(relative_path="app.py", text=text)

    assert "abcdefghijklmnopqrstuvwxyz" not in result.redacted_text
    assert "[REDACTED:BEARER_TOKEN]" in result.redacted_text
    assert result.events[0].kind == SecretKind.BEARER_TOKEN


def test_redactor_masks_jwt() -> None:
    text = "jwt=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.signature"

    result = SecretRedactor().redact(relative_path="config.txt", text=text)

    assert "eyJhbGciOiJIUzI1NiJ9" not in result.redacted_text
    assert result.events[0].kind == SecretKind.JWT


def test_redactor_masks_password_assignments() -> None:
    text = "db_password = super-secret"

    result = SecretRedactor().redact(relative_path="settings.py", text=text)

    assert "super-secret" not in result.redacted_text
    assert "db_password = [REDACTED:PASSWORD]" == result.redacted_text
    assert result.events[0].kind == SecretKind.PASSWORD


def test_redactor_masks_connection_strings_without_masking_regular_urls() -> None:
    text = (
        "database_url=postgresql://user:secret@localhost/app\n"
        "homepage=https://example.com/docs"
    )

    result = SecretRedactor().redact(relative_path="settings.py", text=text)

    assert "user:secret" not in result.redacted_text
    assert "https://example.com/docs" in result.redacted_text
    assert result.events[0].kind == SecretKind.CONNECTION_STRING


def test_redactor_masks_client_secrets() -> None:
    text = "client_secret: very-secret-value"

    result = SecretRedactor().redact(relative_path="oauth.yml", text=text)

    assert "very-secret-value" not in result.redacted_text
    assert result.events[0].kind == SecretKind.CLIENT_SECRET


def test_redactor_masks_authorization_headers() -> None:
    text = "Authorization: Basic dXNlcjpzZWNyZXQ="

    result = SecretRedactor().redact(relative_path="http.txt", text=text)

    assert "dXNlcjpzZWNyZXQ" not in result.redacted_text
    assert result.redacted_text == "Authorization: [REDACTED:AUTHORIZATION_HEADER]"
    assert result.events[0].kind == SecretKind.AUTHORIZATION_HEADER


def test_redactor_masks_dotenv_content() -> None:
    text = "APP_ENV=local\nTOKEN=secret\n# comment\nEMPTY=\n"

    result = SecretRedactor().redact(relative_path=".env", text=text)

    assert "secret" not in result.redacted_text
    assert result.redacted_text == (
        "APP_ENV=[REDACTED:DOTENV_VALUE]\n"
        "TOKEN=[REDACTED:DOTENV_VALUE]\n"
        "# comment\n"
        "EMPTY=[REDACTED:DOTENV_VALUE]\n"
    )
    assert [event.kind for event in result.events] == [
        SecretKind.DOTENV_VALUE,
        SecretKind.DOTENV_VALUE,
        SecretKind.DOTENV_VALUE,
    ]
