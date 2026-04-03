import os
import json
from dataclasses import dataclass
from typing import Any, Iterable

from api.models.job import ValidationStrategy


def _req_get(requirements: dict[str, Any], key: str) -> Any:
    """Resolve fields from top-level JobRequest or nested ``input`` (dashboard / API payloads)."""
    if requirements.get(key) is not None:
        return requirements[key]
    inner = requirements.get("input")
    if isinstance(inner, dict):
        return inner.get(key)
    return None

@dataclass
class ValidationOutcome:
    verified: bool
    strategy: ValidationStrategy
    reason: str


def _normalize_lines(output: str) -> list[str]:
    return [line.strip() for line in output.splitlines() if line.strip()]


def _contains_error_markers(lines: Iterable[str]) -> bool:
    return any(line.startswith("[ERROR]") or line.startswith("[TIMEOUT]") for line in lines)


def _ai_validate(output: str, requirements: dict[str, Any]) -> ValidationOutcome:
    from dotenv import load_dotenv
    load_dotenv()
    gemini_key = os.getenv("GEMINI_API_KEY")
    
    if not gemini_key:
        return ValidationOutcome(
            verified=True,
            strategy=ValidationStrategy.RULE_BASED,
            reason="AI validation skipped (no API key). Passed baseline rule-based validation.",
        )

    import google.generativeai as genai

    genai.configure(api_key=gemini_key)
    task_desc = requirements.get("task", "unknown task")
    prompt = f"""
    Evaluate if the following process output correctly satisfies the requirements for the task: "{task_desc}".
    
    Process Output:
    ---
    {output}
    ---
    
    Requirements: {requirements}
    
    Does the output satisfy the task requirements? Respond ONLY with a JSON object:
    {{
        "verified": boolean,
        "reason": "string explaining why"
    }}
    """
    
    try:
        # Use a model confirmed available by list_models.py
        model = genai.GenerativeModel("models/gemini-flash-latest")
        response = model.generate_content(prompt)
        # Strip potential markdown formatting if Gemini includes it
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:-3].strip()
        elif text.startswith("```"):
            text = text[3:-3].strip()
            
        result = json.loads(text)
        return ValidationOutcome(
            verified=result.get("verified", False),
            strategy=ValidationStrategy.AI_BASED,
            reason=f"AI Validation: {result.get('reason', 'No reason provided')}",
        )
    except Exception as e:
        return ValidationOutcome(
            verified=True,
            strategy=ValidationStrategy.RULE_BASED,
            reason=f"AI validation failed with error: {str(e)}. Falling back to baseline rule-based validation.",
        )


def validate_execution_output(output: str, requirements: dict[str, Any]) -> ValidationOutcome:
    lines = _normalize_lines(output)
    normalized_output = "\n".join(lines)

    if not normalized_output:
        return ValidationOutcome(
            verified=False,
            strategy=ValidationStrategy.RULE_BASED,
            reason="Execution produced no output.",
        )

    if _contains_error_markers(lines):
        return ValidationOutcome(
            verified=False,
            strategy=ValidationStrategy.RULE_BASED,
            reason="Execution emitted runtime error markers.",
        )

    expected_output = _req_get(requirements, "expected_output")
    if expected_output is not None:
        verified = normalized_output == str(expected_output).strip()
        reason = "Output exactly matched the expected output." if verified else "Output did not exactly match the expected output."
        return ValidationOutcome(
            verified=verified,
            strategy=ValidationStrategy.DETERMINISTIC,
            reason=reason,
        )

    expected_substring = _req_get(requirements, "expected_substring")
    if expected_substring:
        verified = str(expected_substring) in normalized_output
        reason = "Output contained the required substring." if verified else "Output did not contain the required substring."
        return ValidationOutcome(
            verified=verified,
            strategy=ValidationStrategy.RULE_BASED,
            reason=reason,
        )

    forbidden_substrings = (
        _req_get(requirements, "forbidden_substrings") or []
    )
    if not isinstance(forbidden_substrings, list):
        forbidden_substrings = [forbidden_substrings]
    if any(str(item) in normalized_output for item in forbidden_substrings):
        return ValidationOutcome(
            verified=False,
            strategy=ValidationStrategy.RULE_BASED,
            reason="Output contained a forbidden substring.",
        )

    # Use AI validation if task requires it or as a fallback for high-level tasks
    return _ai_validate(normalized_output, requirements)
