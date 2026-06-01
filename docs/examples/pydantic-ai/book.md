# Team knowledge (compiled by crewlore)

## docs/version-policy.md

- **[decision]** Per docs/version-policy.md, the hard raise for the RunContext case is shippable as a point-release bug fix (not a major bump) because returning False on NameError is undocumented behavior and the affected code was already crashing at invocation. The non-RunContext NameError case warrants one DeprecationWarning cycle as good citizenship, not as a policy requirement.
  - *Do:* Do not gate this fix on a major version bump; cite the policy clause 'Bug fixes that may result in existing code breaking, provided that such code was relying on undocumented features/constructs/assumptions' when writing the PR description.
  - _anchor_ `version policy file`: "Bug fixes that may result in existing code breaking, provided that such code was relying on undocumented features/constructs/assumptions."

## pydantic_ai/durable_exec/temporal/

- **[procedure]** For irreversible actions where the Temporal cluster is in the threat model, the correct pattern is a two-phase external commit: the tool body submits a reservation against an external authoritative store, and a separate non-Temporal confirmation step triggered directly by the human approver converts the reservation to a commit. The Temporal activity then only queries external state and is idempotent regardless of event-history content.
  - *Do:* For irreversible actions (charge card, delete record) under Temporal, implement a two-phase external commit rather than relying on any flag the library manages.
  - _anchor_ `agent_message: what the right fix actually is`: "For genuinely irreversible actions (charge a card, delete a record), use a two-phase external commit: the tool body submits a reservation against an external authoritative store, and a separate, non-Temporal confirmation step — triggered by the human approver directly, not mediated by Temporal — converts the reservation to a commit."
- **[decision]** Any library-level security check that runs inside a Temporal activity — a hook, a tool-body DB lookup, an HMAC verify — produces an activity result that an attacker with event-history write access can forge. No library abstraction can close this gap.
  - *Do:* Do not add library-level approval verification hooks inside Temporal activities as a security control against event-history tampering; document the limitation instead.
  - _anchor_ `agent_message: why verify_approval fails`: "A check that runs inside a Temporal activity produces an activity result. An attacker with event-history write access can forge that result — replace a rejection with a success — before the workflow reads it."
  - _anchor_ `agent_message: does the library hook buy anything`: "there is no library-level mechanism that meaningfully hardens HITL approval against an attacker with Temporal event-history write access. Any check that runs inside an activity can be bypassed by forging the activity result."
- **[gotcha]** The threat model in issue #5536 (Temporal event-history write access) is effectively a full cluster compromise. The attacker can also forge LLM responses, tool return values, and signals — tool_call_approved forgery is the least interesting thing they can do.
  - *Do:* When evaluating security issues scoped to Temporal event-history write access, note that this is a full cluster compromise and scope the fix accordingly rather than patching individual fields.
  - _anchor_ `agent_message: what the right fix actually is`: "The security boundary the issue assumes ("privileged Temporal write access is in scope") is actually a full Temporal cluster compromise. At that point the attacker can forge LLM responses, tool return values, and workflow signals — not just one bool."

## pydantic_ai/durable_exec/temporal/, pydantic_ai/toolsets/approval_required.py

- **[decision]** Issue #5536 should be closed as wontfix with a documentation note. The narrow fix (drop tool_call_approved from the wire) silently breaks tool bodies that branch on it — a regression worse than the vulnerability. The HMAC fix can be reopened scoped to confused-deputy replay within a trusted cluster (a different, tractable problem) as a future v2 issue.
  - *Do:* Triage issue #5536 as wontfix; add docs on the Temporal trust boundary; open a separate v2 issue for HMAC scoped to confused-deputy replay within a trusted cluster.
  - _anchor_ `agent_message: the narrow fix`: "Dropping the field silently makes every tool body that branches on it see False after a legitimate approval — "dry-run when the user approved the real action" is a silent regression that is worse than the current vulnerability"
  - _anchor_ `agent_message: HMAC approach`: "The HMAC approach might still be worth doing in v2 if the threat model is narrowed to "replay of a legitimately-issued approval token to a different tool call or run" — i.e., protecting against confused-deputy attacks within a trusted Temporal cluster, not external tampering."

## pydantic_ai/durable_exec/temporal/_run_context.py, pydantic_ai/_run_context.py

