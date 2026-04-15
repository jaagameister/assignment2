import json

from bug_ticket_converter import (
    build_structuring_prompt,
    convert_bug_report,
    normalize_ticket,
)


def parse(report: str, strategy: str = "fill_unspecified"):
    return json.loads(convert_bug_report(report, strategy=strategy))


def test_prompt_contains_strict_json_requirements():
    prompt = build_structuring_prompt()
    assert "Return ONLY valid JSON" in prompt
    assert "Support English and Spanish" in prompt


def test_example_input_maps_to_expected_core_fields():
    report = (
        "The login page is broken on Safari. When I click submit nothing happens. "
        "I'm on macOS Ventura. This started after the last deploy on Friday."
    )
    ticket = parse(report)
    assert ticket["browser"] == "Safari"
    assert ticket["os"] == "macOS Ventura"
    assert ticket["severity"] == "high"
    assert "login" in ticket["title"].lower()
    assert ticket["actual_behavior"] == "Nothing happens on click"


def test_vague_report_falls_back_to_unspecified():
    ticket = parse("it's broken")
    assert ticket["browser"] == "unspecified"
    assert ticket["os"] == "unspecified"
    assert ticket["steps_to_reproduce"] == ["unspecified"]


def test_spanish_report_supported():
    report = (
        "La página de iniciar sesión no funciona en Safari. "
        "No hace nada al hacer clic en enviar. Estoy en macOS Ventura. "
        "Empezó después del último despliegue del viernes."
    )
    ticket = parse(report)
    assert ticket["browser"] == "Safari"
    assert ticket["os"] == "macOS Ventura"
    assert ticket["actual_behavior"] == "No pasa nada al hacer clic"


def test_invalid_severity_is_normalized():
    ticket = normalize_ticket(
        {
            "title": "x",
            "severity": "urgent",
            "browser": "Chrome",
            "os": "Windows",
            "steps_to_reproduce": ["a"],
            "expected_behavior": "b",
            "actual_behavior": "c",
            "possible_trigger": "d",
        }
    )
    assert ticket["severity"] == "unspecified"


def test_empty_input_still_valid_json():
    ticket = parse("")
    assert set(ticket.keys()) == {
        "title",
        "severity",
        "browser",
        "os",
        "steps_to_reproduce",
        "expected_behavior",
        "actual_behavior",
        "possible_trigger",
    }


def test_checkout_steps_are_inferred():
    ticket = parse("Checkout is slow on Chrome during payment")
    assert ticket["browser"] == "Chrome"
    assert ticket["severity"] == "medium"
    assert len(ticket["steps_to_reproduce"]) == 3


def test_ask_clarification_strategy_still_emits_schema():
    ticket = parse("broken app", strategy="ask_clarification")
    assert ticket["browser"] == "unspecified"
    assert ticket["steps_to_reproduce"] == ["unspecified"]


def test_json_always_parseable_for_multiline_text():
    report = """Bug report:\n- Browser: Firefox\n- OS: Ubuntu\n- Issue: error shown"""
    raw = convert_bug_report(report)
    ticket = json.loads(raw)
    assert ticket["browser"] == "Firefox"
    assert ticket["os"] == "Ubuntu"


def test_infers_trigger_when_deploy_mentioned():
    ticket = parse("After the last deploy on Tuesday, login is broken")
    assert "deploy" in ticket["possible_trigger"].lower()


def test_handles_unicode_and_accents():
    ticket = parse("Error después del despliegue, no funciona en Android")
    assert ticket["os"] == "Android"


def test_steps_array_never_empty():
    ticket = normalize_ticket(
        {
            "title": "x",
            "severity": "low",
            "browser": "x",
            "os": "y",
            "steps_to_reproduce": [],
            "expected_behavior": "a",
            "actual_behavior": "b",
            "possible_trigger": "c",
        }
    )
    assert ticket["steps_to_reproduce"] == ["unspecified"]
