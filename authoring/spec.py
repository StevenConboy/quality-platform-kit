"""Read an OpenAPI 3 document and describe one endpoint in a form a model can work from."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_REF_DEPTH = 4


@dataclass
class Operation:
    method: str
    path: str
    summary: str = ""
    description: str = ""
    parameters: list[dict[str, Any]] = field(default_factory=list)
    request_schema: dict[str, Any] | None = None
    responses: dict[str, dict[str, Any]] = field(default_factory=dict)


def load_spec(source: str) -> dict[str, Any]:
    """Load a spec from a file path or an http(s) URL."""
    if source.startswith(("http://", "https://")):
        import httpx2

        response = httpx2.get(source, timeout=30.0)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data
    text = Path(source).read_text(encoding="utf-8")
    loaded: dict[str, Any] = json.loads(text)
    return loaded


def resolve_refs(node: Any, spec: dict[str, Any], depth: int = 0) -> Any:
    """Inline `$ref` pointers so the model sees concrete schemas. Bounded depth guards
    against recursive schemas."""
    if depth > MAX_REF_DEPTH:
        return {"description": "(nested schema omitted)"}
    if isinstance(node, dict):
        if "$ref" in node:
            target = _follow(spec, node["$ref"])
            return resolve_refs(copy.deepcopy(target), spec, depth + 1)
        return {key: resolve_refs(value, spec, depth) for key, value in node.items()}
    if isinstance(node, list):
        return [resolve_refs(item, spec, depth) for item in node]
    return node


def _follow(spec: dict[str, Any], ref: str) -> Any:
    if not ref.startswith("#/"):
        raise ValueError(f"only local $ref pointers are supported, got {ref!r}")
    node: Any = spec
    for part in ref[2:].split("/"):
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def extract_operations(spec: dict[str, Any], path: str) -> list[Operation]:
    paths = spec.get("paths", {})
    if path not in paths:
        known = ", ".join(sorted(paths)) or "(none)"
        raise KeyError(f"endpoint {path!r} not in spec; known paths: {known}")
    operations: list[Operation] = []
    for method, raw in paths[path].items():
        if method.lower() not in ("get", "post", "put", "patch", "delete"):
            continue
        body = raw.get("requestBody", {}).get("content", {}).get("application/json", {})
        responses: dict[str, dict[str, Any]] = {}
        for code, response in raw.get("responses", {}).items():
            content = response.get("content", {}).get("application/json", {})
            responses[str(code)] = {
                "description": response.get("description", ""),
                "schema": resolve_refs(content.get("schema"), spec) if content else None,
            }
        operations.append(
            Operation(
                method=method.upper(),
                path=path,
                summary=raw.get("summary", ""),
                description=raw.get("description", ""),
                parameters=[resolve_refs(p, spec) for p in raw.get("parameters", [])],
                request_schema=resolve_refs(body.get("schema"), spec) if body else None,
                responses=responses,
            )
        )
    return operations


def render_operations(operations: list[Operation]) -> str:
    """Compact Markdown the prompt embeds. JSON for schemas keeps it unambiguous."""
    parts: list[str] = []
    for op in operations:
        parts.append(f"### {op.method} {op.path}")
        if op.summary:
            parts.append(op.summary)
        if op.description:
            parts.append(op.description)
        if op.parameters:
            parts.append("Parameters:")
            parts.append("```json\n" + json.dumps(op.parameters, indent=2) + "\n```")
        if op.request_schema:
            parts.append("Request body (application/json):")
            parts.append("```json\n" + json.dumps(op.request_schema, indent=2) + "\n```")
        parts.append("Responses:")
        for code, response in op.responses.items():
            parts.append(f"- {code}: {response['description'] or '(no description)'}")
            if response["schema"]:
                parts.append("```json\n" + json.dumps(response["schema"], indent=2) + "\n```")
        parts.append("")
    return "\n".join(parts)
