"""Strict output schema for the trusted architecture, weight, and testing tools."""


def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False}


INTEGER = {"type": "integer"}
BOOLEAN = {"type": "boolean"}
REASON = {"type": "string", "minLength": 1, "maxLength": 500}
UPDATE = obj({"layer": INTEGER, "row": INTEGER, "column": {"type": ["integer", "null"]},
              "value": {"type": "number"}})
CASE = obj({"inputs": {"type": "array", "items": {"type": "number"}, "minItems": 33, "maxItems": 33},
            "expected_action": {"type": ["integer", "null"]}})
ARGUMENTS = {
    "set_action_feedback": obj({"enabled": BOOLEAN, "reason": REASON}),
    "request_context": obj({"request": REASON, "reason": REASON}),
    "set_architecture": obj({"reason": REASON, "layers": {"type": "array", "minItems": 1, "maxItems": 8,
        "items": obj({"width": {"type": "integer", "minimum": 1, "maximum": 64},
                      "type": {"type": "string", "enum": ["dense", "recurrent"]},
                      "activation": {"type": "string", "enum": ["linear", "relu", "tanh"]}})}}),
    "edit_recurrent": obj({"reason": REASON, "updates": {"type": "array", "items": UPDATE, "maxItems": 418}}),
    "test_sequence": obj({"cases": {"type": "array", "items": CASE, "minItems": 1, "maxItems": 8}}),

    "info": obj({}),
    "read_steps": obj({"start": INTEGER, "count": INTEGER, "stride": INTEGER}),
    "inspect_step": obj({"step": INTEGER, "original": BOOLEAN}),
    "read_weights": obj({"layer": INTEGER, "row": INTEGER}),
    "edit_weights": obj({"reason": REASON, "zero_all": BOOLEAN,
                         "updates": {"type": "array", "items": UPDATE, "maxItems": 418}}),
    "test_inputs": obj({"cases": {"type": "array", "items": CASE, "minItems": 1, "maxItems": 8}}),
    "submit": obj({"reason": REASON}),
}
def reply_schema(tools=None):
    return obj({
        "note": {"type": "string", "maxLength": 300},
        "calls": {"type": "array", "minItems": 1, "maxItems": 8, "items": {
            "anyOf": [obj({"tool": {"type": "string", "enum": [name]}, "arguments": arguments})
                      for name, arguments in ARGUMENTS.items() if tools is None or name in tools]}},
    })


TOOL_REPLY_SCHEMA = reply_schema()
