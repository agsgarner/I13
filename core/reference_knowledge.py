import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    yaml = None


DEFAULT_REFERENCE_ROOTS = (
    "references/knowledge",
    "references/schemas",
)
SUPPORTED_EXTENSIONS = {".json", ".yaml", ".yml", ".md", ".markdown"}


@dataclass(frozen=True)
class ReferenceEntry:
    ref_id: str
    title: str
    schema: str
    content_type: str
    topologies: Tuple[str, ...] = field(default_factory=tuple)
    tags: Tuple[str, ...] = field(default_factory=tuple)
    summary: str = ""
    body: str = ""
    vendor: str = "generic"
    source_path: str = ""
    data: Dict[str, Any] = field(default_factory=dict)

    def to_summary(self, score: float = 0.0, matched_terms: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        payload = {
            "id": self.ref_id,
            "title": self.title,
            "schema": self.schema,
            "content_type": self.content_type,
            "topologies": list(self.topologies),
            "tags": list(self.tags),
            "summary": self.summary,
            "vendor": self.vendor,
            "source_path": self.source_path,
            "data": self.data,
        }
        if score:
            payload["score"] = round(float(score), 4)
        if matched_terms:
            payload["matched_terms"] = list(matched_terms)
        return payload

    def searchable_text(self) -> str:
        chunks = [
            self.ref_id,
            self.title,
            self.schema,
            self.content_type,
            self.summary,
            self.body,
            " ".join(self.topologies),
            " ".join(self.tags),
            self.vendor,
        ]
        if self.data:
            chunks.append(json.dumps(self.data, sort_keys=True))
        return "\n".join(str(item) for item in chunks if item)


class ReferenceCatalog:
    def __init__(
        self,
        entries: Optional[Sequence[ReferenceEntry]] = None,
        roots: Optional[Sequence[str]] = None,
        warnings: Optional[Sequence[str]] = None,
    ):
        self.entries = list(entries or [])
        self.roots = list(roots or [])
        self.warnings = list(warnings or [])

    @classmethod
    def from_paths(cls, paths: Sequence[str]) -> "ReferenceCatalog":
        entries: List[ReferenceEntry] = []
        warnings: List[str] = []
        normalized_roots = [str(Path(path)) for path in paths]
        for root in normalized_roots:
            root_path = Path(root)
            if not root_path.exists():
                warnings.append(f"Reference root not found: {root_path}")
                continue
            if root_path.is_file():
                candidate_files = [root_path]
            else:
                candidate_files = sorted(
                    path for path in root_path.rglob("*")
                    if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
                )
            for file_path in candidate_files:
                try:
                    entries.extend(_load_reference_file(file_path))
                except Exception as exc:
                    warnings.append(f"Failed to load {file_path}: {exc}")
        return cls(entries=entries, roots=normalized_roots, warnings=warnings)

    def summary(self) -> Dict[str, Any]:
        content_types = Counter(entry.content_type for entry in self.entries)
        schemas = Counter(entry.schema for entry in self.entries)
        vendors = Counter(entry.vendor for entry in self.entries)
        return {
            "roots": list(self.roots),
            "entry_count": len(self.entries),
            "content_types": dict(sorted(content_types.items())),
            "schemas": dict(sorted(schemas.items())),
            "vendors": dict(sorted(vendors.items())),
            "warnings": list(self.warnings),
        }

    def search(
        self,
        query: str = "",
        *,
        topologies: Optional[Sequence[str]] = None,
        schemas: Optional[Sequence[str]] = None,
        content_types: Optional[Sequence[str]] = None,
        vendor: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        filters = {
            "topologies": {item for item in (topologies or []) if item},
            "schemas": {item for item in (schemas or []) if item},
            "content_types": {item for item in (content_types or []) if item},
        }
        query_tokens = _tokenize(query)
        scored: List[Tuple[float, List[str], ReferenceEntry]] = []

        for entry in self.entries:
            if vendor and entry.vendor not in {vendor, "generic"}:
                continue
            if filters["schemas"] and entry.schema not in filters["schemas"]:
                continue
            if filters["content_types"] and entry.content_type not in filters["content_types"]:
                continue
            if filters["topologies"] and not (filters["topologies"] & set(entry.topologies)):
                continue

            score, matched_terms = _score_entry(entry, query_tokens, filters["topologies"])
            if score <= 0.0 and query_tokens:
                continue
            if score <= 0.0 and not query_tokens and not filters["topologies"]:
                continue
            scored.append((score, matched_terms, entry))

        scored.sort(key=lambda item: (-item[0], item[2].title.lower(), item[2].ref_id))
        return [entry.to_summary(score=score, matched_terms=matched) for score, matched, entry in scored[: max(1, int(limit))]]


@lru_cache(maxsize=8)
def load_reference_catalog(paths_key: Optional[Tuple[str, ...]] = None) -> ReferenceCatalog:
    paths = list(paths_key or resolve_reference_paths())
    return ReferenceCatalog.from_paths(paths)


def resolve_reference_paths(paths: Optional[Sequence[str]] = None) -> Tuple[str, ...]:
    if paths:
        return tuple(str(Path(path)) for path in paths)

    env_value = os.getenv("I13_REFERENCE_PATHS", "").strip()
    if env_value:
        separators = [segment.strip() for segment in re.split(r"[,:]", env_value) if segment.strip()]
        if separators:
            return tuple(str(Path(path)) for path in separators)

    return tuple(DEFAULT_REFERENCE_ROOTS)


def _load_reference_file(path: Path) -> List[ReferenceEntry]:
    suffix = path.suffix.lower()
    raw = path.read_text(encoding="utf-8")
    if suffix == ".json":
        payload = json.loads(raw)
        return _normalize_records(payload, path)
    if suffix in {".yaml", ".yml"}:
        if yaml is None:
            raise RuntimeError("PyYAML is required to load YAML references")
        payload = yaml.safe_load(raw)
        return _normalize_records(payload, path)
    if suffix in {".md", ".markdown"}:
        payload = _parse_markdown_document(raw, path)
        return _normalize_records(payload, path)
    return []


def _normalize_records(payload: Any, path: Path) -> List[ReferenceEntry]:
    if isinstance(payload, list):
        records = payload
        defaults: Dict[str, Any] = {}
    elif isinstance(payload, dict):
        for bundle_key in ("items", "entries", "references", "documents"):
            if isinstance(payload.get(bundle_key), list):
                defaults = {
                    key: value
                    for key, value in payload.items()
                    if key not in {"items", "entries", "references", "documents"}
                }
                records = payload.get(bundle_key) or []
                break
        else:
            records = [payload]
            defaults = {}
    else:
        records = [{"title": path.stem, "body": str(payload)}]
        defaults = {}

    entries: List[ReferenceEntry] = []
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            record = {"title": f"{path.stem}-{index}", "body": str(record)}
        merged = dict(defaults)
        merged.update(record)
        entries.append(_build_entry(merged, path, index=index))
    return entries


def _build_entry(record: Dict[str, Any], path: Path, index: int) -> ReferenceEntry:
    title = str(record.get("title") or record.get("name") or path.stem.replace("_", " ").title())
    schema = str(record.get("schema") or record.get("template_schema") or "generic_reference")
    content_type = str(record.get("content_type") or record.get("type") or schema)
    topologies = tuple(_as_list(record.get("topologies") or record.get("topology") or []))
    tags = tuple(_as_list(record.get("tags") or record.get("keywords") or []))
    summary = str(record.get("summary") or record.get("description") or "")
    body = str(record.get("body") or record.get("markdown") or record.get("notes") or "")
    vendor = str(record.get("vendor") or "generic")

    reserved = {
        "id", "ref_id", "title", "name", "schema", "template_schema", "content_type", "type",
        "topologies", "topology", "tags", "keywords", "summary", "description", "body", "markdown",
        "notes", "vendor", "data",
    }
    data = record.get("data") if isinstance(record.get("data"), dict) else {}
    extra = {key: value for key, value in record.items() if key not in reserved}
    if extra:
        merged_extra = dict(data)
        merged_extra.update(extra)
        data = merged_extra

    ref_id = str(record.get("id") or record.get("ref_id") or f"{path.stem}::{index}")
    return ReferenceEntry(
        ref_id=ref_id,
        title=title,
        schema=schema,
        content_type=content_type,
        topologies=topologies,
        tags=tags,
        summary=summary,
        body=body,
        vendor=vendor,
        source_path=str(path),
        data=data,
    )


def _parse_markdown_document(text: str, path: Path) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}
    body_lines: List[str] = []
    in_metadata = True
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if in_metadata:
            if not line.strip():
                in_metadata = False
                continue
            if line.lstrip().startswith("#"):
                in_metadata = False
                body_lines.append(line)
                continue
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[_normalize_metadata_key(key)] = _parse_metadata_value(key, value.strip())
                continue
            in_metadata = False
            body_lines.append(line)
            continue
        body_lines.append(line)

    body = "\n".join(body_lines).strip()
    if not metadata.get("title"):
        heading = next((line.lstrip("# ").strip() for line in body_lines if line.lstrip().startswith("#")), None)
        metadata["title"] = heading or path.stem.replace("_", " ").title()
    metadata.setdefault("schema", "markdown_reference")
    metadata.setdefault("content_type", metadata.get("schema", "markdown_reference"))
    metadata.setdefault("body", body)
    return metadata


def _normalize_metadata_key(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _parse_metadata_value(key: str, value: str) -> Any:
    normalized = _normalize_metadata_key(key)
    if normalized in {"topologies", "tags", "keywords"}:
        return [item.strip() for item in value.split(",") if item.strip()]
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    try:
        if "." in value or "e" in value.lower():
            return float(value)
        return int(value)
    except Exception:
        return value


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(value).strip()]


def _tokenize(text: str) -> List[str]:
    return [token for token in re.findall(r"[a-z0-9_]+", (text or "").lower()) if len(token) > 1]


def _score_entry(entry: ReferenceEntry, query_tokens: Sequence[str], topology_filters: Sequence[str]) -> Tuple[float, List[str]]:
    searchable = entry.searchable_text().lower()
    title_text = entry.title.lower()
    summary_text = entry.summary.lower()
    tags = {tag.lower() for tag in entry.tags}
    topologies = {item.lower() for item in entry.topologies}

    score = 0.0
    matched_terms: List[str] = []

    for topology in topology_filters:
        topo = topology.lower()
        if topo in topologies:
            score += 4.0
            matched_terms.append(f"topology:{topo}")

    for token in query_tokens:
        token_score = 0.0
        if token in topologies:
            token_score += 4.0
        if token in tags:
            token_score += 2.5
        if token in title_text:
            token_score += 3.0
        elif token in summary_text:
            token_score += 1.75
        elif token in searchable:
            token_score += 0.75
        if token_score > 0.0:
            score += token_score
            matched_terms.append(token)

    if not query_tokens and topology_filters and topologies.intersection({item.lower() for item in topology_filters}):
        score += 1.0

    return score, matched_terms[:12]
