from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class SecretKind(StrEnum):
    PRIVATE_KEY = "PRIVATE_KEY"
    BEARER_TOKEN = "BEARER_TOKEN"
    JWT = "JWT"
    PASSWORD = "PASSWORD"
    CONNECTION_STRING = "CONNECTION_STRING"
    CLIENT_SECRET = "CLIENT_SECRET"
    AUTHORIZATION_HEADER = "AUTHORIZATION_HEADER"
    DOTENV_VALUE = "DOTENV_VALUE"
    CERTIFICATE_BODY = "CERTIFICATE_BODY"


@dataclass(frozen=True)
class RedactionEvent:
    kind: SecretKind
    relative_path: str
    line_start: int
    line_end: int
    replacement: str


@dataclass(frozen=True)
class RedactionResult:
    redacted_text: str
    events: tuple[RedactionEvent, ...]


@dataclass(frozen=True)
class RedactionPattern:
    kind: SecretKind
    pattern: re.Pattern[str]
    replacement: str


PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)
CERTIFICATE_PATTERN = re.compile(
    r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
    re.DOTALL,
)
AUTHORIZATION_HEADER_PATTERN = re.compile(
    r"(?im)^(\s*authorization\s*[:=]\s*)(.+)$",
)
BEARER_PATTERN = re.compile(
    r"(?i)\bBearer\s+[A-Za-z0-9._~+/\-]+=*",
)
JWT_PATTERN = re.compile(
    r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b",
)
PASSWORD_PATTERN = re.compile(
    r"(?i)\b([A-Za-z0-9_.-]*(?:password|passwd|pwd)[A-Za-z0-9_.-]*)"
    r"(\s*[:=]\s*)(['\"]?)[^'\"\s,;]+(['\"]?)",
)
CLIENT_SECRET_PATTERN = re.compile(
    r"(?i)\b([A-Za-z0-9_.-]*(?:client[_-]?secret|secret_key)[A-Za-z0-9_.-]*)"
    r"(\s*[:=]\s*)(['\"]?)[^'\"\s,;]+(['\"]?)",
)
CONNECTION_STRING_PATTERN = re.compile(
    r"\b(?:postgresql|postgres|mysql|mariadb|mongodb(?:\+srv)?|redis|sqlserver)://"
    r"[^\s'\"<>]+:[^\s'\"<>]+@[^\s'\"<>]+",
    re.IGNORECASE,
)
DOTENV_ASSIGNMENT_PATTERN = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*\s*=\s*)(.*)$",
)


INLINE_PATTERNS = (
    RedactionPattern(
        kind=SecretKind.AUTHORIZATION_HEADER,
        pattern=AUTHORIZATION_HEADER_PATTERN,
        replacement=r"\1[REDACTED:AUTHORIZATION_HEADER]",
    ),
    RedactionPattern(
        kind=SecretKind.BEARER_TOKEN,
        pattern=BEARER_PATTERN,
        replacement="[REDACTED:BEARER_TOKEN]",
    ),
    RedactionPattern(
        kind=SecretKind.JWT,
        pattern=JWT_PATTERN,
        replacement="[REDACTED:JWT]",
    ),
    RedactionPattern(
        kind=SecretKind.PASSWORD,
        pattern=PASSWORD_PATTERN,
        replacement=r"\1\2\3[REDACTED:PASSWORD]\4",
    ),
    RedactionPattern(
        kind=SecretKind.CLIENT_SECRET,
        pattern=CLIENT_SECRET_PATTERN,
        replacement=r"\1\2\3[REDACTED:CLIENT_SECRET]\4",
    ),
    RedactionPattern(
        kind=SecretKind.CONNECTION_STRING,
        pattern=CONNECTION_STRING_PATTERN,
        replacement="[REDACTED:CONNECTION_STRING]",
    ),
)