- **[gotcha]** ctx.tool_call_approved on the Temporal wire is an artifact of workflow-side re-derivation from DeferredToolResults, not an authorization control. Nothing in the activity checks it for authorization; it only matters to tool bodies that branch on it for behavioral differences (e.g. dry-run vs. real action).
  - *Do:* Do not treat ctx.tool_call_approved in a TemporalRunContext as an integrity-protected authorization signal; treat it as informational state for tool-body branching only.
  - _anchor_ `agent_message: where the real vulnerability is`: "The actual exposure is narrower: tool bodies that branch on ctx.tool_call_approved — e.g., "if approved, charge the real card; else dry-run." That is a documented, public use case"
  - _anchor_ `agent_message: architecture facts`: "The re-derivation happens in the workflow before the activity, not inside the activity itself."

## pydantic_ai/toolsets/approval_required.py, pydantic_ai/durable_exec/temporal/_function_toolset.py

- **[gotcha]** ApprovalRequiredToolset.call_tool runs in the Temporal workflow, not inside the activity. Inside the activity, FunctionToolset.call_tool is invoked directly — the approval gate is never re-applied there.
  - *Do:* When tracing HITL approval flow under Temporal, check where in the toolset hierarchy the gate fires — it is workflow-side, before activity dispatch, not inside the activity.
  - _anchor_ `agent_message: architecture facts`: "ApprovalRequiredToolset.call_tool — in the workflow (checks ctx.tool_call_approved, raises ApprovalRequired if not approved, then delegates to inner toolset)"
  - _anchor_ `agent_message: architecture facts`: "Inside the activity: _call_tool_in_activity calls self.wrapped.call_tool = FunctionToolset.call_tool directly — ApprovalRequiredToolset is never invoked inside the activity"

## pydantic_ai_slim/pydantic_ai/_utils.py

- **[gotcha]** takes_run_context() treats None from get_first_param_type as False (line 577-578), conflating 'no annotated first param' with 'annotation present but unresolvable', causing a function that does take RunContext to be dispatched without ctx — crashing at invocation with a confusing missing-argument TypeError, not at registration.
  - *Do:* Do not treat None as a safe False default; distinguish resolution failure from genuine absence of annotation before returning False.
  - _anchor_ `takes_run_context lines 577-578`: "first_param_type = get_first_param_type(callable_obj)
    if first_param_type is None:
        return False"
- **[decision]** The recommended fix shape splits on whether the raw annotation string (inspectable before resolution) contains 'RunContext': if yes, raise immediately at registration (code was already crashing at invocation); if no, emit DeprecationWarning and return None for one release cycle. Also pass include_keys={first_param_name} to get_function_type_hints so a NameError on a later parameter cannot produce a misleading error about the first param.
  - *Do:* Implement the split-except fix with string-inspection heuristic and include_keys scoping; do not use a single broad except or a strict= opt-in flag.
  - _anchor_ `fix shape description`: "The `include_keys={first_param_name}` refinement (already available on pydantic's `get_function_type_hints`, line 559 of `_typing_extra.py`) is important: without it, an unresolvable annotation on the *second* parameter would cause a `NameError` that gets blamed on the first-param check, producing a misleading message."
- **[gotcha]** The root trigger is from __future__ import annotations combined with a TYPE_CHECKING-only RunContext import: future annotations stringify all annotations, pydantic's get_function_type_hints evaluates those strings against runtime __globals__, and RunContext is absent at runtime, raising NameError.
  - *Do:* When reviewing user-supplied processor/tool functions, check whether from __future__ import annotations is present and RunContext is only imported under TYPE_CHECKING; if so, the takes_run_context check will silently misfire.
  - _anchor_ `root cause explanation`: "With `from __future__ import annotations`, every annotation is stored as a **string**. `my_processor.__annotations__` returns `{'ctx': 'RunContext', 'messages': 'list', ...}` — the string `"RunContext"`, not the class."

## pydantic_ai_slim/pydantic_ai/ui/ag_ui/_adapter.py

- **[decision]** The AG-UI adapter emits exactly one UserWarning per UserPromptPart content list (not per item) when any TextContent with non-None metadata is encountered during dump. This prevents log spam on long histories.
  - *Do:* Use a per-content-list boolean flag to emit at most one warning per UserPromptPart when dropping TextContent.metadata in the AG-UI adapter.
  - _anchor_ `agent micro-decisions`: "One warning per `dump_messages` call in AG-UI, not per item (to avoid log spam on long histories). Implemented by tracking a flag inside the call."
