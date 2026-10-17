from dataclasses import dataclass
from hashlib import sha256

from .config import BACKEND_ROOT
from .schemas import DocumentId


@dataclass(frozen=True)
class Document:
    id: DocumentId
    text: str
    sha256: str


def load_document(document_id: DocumentId) -> Document:
    # Only enum values can reach this file lookup; never accept a client path.
    document_id = DocumentId(document_id)
    content = (BACKEND_ROOT / "data" / "documents" / f"{document_id.value}.md").read_bytes()
    text = content.decode("utf-8")
    if len(text) > 8000:
        raise ValueError("资料超出本实验长度上限")
    return Document(document_id, text, sha256(content).hexdigest())
