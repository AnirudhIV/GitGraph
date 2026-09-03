"""TypeScript/JavaScript source parsing for the function-level dependency
graph -- shells out to a small standalone Node.js helper
(backend/seed/ts-analyzer/extract.js) that uses ts-morph to get genuine
symbol/type resolution from the real TypeScript checker, since no viable
Python binding for the TS compiler exists. Same subprocess+timeout+custom-
exception pattern as mine_git.py's git subprocess calls.

The Node helper emits JSON matching the FunctionDef/CallSite/ImportEdge
contract exactly (see backend/seed/parse/__init__.py), so this module's
only job is invoking it and reading the result back -- no per-language
resolution logic lives here, only in extract.js.
"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from seed.parse import CallSite, FunctionDef, ImportEdge, ParseOperationError

_ANALYZER_DIR = Path(__file__).resolve().parent.parent / "ts-analyzer"
_EXTRACT_SCRIPT = _ANALYZER_DIR / "extract.js"


def parse(repo_path: str, ts_files: list[str], timeout: int = 300) -> tuple[list[FunctionDef], list[CallSite], list[ImportEdge]]:
    if shutil.which("node") is None:
        raise ParseOperationError(
            "Node.js is not installed (or not on PATH) -- required to parse TypeScript/JavaScript. "
            "Install Node.js and run `npm install` in backend/seed/ts-analyzer/."
        )
    if not (_ANALYZER_DIR / "node_modules").is_dir():
        raise ParseOperationError(
            "backend/seed/ts-analyzer/node_modules is missing -- run `npm install` in that directory once."
        )

    with tempfile.TemporaryDirectory() as tmp:
        files_list_path = Path(tmp) / "files.json"
        out_path = Path(tmp) / "out.json"
        files_list_path.write_text(json.dumps(ts_files), encoding="utf-8")

        try:
            result = subprocess.run(
                ["node", str(_EXTRACT_SCRIPT), repo_path, str(files_list_path), str(out_path)],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise ParseOperationError(f"TS/JS parsing timed out after {timeout}s.") from exc
        except subprocess.CalledProcessError as exc:
            detail = next((line for line in reversed((exc.stderr or "").splitlines()) if line.strip()), str(exc))
            raise ParseOperationError(f"TS/JS parsing failed: {detail}") from exc

        try:
            data = json.loads(out_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ParseOperationError(f"TS/JS parser produced no readable output: {exc}") from exc

    functions = [
        FunctionDef(
            id=f["id"],
            path=f["path"],
            name=f["name"],
            qualname=f["qualname"],
            language=f["language"],
            start_line=f["start_line"],
            end_line=f["end_line"],
            is_exported=f["is_exported"],
            is_method=f["is_method"],
            source=f.get("source", ""),
            complexity=f.get("complexity", 1),
        )
        for f in data.get("functions", [])
    ]
    calls = [
        CallSite(
            caller_id=c["caller_id"],
            callee_id=c["callee_id"],
            confidence=c["confidence"],
            resolution=c["resolution"],
            line=c["line"],
        )
        for c in data.get("calls", [])
    ]
    imports = [
        ImportEdge(from_path=i["from_path"], to_path=i["to_path"], imported_names=i["imported_names"])
        for i in data.get("imports", [])
    ]
    return functions, calls, imports
