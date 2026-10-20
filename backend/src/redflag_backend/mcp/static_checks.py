"""Static checks on an MCP tool's description and input schema.

They look for known bad patterns with plain rules, no model. A tool with no findings is not
proven safe: the checks only know the patterns listed here, and say what they saw, never more.
"""

import json
import re
from dataclasses import dataclass
from typing import Any

from redflag_backend.targets.mcp_target import McpTool

LONG_DESCRIPTION = 2000


@dataclass(frozen=True)
class Family:
    title: str
    risk: str
    rule: str
    fix: str


FAMILIES: dict[str, Family] = {
    "hidden_instructions": Family(
        "Tool descriptions: hidden instructions",
        "LLM01",
        "A tool's description is read by the AI model. It must describe the tool and must not "
        "carry instructions to the model, least of all ones hidden from the user.",
        "Keep descriptions to what the tool does. Remove any instruction aimed at the model.",
    ),
    "hidden_characters": Family(
        "Tool descriptions: invisible characters",
        "LLM01",
        "Text the model reads must be text the user can see. Invisible or direction-changing "
        "characters can hide instructions.",
        "Remove invisible and direction-changing characters from names, descriptions and schemas.",
    ),
    "sensitive_wording": Family(
        "Tool descriptions: credentials and sending data out",
        "LLM02",
        "A tool's description must not point at credential files or tell the model to send data "
        "to an outside address.",
        "Remove references to credential files and to outside addresses from the description.",
    ),
    "broad_parameters": Family(
        "Tool inputs: open-ended parameters",
        "LLM06",
        "A tool's parameters should be as narrow as the job: a fixed list, a pattern or a length "
        "limit, not free text that reaches files, commands or queries.",
        "Give each text parameter a list of allowed values, a pattern or a maximum length, and "
        "check it again on the server.",
    ),
}

HIDDEN_INSTRUCTIONS = [
    r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|rules|messages)",
    r"do not (tell|mention|inform|reveal|show)\b.{0,40}\buser",
    r"don't (tell|mention|inform)\b.{0,40}\buser",
    r"<\s*(important|system|instructions?|secret)\s*>",
    r"\[\s*system\s*\]",
    r"before (using|calling|running) this tool",
    r"you must (first |always )?(read|send|call|include|pass|ignore)",
]
CREDENTIAL_FILES = (
    r"\.ssh\b|id_rsa|\.env\b|/etc/passwd|\.aws/credentials|credentials\.json|private key"
)
SEND_OUT = r"\bsend\w*\b.{0,80}(https?://|\bto (me|us|the server|an? (external|remote)))"
SEND_OUT_ALT = r"\b(upload|post|forward|transmit|exfiltrate)\w*\b.{0,80}https?://"

PATH_NAMES = {"path", "file", "filename", "filepath", "dir", "directory", "folder"}
RISKY_NAMES = {"command", "cmd", "sql", "script", "shell", "code", "expression"}
OPEN_NAMES = {"url", "query"}

# Characters that show nothing or change the order text is shown in. U+200D (joiner) is left
# alone because ordinary emoji and some scripts use it.
HIDDEN_RANGES: list[tuple[int, int, str]] = [
    (0x200B, 0x200C, "zero-width"),
    (0x2060, 0x2060, "zero-width"),
    (0xFEFF, 0xFEFF, "zero-width"),
    (0x200E, 0x200F, "direction-changing"),
    (0x202A, 0x202E, "direction-changing"),
    (0x2066, 0x2069, "direction-changing"),
    (0x2061, 0x2064, "invisible-operator"),
    (0xE0000, 0xE007F, "tag"),
]


@dataclass(frozen=True)
class Finding:
    family: str
    severity: str
    evidence: str
    fix: str


def _finding(family: str, severity: str, evidence: str) -> Finding:
    return Finding(family, severity, evidence, FAMILIES[family].fix)


