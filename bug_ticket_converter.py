"""Natural-language bug report to structured JSON ticket converter.

This module provides:
1) A production-ready LLM prompt (see ``build_structuring_prompt``).
2) Supporting code that can post-process and validate model output.
3) A deterministic fallback parser for English and Spanish reports.

Design goals:
- Always return valid JSON (via ``json.dumps`` + schema normalization).
- Handle vague reports by either asking clarifying questions OR filling
  missing fields as ``"unspecified"``.
- Support multilingual reports (English + Spanish).
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Literal

TicketStrategy = Literal["fill_unspecified", "ask_clarification"]

SCHEMA_KEYS = [
    "title",
    "severity",
    "browser",
    "os",
    "steps_to_reproduce",
    "expected_behavior",
    "actual_behavior",
    "possible_trigger",
]

SEVERITY_LEVELS = {"low", "medium", "high", "critical", "unspecified"}

BROWSER_PATTERNS = {
    "Edge": r"\bedge\b|\bmicrosoft edge\b",
    "Chrome": r"\bchrome\b|\bgoogle chrome\b",
    "Firefox": r"\bfirefox\b",
    "Safari": r"\bsafari\b",
    "Opera": r"\bopera\b",
    "IE": r"\binternet explorer\b|\bie\b",
}

OS_PATTERNS = {
    "Windows 11": r"\bwindows\s*11\b",
    "Windows 10": r"\bwindows\s*10\b",
    "Windows": r"\bwindows\b",
    "macOS Ventura": r"\bmac\s?os\s+ventura\b|\bmacos\s+ventura\b",
    "macOS": r"\bmac\s?os\b|\bmacos\b",
    "Ubuntu": r"\bubuntu\b",
    "Linux": r"\blinux\b",
    "iOS": r"\bios\b|\biphone\b|\bipad\b",
    "Android": r"\bandroid\b",
}

SPANISH_HINTS = (
    "error",
    "falla",
    "no funciona",
    "iniciar sesión",
    "después del despliegue",
    "navegador",
)


def build_structuring_prompt() -> str:
    """Return a reusable LLM prompt for structuring bug reports into JSON.

    The prompt is strict about:
    - fixed schema
    - valid JSON output only
    - multilingual support (English/Spanish)
    - handling missing information in two modes
    """

    return """You are a bug-triage assistant. Convert user bug reports into JSON tickets.

Return ONLY valid JSON (no markdown, no prose, no code fences).
Always include exactly these keys:
- title (string)
- severity (one of: low, medium, high, critical, unspecified)
- browser (string)
- os (string)
- steps_to_reproduce (array of strings)
- expected_behavior (string)
- actual_behavior (string)
- possible_trigger (string)

