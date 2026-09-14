import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup, Comment, NavigableString, Tag


class EvidenceError(RuntimeError):
    code = "EVIDENCE_READ_INVALID"
    retryable = False


@dataclass
class EvidenceNode:
    id: str
    tag: str
    attributes: dict[str, Any]
    value: Any
    parent: str | None
    children: list[str] = field(default_factory=list)
    text_length: int = 0
    link_length: int = 0
    preview: str = ""
    attributes_truncated: bool = False


class PageEvidence:
    """Read-only, snapshot-scoped DOM/JSON directory. No model-supplied selectors execute here."""

    def __init__(self, page_id: str, stage: str, source: str):
        self.page_id = page_id
        self.stage = stage
        self.digest = "sha256:" + hashlib.sha256(source.encode()).hexdigest()
        self.nodes: dict[str, EvidenceNode] = {}
        self._ranges: dict[str, list[tuple[int, int]]] = {}
        self._serialized: dict[str, str] = {}
        self._row_spans: dict[str, list[tuple[int, int]]] = {}
        try:
            root = json.loads(source)
            self.format = "json"
        except (ValueError, RecursionError):
            root = BeautifulSoup(source, "html.parser")
            for node in root.select("script, style, noscript, svg, canvas, template"):
                node.decompose()
            for comment in root.find_all(string=lambda value: isinstance(value, Comment)):
                comment.extract()
            self.format = "html"
        pending = [(root, None, None)]
        while pending:
            value, parent, key = pending.pop()
            if len(self.nodes) >= 100000:
                raise EvidenceError("EVIDENCE_INDEX_LIMIT")
            node_id = f"n{len(self.nodes)}"
            attrs: dict = {}
            truncated = False
            if self.format == "html":
                tag = value.name
                for name, attr in value.attrs.items():
                    if name in {"id", "class", "role", "name", "property", "http-equiv", "content", "href", "type"}:
                        text = " ".join(attr) if isinstance(attr, list) else str(attr)
                        attrs[name] = text[:400]
                        truncated |= len(text) > 400
                children = [(child, node_id, None) for child in value.children if isinstance(child, Tag)]
                direct_text = " ".join(str(child) for child in value.children if isinstance(child, NavigableString))
                compact_text = re.sub(r"\s+", " ", direct_text).strip()
                preview = compact_text[:100]
                text_length = len(compact_text)
            else:
                tag = "object" if isinstance(value, dict) else "array" if isinstance(value, list) else "value"
                attrs = {"key": str(key)[:100]} if key is not None else {}
                truncated = key is not None and len(str(key)) > 100
                entries = list(value.items()) if isinstance(value, dict) else list(enumerate(value)) if isinstance(value, list) else []
                children = [(child, node_id, child_key) for child_key, child in entries]
                preview = "" if entries else str(value)[:100]
                text_length = 0 if entries else len(str(value))
            node = EvidenceNode(node_id, tag, attrs, value, parent, text_length=text_length, preview=preview,
                                attributes_truncated=truncated)
            self.nodes[node_id] = node
            if parent:
                self.nodes[parent].children.append(node_id)
            pending.extend(reversed(children))
        for node in reversed(list(self.nodes.values())):
            node.link_length = node.text_length if node.tag == "a" else sum(self.nodes[c].link_length for c in node.children)
            if node.parent:
                self.nodes[node.parent].text_length += node.text_length
                if not self.nodes[node.parent].preview:
                    self.nodes[node.parent].preview = node.preview

    def _node(self, node_id: str) -> EvidenceNode:
        if not isinstance(node_id, str) or node_id not in self.nodes:
            raise EvidenceError("EVIDENCE_NODE_NOT_FOUND")
        return self.nodes[node_id]

    def describe(self, node_id: str) -> dict:
        node = self._node(node_id)
        return {
            "nodeId": node.id, "tag": node.tag, "attributes": node.attributes,
            "attributesTruncated": node.attributes_truncated, "childCount": len(node.children),
            "textLength": node.text_length, "linkDensity": round(node.link_length / max(1, node.text_length), 2),
            "preview": node.preview, "parentId": node.parent,
        }

    def index(self) -> dict:
        return {"pageId": self.page_id, "stage": self.stage, "format": self.format, "digest": self.digest,
                "nodeCount": len(self.nodes), "root": self.describe("n0")}

    def landmarks(self) -> list[dict]:
        semantic = {"main", "article", "section", "table", "ul", "ol", "array", "object"}
        candidates = []
        for node in self.nodes.values():
            if node.tag not in semantic | {"div", "p", "h1", "h2", "time"}:
                continue
            largest_child = max((self.nodes[child].text_length for child in node.children), default=0)
            # A chain of layout wrappers must not cost one model call per level.
            if node.tag not in semantic and largest_child >= max(1, node.text_length * 0.85):
                continue
            candidates.append(node)
        if self.stage == "list":
            candidates.sort(key=lambda n: (len(n.children) if n.link_length else 0, n.text_length), reverse=True)
        else:
            candidates.sort(key=lambda n: ((n.text_length - n.link_length) ** 2 / max(1, n.text_length),
                                          n.tag in {"main", "article"}), reverse=True)
        selected = [node.id for node in self.nodes.values() if node.tag == "head"][:1]
        selected.extend(node.id for node in candidates[:2] if node.id not in selected)
        metadata = [node.id for node in self.nodes.values() if node.tag == "title" or (
            node.tag == "meta" and any(word in " ".join(str(node.attributes.get(key, ""))
                for key in ("name", "property", "http-equiv")).lower() for word in ("title", "date", "time")))]
        selected.extend(node_id for node_id in metadata[:6] if node_id not in selected)
        selected.extend(node.id for node in candidates[2:8] if node.id not in selected)
        return [self.describe(node_id) for node_id in selected]

    def _offset(self, node_id: str, kind: str, cursor: str | None, total: int) -> int:
        if cursor is None:
            return 0
        prefix = f"{self.digest[7:23]}:{node_id}:{kind}:"
        if not isinstance(cursor, str) or not cursor.startswith(prefix):
            raise EvidenceError("EVIDENCE_CURSOR_INVALID")
        offset = cursor[len(prefix):]
        if not offset.isascii() or not offset.isdecimal() or len(offset) > 9 or int(offset) >= total:
            raise EvidenceError("EVIDENCE_CURSOR_INVALID")
        return int(offset)

    def _cursor(self, node_id: str, kind: str, offset: int, total: int) -> str | None:
        return f"{self.digest[7:23]}:{node_id}:{kind}:{offset}" if offset < total else None

    def expand(self, node_id: str, *, cursor: str | None = None, limit: int = 16) -> dict:
        node = self._node(node_id)
        if type(limit) is not int or not 1 <= limit <= 32:
            raise EvidenceError("EVIDENCE_LIMIT_INVALID")
        offset = self._offset(node_id, "children", cursor, len(node.children))
        end = min(len(node.children), offset + limit)
        return {"pageId": self.page_id, "nodeId": node.id, "digest": self.digest,
                "start": offset, "end": end,
                "nodes": [self.describe(child) for child in node.children[offset:end]],
                "complete": end == len(node.children), "nextCursor": self._cursor(node.id, "children", end, len(node.children))}

    def read(self, node_id: str, *, cursor: str | None = None, max_chars: int = 2400, record: bool = True) -> dict:
        node = self._node(node_id)
        if type(max_chars) is not int or not 128 <= max_chars <= 12000:
            raise EvidenceError("EVIDENCE_LIMIT_INVALID")
        if node_id not in self._serialized:
            self._serialized[node_id] = (str(node.value) if self.format == "html"
                                         else json.dumps(node.value, ensure_ascii=False, separators=(",", ":")))
        text = self._serialized[node_id]
        offset = self._offset(node_id, "content", cursor, len(text))
        end = min(len(text), offset + max_chars)
        # Do not split HTML tags. Text can span fragments, explicitly marked incomplete.
        if self.format == "html" and end < len(text):
            opening = text.rfind("<", offset, end)
            closing = text.rfind(">", offset, end)
            if opening > closing:
                end = opening
                if end == offset:
                    raise EvidenceError("EVIDENCE_TAG_EXCEEDS_READ_BUDGET")
        ancestors = []
        parent = node.parent
        table_headers = (" | ".join(th.get_text(" ", strip=True) for th in node.value.select("th"))
                         if node.tag == "table" else "")
        while parent:
            ancestor = self.nodes[parent]
            if ancestor.tag == "table" and not table_headers:
                table_headers = " | ".join(th.get_text(" ", strip=True) for th in ancestor.value.select("th"))
            attributes = {key: value[:120] for key, value in ancestor.attributes.items() if key in {"id", "class", "role", "key"}}
            ancestors.append({"nodeId": ancestor.id, "tag": ancestor.tag, "attributes": attributes,
                              "attributesTruncated": ancestor.attributes_truncated or any(
                                  len(value) > 120 for key, value in ancestor.attributes.items()
                                  if key in {"id", "class", "role", "key"})})
            parent = ancestor.parent
        row_range = None
        if self.format == "html" and node.tag in {"table", "tbody", "thead", "tfoot"}:
            if node_id not in self._row_spans:
                table = node.value if node.tag == "table" else node.value.find_parent("table")
                rows = [row for row in node.value.find_all("tr") if row.find_parent("table") is table]
                spans, position = [], 0
                for row in rows:
                    serialized = str(row)
                    start = text.find(serialized, position)
                    if start >= 0:
                        position = start + len(serialized)
                        spans.append((start, position))
                self._row_spans[node_id] = spans
            matching = [(i, start, stop) for i, (start, stop) in enumerate(self._row_spans[node_id])
                        if start < end and stop > offset]
            if matching:
                row_range = {"start": matching[0][0], "end": matching[-1][0] + 1,
                             "total": len(self._row_spans[node_id]),
                             "partialStart": offset > matching[0][1], "partialEnd": end < matching[-1][2]}
        if record:
            self._ranges.setdefault(node_id, []).append((offset, end))
        return {"pageId": self.page_id, "nodeId": node.id, "digest": self.digest, "format": self.format,
                "ancestors": list(reversed(ancestors[:16])), "ancestorsTruncated": len(ancestors) > 16,
                "tableHeaders": table_headers[:1000], "tableHeadersTruncated": len(table_headers) > 1000,
                "tableRowRange": row_range,
                "content": text[offset:end], "start": offset, "end": end, "totalChars": len(text),
                "complete": end == len(text), "nextCursor": self._cursor(node_id, "content", end, len(text))}

    def coverage(self) -> dict:
        read_chars = 0
        for ranges in self._ranges.values():
            end = 0
            for start, stop in sorted(ranges):
                read_chars += max(0, stop - max(start, end))
                end = max(end, stop)
        return {"pageId": self.page_id, "indexedNodes": len(self.nodes), "readNodes": len(self._ranges),
                "readFragmentChars": read_chars}