- **[gotcha]** The AG-UI adapter has the same TextContent.metadata loss shape as the Vercel adapter, but it is structurally unfixable via round-trip: ag_ui.core.TextInputContent has only 'type' and 'text' fields with no provider_metadata slot, so there is no wire channel to carry the metadata.
  - *Do:* Do not attempt to round-trip TextContent.metadata through the AG-UI adapter; the protocol has no wire slot. Emit a UserWarning on dump instead of silently dropping.
  - _anchor_ `agent analysis of ag_ui/_adapter.py:181-182`: "elif isinstance(item, TextContent):
        return TextInputContent(type='text', text=item.content)"

## pydantic_ai_slim/pydantic_ai/ui/vercel_ai/_adapter.py

- **[procedure]** When dumping TextContent.metadata with preserve mode, the value must be JSON-serializable to fit in provider_metadata (typed as dict[str, dict[str, JSONValue]]). The implementation probes serializability with json.dumps; on failure it falls back to None and emits a UserWarning rather than raising.
  - *Do:* When writing Any-typed metadata into a JSON wire format, always probe with json.dumps first and fall back gracefully with a warning on TypeError/ValueError rather than raising.
  - _anchor_ `agent micro-decisions`: "Non-JSON metadata → drop + warn (graceful), not raise."
- **[decision]** TextContent(content=..., metadata=None) round-trips as a bare str even with preserve mode. The load path only reconstructs TextContent when the metadata key is present and non-None in provider_metadata. This is documented behavior, not a bug.
  - *Do:* Do not wrap every TextUIPart in TextContent on load; only reconstruct TextContent when provider_metadata['pydantic_ai']['metadata'] is present. TextContent with metadata=None round-trips as str.
  - _anchor_ `agent micro-decisions`: "`TextContent(content=..., metadata=None)` round-trips as bare `str` (lossless behaviorally; lossy in type). Documented in the flag's docstring. Doing otherwise would wrap every plain text in `TextContent` on load, which is noisy."
- **[decision]** The fix for TextContent.metadata round-trip in the Vercel adapter is gated behind text_content_metadata: Literal['drop', 'preserve'] = 'drop' on VercelAIAdapter, defaulting to 'drop' to preserve existing behavior. Both dump and load are gated together; making dump unconditional would silently leak application metadata to the browser for all existing users.
  - *Do:* Gate both dump and load sides of TextContent.metadata round-trip behind the same flag. Do not make dump unconditional while load is gated, or vice versa.
  - _anchor_ `agent rationale for gating both sides`: "If I make dump unconditional, every existing Vercel-adapter user starts shipping their private app metadata to the browser tomorrow — a silent behavior change with a real leak risk.
- If I gate only load, the asymmetry is worse: data still leaks on dump, just gets discarded on the way back."
- **[gotcha]** TextContent.metadata is silently dropped on both the dump and load sides of the Vercel AI adapter round-trip. On dump (_convert_user_prompt_part line ~886), only item.content is copied into TextUIPart; item.metadata is discarded. On load (load_messages user branch ~line 274), TextUIPart is collapsed to a bare str with no metadata reconstruction.
  - *Do:* When tracing metadata loss in the Vercel adapter, check both _convert_user_prompt_part (dump) and the user-role TextUIPart branch in load_messages (load); both ends must be fixed together.
  - _anchor_ `agent analysis of _adapter.py:886-887`: "elif isinstance(item, TextContent):
                ui_parts.append(TextUIPart(text=item.content, state='done'))"
  - _anchor_ `agent analysis of _adapter.py:274-275`: "if isinstance(part, TextUIPart):
                        user_prompt_content.append(part.text)"
- **[style]** The flag name and style text_content_metadata: Literal['drop', 'preserve'] = 'drop' follows the existing manage_system_prompt: Literal['server', 'client'] = 'server' precedent on UIAdapter. New trust-axis flags on adapters should use string literals rather than booleans for legibility.
  - *Do:* Use Literal string enums (not bool) for new trust-axis flags on UIAdapter subclasses, following the manage_system_prompt pattern.
  - _anchor_ `agent flag design rationale`: "**Proposed flag:** `text_content_metadata: Literal['drop', 'preserve'] = 'drop'` on `VercelAIAdapter`, exposed through `from_request` / `dispatch_request`. Matches the style of the existing `manage_system_prompt: Literal['server', 'client']` field."

## tests/

- **[procedure]** When testing that a code path emits no warnings (as opposed to asserting warnings are present), use recwarn fixture and assert len(recwarn) == 0 rather than pytest.warns(), which requires at least one warning to be emitted.
  - *Do:* Use recwarn fixture (not pytest.warns) when asserting that no warnings are emitted.
  - _anchor_ `agent fix to test_ag_ui.py after first run`: "The "no warning" test needs `recwarn` instead of `pytest.warns` (which requires at least one warning). Fix that test"