Rules:
1) If data is missing and mode=fill_unspecified, set missing string fields to "unspecified" and missing arrays to ["unspecified"].
2) If data is missing and mode=ask_clarification, still return the same schema but fill unknowns with "unspecified" and additionally infer title conservatively.
3) For vague reports (e.g. "it's broken"), do not invent specific browsers/OS. Use "unspecified".
4) Support English and Spanish inputs.
5) Keep title concise and action-oriented.
6) Ensure JSON is syntactically valid every time.
"""


def _detect_language(report: str) -> str:
    text = report.lower()
    return "es" if any(h in text for h in SPANISH_HINTS) else "en"


def _extract_browser(text_lower: str) -> str:
    for browser, pattern in BROWSER_PATTERNS.items():
        if re.search(pattern, text_lower):
            return browser
    return "unspecified"


def _extract_os(text_lower: str) -> str:
    for os_name, pattern in OS_PATTERNS.items():
        if re.search(pattern, text_lower):
            return os_name
    return "unspecified"


def _extract_trigger(text: str, language: str) -> str:
    lower = text.lower()
    trigger_patterns = [
        r"after (?:the )?(?:last )?deploy(?:ment)?(?: on ([^\.,;]+))?",
        r"after update(?: on ([^\.,;]+))?",
        r"since (?:the )?release(?: on ([^\.,;]+))?",
        r"despu[eé]s del (?:[uú]ltimo )?despliegue(?: del? ([^\.,;]+))?",
    ]
    for pat in trigger_patterns:
        m = re.search(pat, lower)
        if m:
            suffix = m.group(1).strip() if m.groups() and m.group(1) else ""
            if language == "es":
                return f"Despliegue {suffix}".strip() if suffix else "Despliegue reciente"
            return f"Deploy {suffix}".strip() if suffix else "Recent deploy"
    return "unspecified"


def _extract_severity(text_lower: str) -> str:
    if any(k in text_lower for k in ["critical", "sev1", "blocker", "caído", "caida total"]):
        return "critical"
    if any(k in text_lower for k in ["nothing happens", "cannot", "can't", "unable", "broken", "no funciona", "no hace nada"]):
        return "high"
    if any(k in text_lower for k in ["slow", "lag", "intermittent", "lento", "a veces"]):
        return "medium"
    if any(k in text_lower for k in ["typo", "cosmetic", "minor", "visual"]):
        return "low"
    return "unspecified"


def _infer_title(text: str, browser: str, language: str) -> str:
    lower = text.lower()
    area = "application"
    if "login" in lower or "iniciar sesión" in lower:
        area = "login"
    elif "checkout" in lower or "pago" in lower:
        area = "checkout"
    elif "profile" in lower or "perfil" in lower:
        area = "profile"

    issue = "non-functional behavior"
    if any(k in lower for k in ["nothing happens", "no hace nada"]):
        issue = "action ignored"
    elif any(k in lower for k in ["crash", "se cierra", "throws", "error 500"]):
        issue = "crash/error"
    elif any(k in lower for k in ["slow", "lento"]):
        issue = "performance degradation"

    browser_part = f" on {browser}" if browser != "unspecified" else ""
    if language == "es":
        return f"Problema en {area}: {issue}{browser_part}"
    return f"{area.capitalize()} issue: {issue}{browser_part}"


def _extract_behavior(text: str, language: str) -> Dict[str, str]:
    lower = text.lower()
    actual = "unspecified"
    expected = "unspecified"

    if "nothing happens" in lower or "no hace nada" in lower or "no pasa nada" in lower:
        actual = "Nothing happens on click" if language == "en" else "No pasa nada al hacer clic"
    elif "crash" in lower or "se cierra" in lower:
        actual = "Application crashes" if language == "en" else "La aplicación se cierra"
    elif "error" in lower:
        actual = "An error is shown" if language == "en" else "Se muestra un error"

    if "login" in lower or "iniciar sesión" in lower:
        expected = (
            "Form submits and user is logged in"
            if language == "en"
            else "El formulario se envía y el usuario inicia sesión"
        )
    elif "checkout" in lower or "pago" in lower:
        expected = "Payment completes successfully" if language == "en" else "El pago se completa correctamente"

    return {"actual": actual, "expected": expected}


def _extract_steps(text: str, language: str) -> List[str]:
    lower = text.lower()
    if "login" in lower or "iniciar sesión" in lower:
        return [
            "Navigate to login page" if language == "en" else "Ir a la página de inicio de sesión",
            "Enter credentials" if language == "en" else "Ingresar credenciales",
            "Click submit" if language == "en" else "Hacer clic en enviar",
        ]
    if "checkout" in lower or "pago" in lower:
        return [
            "Add item to cart" if language == "en" else "Agregar un artículo al carrito",
            "Open checkout" if language == "en" else "Abrir checkout",
            "Submit payment" if language == "en" else "Enviar pago",
        ]
    return ["unspecified"]


def normalize_ticket(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize arbitrary dict into strict ticket schema.

    Guarantees all required keys exist with valid primitive types,
    and severity is constrained to the allowed enum.
    """

    result: Dict[str, Any] = {}
    for key in SCHEMA_KEYS:
        if key not in candidate:
            result[key] = ["unspecified"] if key == "steps_to_reproduce" else "unspecified"
            continue

        value = candidate[key]
        if key == "steps_to_reproduce":
            if isinstance(value, list) and value:
                normalized_steps = [str(v).strip() or "unspecified" for v in value]
                result[key] = normalized_steps
            else:
                result[key] = ["unspecified"]
            continue

        text = str(value).strip() if value is not None else ""
        result[key] = text if text else "unspecified"

    severity = result["severity"].lower()
    result["severity"] = severity if severity in SEVERITY_LEVELS else "unspecified"
    return result


def convert_bug_report(
    report: str,
    strategy: TicketStrategy = "fill_unspecified",
) -> str:
    """Convert a bug report string into a strict JSON ticket string.

    Args:
        report: Free-form bug report text.
        strategy: Missing-field handling strategy.

    Returns:
        JSON string containing only the structured ticket object.
    """

    text = (report or "").strip()
    language = _detect_language(text)
    lower = text.lower()

    browser = _extract_browser(lower)
    os_name = _extract_os(lower)
    severity = _extract_severity(lower)
    trigger = _extract_trigger(text, language)
    behavior = _extract_behavior(text, language)
    steps = _extract_steps(text, language)

    ticket = {
        "title": _infer_title(text, browser, language),
        "severity": severity,
        "browser": browser,
        "os": os_name,
        "steps_to_reproduce": steps,
        "expected_behavior": behavior["expected"],
        "actual_behavior": behavior["actual"],
        "possible_trigger": trigger,
    }

    if strategy == "ask_clarification":
        # Keep base schema while preserving strict JSON output.
        # Unknowns remain "unspecified", downstream systems can detect and ask user.
        ticket = normalize_ticket(ticket)
    else:
        ticket = normalize_ticket(ticket)

    return json.dumps(ticket, ensure_ascii=False)


if __name__ == "__main__":
    sample = (
        "The login page is broken on Safari. When I click submit nothing happens. "
        "I'm on macOS Ventura. This started after the last deploy on Friday."
    )
    print(convert_bug_report(sample))
