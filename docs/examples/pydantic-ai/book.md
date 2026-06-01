# Team knowledge (compiled by agent-lore)

## docs/version-policy.md

- **[decision]** The version policy (docs/version-policy.md) explicitly permits point-release bug fixes that break code relying on undocumented behavior. Returning False on NameError is undocumented — the takes_run_context docstring says False means 'doesn't take RunContext', not 'we couldn't tell'. The RunContext-annotation case requires no deprecation cycle because that code was already broken at invocation. The non-RunContext NameError case warrants one warning cycle as good citizenship, not as a policy requirement.
  - *Do:* Do not treat the takes_run_context NameError fix as requiring a major version bump or a full deprecation cycle for the RunContext case; ship the hard raise in a point release citing the undocumented-behavior clause of the version policy.
  - _anchor_ `docs/version-policy.md:7-8`: "Bug fixes that may result in existing code breaking, provided that such code was relying on undocumented features/constructs/assumptions."
  - _anchor_ `agent analysis`: "Returning `False` on `NameError` is undocumented — the `takes_run_context` docstring says `False` means \"doesn't take RunContext\", not \"we couldn't tell\". The RunContext case warrants no deprecation cycle (code was already broken). The non-RunContext case warrants one warning cycle as good citizenship, not as a policy requirement."

## pydantic_ai_slim/pydantic_ai/_utils.py

- **[gotcha]** When a user function uses `from __future__ import annotations` and imports RunContext only under `if TYPE_CHECKING:`, pydantic's get_function_type_hints raises NameError because the annotation is stored as the string 'RunContext' and evaluated against the module's runtime __globals__ where RunContext is absent. The broad except swallows this, takes_run_context() returns False, and the processor is called without ctx — crashing at invocation with a confusing missing-argument TypeError rather than at registration.
  - *Do:* When debugging mysterious 'missing 1 required positional argument' crashes in history processors or tool dispatch, check whether the function uses `from __future__ import annotations` with a TYPE_CHECKING-only RunContext import before assuming the call site is wrong.
  - _anchor_ `confirmed by bash reproduction`: "takes_run_context result: False"
  - _anchor_ `confirmed by bash reproduction`: "EXCEPTION type=NameError: name 'RunContext' is not defined"
- **[decision]** The recommended fix splits on whether the raw annotation string (inspectable before resolution via callable.__annotations__[first_param_name]) contains 'RunContext'. If yes: hard raise at registration with an actionable message, because the code was already crashing at invocation — no working code is broken. If no: emit DeprecationWarning and return None, giving users one release cycle.
  - *Do:* Implement the split-on-annotation-string approach: inspect `callable.__annotations__` before resolution to distinguish the RunContext case (hard raise) from the generic NameError case (DeprecationWarning + return None).
  - _anchor_ `agent analysis`: "You can inspect `callable.__annotations__[first_param_name]` *before* resolution (it's still a raw string). If it contains `\"RunContext\"`: the code was already crashing at invocation (`missing 1 required positional argument`), so a hard `TypeError` at registration is strictly better — no working code is broken."

## pydantic_ai_slim/pydantic_ai/ui/ag_ui/_adapter.py

- **[gotcha]** The same TextContent.metadata silent-drop bug exists in the AG-UI adapter, but with a harder constraint: ag_ui.core.TextInputContent has only 'type' and 'text' fields — there is no provider_metadata slot in the AG-UI wire protocol to stash metadata in.
  - *Do:* For AG-UI, do not attempt to round-trip TextContent.metadata through the wire; instead emit a UserWarning when metadata is dropped. A protocol extension would require upstream AG-UI changes.
  - _anchor_ `ag_ui/_adapter.py:181-182`: "elif isinstance(item, TextContent):
        return TextInputContent(type='text', text=item.content)"
  - _anchor_ `analysis`: "the wire type `ag_ui.core.TextInputContent` has *only* `type` and `text` fields (`ag_ui/core/types.py:76-80`). There is **no `provider_metadata` slot** to stash anything in — the AG-UI protocol itself has no channel for it."
