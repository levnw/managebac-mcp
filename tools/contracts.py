"""Common contracts, not a second dispatcher or a second source of truth."""
from pydantic import BaseModel, ConfigDict
from mcp.types import Tool, ToolAnnotations


class NoArguments(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


def definition(name, model, description, properties, required=None, *, title, invoking, invoked, meta=None):
    """One definition style for every tool: strict input, closed output, read-only hints.

    `description` says what the tool does and when to use it, in plain words; argument
    details live in each argument's description, and what to do about a problem is in
    the result that reports it. `invoking`/`invoked` are ChatGPT's short status lines
    (at most 64 characters).
    """
    if len(invoking) > 64 or len(invoked) > 64:
        raise ValueError(f'{name}: tool status text exceeds 64 characters')
    return Tool(name=name, title=title, description=description,
                inputSchema=model.model_json_schema(),
                outputSchema={'type': 'object', 'properties': properties,
                              'required': list(properties) if required is None else required,
                              'additionalProperties': False},
                annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                            idempotentHint=True, openWorldHint=True),
                _meta={'openai/toolInvocation/invoking': invoking, 'openai/toolInvocation/invoked': invoked, **(meta or {})})


STRING = {'type': 'string'}
