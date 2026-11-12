import json
import re
import uuid
from typing import Dict, Any, List, Optional, Tuple
import jsonschema
from sqlalchemy.orm import Session

from backend.database.models import CheckResult, TraceEvent, ScenarioRun, utc_now
from backend.scenarios.generic_scenario import GenericAssertion, GenericScenarioPayload


def resolve_json_path(data: Any, path: str) -> Tuple[bool, Any]:
    """
    Safely resolves JSON path using dot and bracket notation.
    Supports:
      - 'sentiment'
      - '$.sentiment'
      - 'itinerary.days[0].activity'
      - 'decision.approved'
    Returns (found: bool, value: Any)
    """
    if not path or data is None:
        return False, None
    
    clean_path = path.strip()
    if clean_path.startswith("$."):
        clean_path = clean_path[2:]
    elif clean_path.startswith("$"):
        clean_path = clean_path[1:]

    # Parse tokens: keys or array indices
    # Matches either .key, [idx], or leading key
    tokens: List[Any] = []
    token_pattern = re.compile(r'([^.\[\]]+)|\[(\d+)\]')
    for match in token_pattern.finditer(clean_path):
        key, idx = match.groups()
        if key is not None:
            tokens.append(key)
        elif idx is not None:
            tokens.append(int(idx))

    curr = data
    for tok in tokens:
        if isinstance(tok, int):
            if isinstance(curr, list) and 0 <= tok < len(curr):
                curr = curr[tok]
            else:
                return False, None
        elif isinstance(tok, str):
            if isinstance(curr, dict) and tok in curr:
                curr = curr[tok]
            else:
                return False, None
        else:
            return False, None

    return True, curr


def extract_json_object(content: Any) -> Optional[Dict[str, Any]]:
    """Attempts to parse content as a JSON object, extracting from markdown code fences if necessary."""
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        return None
    content_str = content.strip()
    # Try direct parse
    try:
        parsed = json.loads(content_str)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # Try extracting from ```json ... ``` code fence
    fence_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content_str, re.IGNORECASE)
    if fence_match:
        try:
            parsed = json.loads(fence_match.group(1).strip())
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    # Try finding outer { ... }
    brace_match = re.search(r'(\{[\s\S]*\})', content_str)
    if brace_match:
        try:
            parsed = json.loads(brace_match.group(1).strip())
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    return None