class SecretRedactor:
    def redact(self, *, relative_path: str, text: str) -> RedactionResult:
        redacted_text = text
        events: list[RedactionEvent] = []
        redacted_text = self._redact_multiline_block(
            relative_path=relative_path,
            text=redacted_text,
            pattern=PRIVATE_KEY_PATTERN,
            kind=SecretKind.PRIVATE_KEY,
            events=events,
        )
        redacted_text = self._redact_multiline_block(
            relative_path=relative_path,
            text=redacted_text,
            pattern=CERTIFICATE_PATTERN,
            kind=SecretKind.CERTIFICATE_BODY,
            events=events,
        )
        if _is_dotenv_path(relative_path):
            redacted_text = self._redact_dotenv_values(
                relative_path=relative_path,
                text=redacted_text,
                events=events,
            )
        for redaction_pattern in INLINE_PATTERNS:
            redacted_text = self._redact_inline_pattern(
                relative_path=relative_path,
                text=redacted_text,
                redaction_pattern=redaction_pattern,
                events=events,
            )
        events.sort(key=lambda event: (event.line_start, event.line_end, event.kind.value))
        return RedactionResult(redacted_text=redacted_text, events=tuple(events))

    def _redact_multiline_block(
        self,
        *,
        relative_path: str,
        text: str,
        pattern: re.Pattern[str],
        kind: SecretKind,
        events: list[RedactionEvent],
    ) -> str:
        def replace(match: re.Match[str]) -> str:
            line_start, line_end = _line_range(text, match.start(), match.end())
            replacement = _line_preserving_block_replacement(match.group(0), kind)
            events.append(
                RedactionEvent(
                    kind=kind,
                    relative_path=relative_path,
                    line_start=line_start,
                    line_end=line_end,
                    replacement=f"[REDACTED:{kind.value}]",
                )
            )
            return replacement

        return pattern.sub(replace, text)

    def _redact_dotenv_values(
        self,
        *,
        relative_path: str,
        text: str,
        events: list[RedactionEvent],
    ) -> str:
        redacted_lines: list[str] = []
        for line_number, line in enumerate(text.splitlines(keepends=True), start=1):
            line_without_newline = line.rstrip("\r\n")
            newline = line[len(line_without_newline) :]
            stripped = line_without_newline.strip()
            if not stripped or stripped.startswith("#"):
                redacted_lines.append(line)
                continue
            match = DOTENV_ASSIGNMENT_PATTERN.match(line_without_newline)
            if match is None:
                redacted_lines.append(line)
                continue
            replacement = f"{match.group(1)}[REDACTED:DOTENV_VALUE]{newline}"
            events.append(
                RedactionEvent(
                    kind=SecretKind.DOTENV_VALUE,
                    relative_path=relative_path,
                    line_start=line_number,
                    line_end=line_number,
                    replacement="[REDACTED:DOTENV_VALUE]",
                )
            )
            redacted_lines.append(replacement)
        return "".join(redacted_lines)

    def _redact_inline_pattern(
        self,
        *,
        relative_path: str,
        text: str,
        redaction_pattern: RedactionPattern,
        events: list[RedactionEvent],
    ) -> str:
        def replace(match: re.Match[str]) -> str:
            line_start, line_end = _line_range(text, match.start(), match.end())
            events.append(
                RedactionEvent(
                    kind=redaction_pattern.kind,
                    relative_path=relative_path,
                    line_start=line_start,
                    line_end=line_end,
                    replacement=f"[REDACTED:{redaction_pattern.kind.value}]",
                )
            )
            return match.expand(redaction_pattern.replacement)

        return redaction_pattern.pattern.sub(replace, text)


def _line_range(text: str, start: int, end: int) -> tuple[int, int]:
    line_start = text.count("\n", 0, start) + 1
    line_end = text.count("\n", 0, max(start, end - 1)) + 1
    return line_start, line_end


def _line_preserving_block_replacement(block: str, kind: SecretKind) -> str:
    lines = block.splitlines(keepends=True)
    replacement_lines = []
    for line in lines:
        newline_length = len(line) - len(line.rstrip("\r\n"))
        newline = line[-newline_length:] if newline_length else ""
        replacement_lines.append(f"[REDACTED:{kind.value}]{newline}")
    return "".join(replacement_lines)


def _is_dotenv_path(relative_path: str) -> bool:
    name = relative_path.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    return name == ".env" or name.startswith(".env.")