def _quote(text: str, start: int, end: int) -> str:
    left, right = max(0, start - 60), min(len(text), end + 60)
    return ("…" if left else "") + text[left:right].strip() + ("…" if right < len(text) else "")


def _texts(tool: McpTool) -> str:
    return "\n".join(
        [tool.name, tool.description, json.dumps(tool.input_schema, ensure_ascii=False)]
    )


def _descriptions(tool: McpTool) -> list[str]:
    found = [tool.description]

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("description"), str):
                found.append(node["description"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(tool.input_schema)
    return found


def _hidden_instructions(tool: McpTool) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[str] = set()
    for text in _descriptions(tool):
        for pattern in HIDDEN_INSTRUCTIONS:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match and pattern not in seen:
                seen.add(pattern)
                findings.append(
                    _finding(
                        "hidden_instructions",
                        "critical",
                        f"The description contains wording aimed at the model: "
                        f"“{_quote(text, match.start(), match.end())}”",
                    )
                )
    if len(tool.description) > LONG_DESCRIPTION:
        findings.append(
            _finding(
                "hidden_instructions",
                "medium",
                f"The description is {len(tool.description)} characters long, long enough to "
                "hide instructions in.",
            )
        )
    return findings


def _hidden_characters(tool: McpTool) -> list[Finding]:
    found: dict[str, set[str]] = {}
    for char in _texts(tool):
        code = ord(char)
        for low, high, label in HIDDEN_RANGES:
            if low <= code <= high:
                found.setdefault(label, set()).add(f"U+{code:04X}")
    if not found:
        return []
    parts = [f"{label} ({', '.join(sorted(codes))})" for label, codes in sorted(found.items())]
    return [
        _finding(
            "hidden_characters",
            "high",
            "The name, description or schema contains invisible characters: " + "; ".join(parts),
        )
    ]


def _sensitive_wording(tool: McpTool) -> list[Finding]:
    findings: list[Finding] = []
    for text in _descriptions(tool):
        send = re.search(SEND_OUT, text, re.IGNORECASE | re.DOTALL) or re.search(
            SEND_OUT_ALT, text, re.IGNORECASE | re.DOTALL
        )
        if send:
            findings.append(
                _finding(
                    "sensitive_wording",
                    "critical",
                    f"The description tells the model to send something out: "
                    f"“{_quote(text, send.start(), send.end())}”",
                )
            )
        creds = re.search(CREDENTIAL_FILES, text, re.IGNORECASE)
        if creds:
            findings.append(
                _finding(
                    "sensitive_wording",
                    "high",
                    f"The description refers to a credential or secret file: "
                    f"“{_quote(text, creds.start(), creds.end())}”",
                )
            )
    return findings


def _broad_parameters(tool: McpTool) -> list[Finding]:
    schema = tool.input_schema
    if not schema:
        return [_finding("broad_parameters", "medium", "The tool declares no input schema.")]
    findings: list[Finding] = []
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    if schema.get("additionalProperties") is True:
        findings.append(
            _finding(
                "broad_parameters", "medium", "The tool accepts extra parameters it does not list."
            )
        )
    for name, prop in (properties or {}).items():
        if not isinstance(prop, dict) or prop.get("type") != "string":
            continue
        if any(key in prop for key in ("enum", "const", "pattern", "maxLength")):
            continue
        lowered = name.lower()
        if lowered in RISKY_NAMES:
            severity = "high"
        elif lowered in PATH_NAMES or lowered in OPEN_NAMES:
            severity = "medium"
        else:
            continue
        findings.append(
            _finding(
                "broad_parameters",
                severity,
                f"The parameter “{name}” takes any text, with no list, pattern or length limit.",
            )
        )
    return findings


def check_tool(tool: McpTool) -> list[Finding]:
    return [
        *_hidden_instructions(tool),
        *_hidden_characters(tool),
        *_sensitive_wording(tool),
        *_broad_parameters(tool),
    ]
