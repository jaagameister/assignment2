# Bug Report → JSON Ticket Converter

This project includes:

- A **strict prompt** for an LLM to convert free-form bug reports into a fixed JSON schema.
- **Supporting Python code** to parse/normalize outputs and guarantee valid JSON.
- A **deterministic fallback converter** for English and Spanish.
- A test suite with **12 test cases** (including edge cases).

## Schema

```json
{
  "title": "string",
  "severity": "low|medium|high|critical|unspecified",
  "browser": "string",
  "os": "string",
  "steps_to_reproduce": ["string"],
  "expected_behavior": "string",
  "actual_behavior": "string",
  "possible_trigger": "string"
}
```

## Run

```bash
python bug_ticket_converter.py
```

## Run tests

```bash
pytest -q
```

## Notes on vague reports

For reports like `"it's broken"`, missing fields are filled with `"unspecified"`.

## Multi-language support

Current deterministic parsing supports:
- English
- Spanish

The prompt is also explicitly instructed to support both.