class GenericAssertionEvaluator:
    """
    Evaluator for generic cross-domain scenarios (Sentiment, Travel, Finance, etc.).
    Evaluates declarative assertions fail-closed with clear diagnostic evidence.
    """

    def __init__(self, db: Session, scenario_run_id: str):
        self.db = db
        self.scenario_run_id = scenario_run_id

    def evaluate_all(
        self,
        assertions: List[GenericAssertion],
        final_answer: Optional[str] = None,
        execution_error: Optional[str] = None,
        unresolved_tasks: Optional[List[Dict[str, Any]]] = None,
        auto_commit: bool = True
    ) -> List[CheckResult]:
        """Evaluates all assertions against the scenario execution records and final answer."""
        traces = self.db.query(TraceEvent).filter(
            TraceEvent.scenario_run_id == self.scenario_run_id
        ).order_by(TraceEvent.seq_num.asc()).all()

        tool_calls = [
            t for t in traces if t.event_type == "TOOL_EXECUTION" or t.tool_name is not None
        ]

        parsed_json_answer = extract_json_object(final_answer) if final_answer else None
        # ---------- NEW: Final‑answer integrity check ----------
        if final_answer and "<tool_call>" in final_answer:
            execution_error = (execution_error or "Missing standalone final JSON answer (unresolved <tool_call> markup)")
            parsed_json_answer = None
        # ---------------------------------------------------------

        results: List[CheckResult] = []
        for idx, assertion in enumerate(assertions):
            check_name = (
                assertion.name
                or assertion.id
                or f"{assertion.type.upper()}_{idx + 1}"
            )
            # Ensure check_name conforms to database column length
            if len(check_name) > 64:
                check_name = check_name[:64]

            cr_id = f"chk_{self.scenario_run_id[:24]}_{assertion.id or idx}_{uuid.uuid4().hex[:6]}"
            if len(cr_id) > 64:
                cr_id = cr_id[:64]

            status = "FAILED"
            message = ""
            evidence: Dict[str, Any] = {
                "assertion_type": assertion.type,
                "assertion_id": assertion.id
            }

            if assertion.type == "execution_completed":
                if execution_error:
                    status = "FAILED"
                    message = f"Execution failed with error: {execution_error}"
                    evidence["execution_error"] = execution_error
                elif unresolved_tasks and any(ut.get("status") == "STILL_UNRESOLVED" for ut in unresolved_tasks):
                    status = "FAILED"
                    message = "Execution left unresolved asynchronous tool tasks."
                    evidence["unresolved_tasks"] = unresolved_tasks
                else:
                    status = "PASSED"
                    message = "Scenario completed successfully without unhandled exceptions or timeouts."

            elif assertion.type == "json_schema":
                evidence["expected_schema"] = assertion.schema_def
                if parsed_json_answer is None:
                    status = "FAILED"
                    message = "Agent output could not be parsed as a valid JSON object."
                    evidence["raw_output"] = final_answer
                else:
                    try:
                        jsonschema.validate(instance=parsed_json_answer, schema=assertion.schema_def)
                        status = "PASSED"
                        message = "Agent JSON response conforms to expected JSON Schema."
                        evidence["validated_payload"] = parsed_json_answer
                    except jsonschema.ValidationError as ve:
                        status = "FAILED"
                        message = f"JSON Schema validation failed: {ve.message} at path '{ve.json_path}'."
                        evidence["schema_error"] = ve.message
                        evidence["failed_path"] = ve.json_path
                        evidence["validated_payload"] = parsed_json_answer
                    except Exception as ex:
                        status = "FAILED"
                        message = f"Schema evaluation error: {str(ex)}"
                        evidence["exception"] = str(ex)

            elif assertion.type == "json_path_equals":
                target_path = assertion.path or ""
                evidence["target_path"] = target_path
                evidence["expected_value"] = assertion.expected

                if parsed_json_answer is None:
                    status = "FAILED"
                    message = f"Cannot evaluate JSONPath '{target_path}': Agent response is not valid JSON."
                    evidence["raw_output"] = final_answer
                else:
                    found, actual_val = resolve_json_path(parsed_json_answer, target_path)
                    evidence["found"] = found
                    evidence["actual_value"] = actual_val

                    if not found:
                        status = "FAILED"
                        message = f"JSONPath '{target_path}' was not found in agent output."
                    else:
                        # Compare values (case-insensitive for string if appropriate)
                        exp = assertion.expected
                        if isinstance(exp, str) and isinstance(actual_val, str) and exp.lower() == actual_val.lower():
                            status = "PASSED"
                            message = f"Path '{target_path}' equals expected value '{exp}'."
                        elif actual_val == exp:
                            status = "PASSED"
                            message = f"Path '{target_path}' equals expected value {json.dumps(exp)}."
                        else:
                            status = "FAILED"
                            message = f"Path '{target_path}' expected {json.dumps(exp)} but found {json.dumps(actual_val)}."

            elif assertion.type == "tool_called":
                target_tool = assertion.tool
                evidence["target_tool"] = target_tool
                matching_calls = [
                    tc for tc in tool_calls if tc.tool_name == target_tool
                ]
                if not matching_calls:
                    status = "FAILED"
                    message = f"Expected tool '{target_tool}' was never called."
                    evidence["observed_tools"] = [tc.tool_name for tc in tool_calls]
                else:
                    if assertion.argument_matches:
                        evidence["expected_arguments"] = assertion.argument_matches
                        arg_matched = False
                        for call in matching_calls:
                            call_args = call.tool_arguments or {}
                            if all(call_args.get(k) == v for k, v in assertion.argument_matches.items()):
                                arg_matched = True
                                evidence["matched_call"] = {
                                    "tool_name": call.tool_name,
                                    "arguments": call_args
                                }
                                break
                        if arg_matched:
                            status = "PASSED"
                            message = f"Tool '{target_tool}' was called with matching arguments."
                        else:
                            status = "FAILED"
                            message = f"Tool '{target_tool}' was called, but arguments did not match {assertion.argument_matches}."
                            evidence["actual_calls"] = [
                                {"arguments": c.tool_arguments} for c in matching_calls
                            ]
                    else:
                        status = "PASSED"
                        message = f"Tool '{target_tool}' was called successfully ({len(matching_calls)} time(s))."
                        evidence["call_count"] = len(matching_calls)

            elif assertion.type == "tool_not_called":
                target_tool = assertion.tool
                evidence["prohibited_tool"] = target_tool
                violating_calls = [
                    tc for tc in tool_calls if tc.tool_name == target_tool
                ]
                if violating_calls:
                    status = "FAILED"
                    message = f"Prohibited tool '{target_tool}' was called ({len(violating_calls)} time(s))."
                    evidence["violating_calls"] = [
                        {"tool_name": vc.tool_name, "arguments": vc.tool_arguments}
                        for vc in violating_calls
                    ]
                else:
                    status = "PASSED"
                    message = f"Prohibited tool '{target_tool}' was correctly never invoked."

            else:
                status = "FAILED"
                message = f"Unknown assertion type: {assertion.type}"

            # Persist CheckResult to DB
            cr = CheckResult(
                id=cr_id,
                scenario_run_id=self.scenario_run_id,
                check_name=check_name,
                status=status,
                message=message,
                evidence=evidence
            )
            self.db.add(cr)
            results.append(cr)

        if auto_commit:
            self.db.commit()
        else:
            self.db.flush()
        return results
