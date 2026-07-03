import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SourceRecord:
    title: str
    text: str
    source: str


def load_sources(input_path: Path) -> list[SourceRecord]:
    path = input_path.expanduser().resolve()
    if not path.exists():
        msg = f"Input path does not exist: {input_path}"
        raise FileNotFoundError(msg)

    if path.is_dir():
        return _load_directory(path)
    if path.suffix == ".txt":
        return _load_txt_file(path)
    if path.suffix == ".jsonl":
        return _load_jsonl_file(path)

    msg = f"Unsupported input format: {input_path} (expected .txt, directory, or .jsonl)"
    raise ValueError(msg)


def load_txt_sources(input_path: Path) -> list[SourceRecord]:
    path = input_path.expanduser().resolve()
    if not path.exists():
        msg = f"Source path does not exist: {input_path}"
        raise FileNotFoundError(msg)

    if path.is_dir():
        return _load_directory(path)
    if path.suffix == ".txt":
        return _load_txt_file(path)

    msg = "Only .txt files and directories are supported for this endpoint."
    raise ValueError(msg)


def _load_directory(directory: Path) -> list[SourceRecord]:
    txt_files = sorted(directory.glob("*.txt"))
    if not txt_files:
        msg = f"No .txt files found in directory: {directory}"
        raise ValueError(msg)
    records: list[SourceRecord] = []
    for txt_file in txt_files:
        records.extend(_load_txt_file(txt_file))
    return records


def _load_txt_file(path: Path) -> list[SourceRecord]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    return [
        SourceRecord(
            title=path.stem,
            text=text,
            source=str(path),
        )
    ]


def _load_jsonl_file(path: Path) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            msg = f"Malformed JSON on line {line_number} of {path}: {exc.msg}"
            raise ValueError(msg) from exc
        if not isinstance(data, dict):
            msg = f"Expected JSON object on line {line_number} of {path}"
            raise ValueError(msg)
        if "title" not in data or "text" not in data:
            msg = f"Missing required 'title' or 'text' on line {line_number} of {path}"
            raise ValueError(msg)
        text = str(data["text"]).strip()
        if not text:
            continue
        source = str(data.get("source", path))
        records.append(
            SourceRecord(
                title=str(data["title"]),
                text=text,
                source=source,
            )
        )
    return records
