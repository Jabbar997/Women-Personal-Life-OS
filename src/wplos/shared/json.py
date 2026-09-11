from pydantic import JsonValue

type JsonObject = dict[str, JsonValue]

__all__ = ["JsonObject", "JsonValue"]