- **[procedure]** For AG-UI, emit exactly one UserWarning per UserPromptPart content list (not per item) when any TextContent with non-None metadata is encountered during dump. Use a per-content-list boolean flag to suppress duplicate warnings and avoid log spam on long histories.
  - *Do:* In _dump_request_parts, set a _warned_text_content_metadata = False flag before iterating each UserPromptPart's content list; emit the warning once and set the flag to True on first TextContent with non-None metadata.
  - _anchor_ `design decision`: "One warning per `dump_messages` call in AG-UI, not per item (to avoid log spam on long histories). Implemented by tracking a flag inside the call."

## pydantic_ai_slim/pydantic_ai/ui/vercel_ai/_adapter.py

- **[gotcha]** TextContent.metadata is silently dropped on both the dump and load sides of the Vercel AI adapter round-trip (dump_messages → load_messages). The dump loss is in _convert_user_prompt_part at the TextContent branch; the load loss is in load_messages where TextUIPart in the user branch is collapsed to a bare str with no metadata reconstruction.
  - *Do:* When tracing metadata loss in the Vercel adapter, check _convert_user_prompt_part (dump side, TextContent branch) and load_messages user-role TextUIPart branch (load side) as the two loss sites.
  - _anchor_ `_adapter.py:886-887 (dump side)`: "elif isinstance(item, TextContent):
                ui_parts.append(TextUIPart(text=item.content, state='done'))"
  - _anchor_ `_adapter.py:274-275 (load side)`: "if isinstance(part, TextUIPart):
                        user_prompt_content.append(part.text)"
- **[style]** The manage_system_prompt: Literal['server', 'client'] field on VercelAIAdapter is the established precedent for trust-axis feature flags. New flags controlling client-trust boundaries should follow the same Literal pattern and default to the safe/restrictive value.
  - *Do:* Model new trust-axis flags on VercelAIAdapter after manage_system_prompt: use Literal with a safe default, expose through from_request and dispatch_request kwargs, and document the security rationale in the field docstring.
  - _anchor_ `design rationale`: "The project already has precedent for trust-axis flags on the Vercel adapter (`manage_system_prompt: 'server' | 'client'`, `allowed_file_url_schemes`). A flag lets safe applications opt into round-trip without imposing a footgun on everyone."
- **[gotcha]** The assistant branch of load_messages already round-trips id/provider_name/provider_details through provider_metadata['pydantic_ai'] for TextPart, ThinkingPart, and FilePart. The user branch had no analogous lookup — this asymmetry is where TextContent.metadata was lost.
  - *Do:* When adding new metadata round-trip support for user-role parts, check that both the user branch (load_messages) and _convert_user_prompt_part (dump side) are updated symmetrically.
  - _anchor_ `analysis`: "Note the asymmetry: the *assistant* branch at `:317-326` reads `part.provider_metadata` via `load_provider_metadata(...)` and threads `id`, `provider_name`, `provider_details` onto the resulting `TextPart`. The user branch has no analogous lookup, by design — `TextPart` carries provider-side fields, while `TextContent.metadata` is application-side `Any`."
- **[decision]** TextContent(content=..., metadata=None) round-trips as a bare str through both adapters even with text_content_metadata='preserve'. This is intentional — wrapping every plain text in TextContent on load would be noisy. Document this in the flag's docstring.
  - *Do:* On load, only reconstruct TextContent (instead of bare str) when provider_metadata['pydantic_ai']['metadata'] is present and non-None. TextContent with metadata=None round-trips as str.
  - _anchor_ `design decision`: "`TextContent(content=..., metadata=None)` round-trips as bare `str` (lossless behaviorally; lossy in type). Documented in the flag's docstring. Doing otherwise would wrap every plain text in `TextContent` on load, which is noisy."
