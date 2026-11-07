"""Strict output schema for the seven trusted data tools."""


def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False}


INTEGER = {"type": "integer"}
BOOLEAN = {"type": "boolean"}
REASON = {"type": "string", "minLength": 1, "maxLength": 500}
UPDATE = obj({"layer": INTEGER, "row": INTEGER, "column": {"type": ["integer", "null"]},
              "value": {"type": "number"}})
CASE = obj({"inputs": {"type": "array", "items": {"type": "number"}, "minItems": 31, "maxItems": 31},
            "expected_action": {"type": ["integer", "null"]}})
ARGUMENTS = {
    "info": obj({}),
    "read_steps": obj({"start": INTEGER, "count": INTEGER, "stride": INTEGER}),
    "inspect_step": obj({"step": INTEGER, "original": BOOLEAN}),
    "read_weights": obj({"layer": INTEGER, "row": INTEGER}),
    "edit_weights": obj({"reason": REASON, "zero_all": BOOLEAN,
                         "updates": {"type": "array", "items": UPDATE, "maxItems": 418}}),
    "test_inputs": obj({"cases": {"type": "array", "items": CASE, "minItems": 1, "maxItems": 8}}),
    "submit": obj({"reason": REASON}),
}
TOOL_REPLY_SCHEMA = obj({
    "note": {"type": "string", "maxLength": 300},
    "calls": {"type": "array", "minItems": 1, "maxItems": 4, "items": {
        "anyOf": [obj({"tool": {"type": "string", "enum": [name]}, "arguments": arguments})
                  for name, arguments in ARGUMENTS.items()]}},
})
