"""Python source parsing for the function-level dependency graph.

Uses the stdlib `ast` module rather than tree-sitter: Python has no static
type checker built into either tool, so tree-sitter's one real advantage --
a single grammar API across languages -- doesn't pay for itself when this
is the only non-TS/JS language in scope, and `ast` avoids adding a native-
extension dependency (see the plan for the full reasoning).

Two passes:
  1. Per-file (_FileParse): collects this file's own function definitions
     (with CPython-style qualnames), raw call sites, and raw import
     statements.
  2. Repo-wide: builds a module-path index and a global function-name
     index, then resolves every raw call site against the ladder described
     in seed/parse/__init__.py's module docstring -- same-file first, then
     import-based cross-file, then a name-heuristic fallback that only
     fires when exactly one candidate matches anywhere in the repo.

Known accepted gap (see the plan): module resolution is inferred purely by
walking the repo's own file tree, since parsing runs against source only,
never an installed/importable environment. `src/`-layout remaps, PEP 420
namespace packages, and sys.path hacks won't resolve correctly -- ambiguous
or unresolvable imports are simply dropped rather than guessed.
"""
import ast
import posixpath
from dataclasses import dataclass, field

from seed.parse import CallSite, FunctionDef, ImportEdge


class _ComplexityVisitor(ast.NodeVisitor):
    """McCabe cyclomatic complexity: 1 (the function's base path) plus one
    per decision point in its body -- the same practical node-counting
    definition radon/mccabe/ESLint's complexity rule use, not the full
    control-flow-graph (edges - nodes + 2) derivation; the two coincide for
    structured code with no gotos, which is all Python can express anyway.

    Stops at a nested FunctionDef/AsyncFunctionDef: that nested function
    gets its own FunctionDef entry (see _visit_function) and its own
    complexity, so descending into it here would double-count its branches
    into the enclosing function's score.
    """

    def __init__(self) -> None:
        self.count = 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        pass  # nested def -- own complexity, don't descend

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        pass

    def visit_If(self, node: ast.If) -> None:
        self.count += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.count += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.count += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self.count += 1
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.count += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.count += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        # "a and b and c" has 2 extra branch points (short-circuit can exit
        # after either `a` or `b`), not 1 -- one per operator, not one per
        # BoolOp node.
        self.count += len(node.values) - 1
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        # The implicit `for` plus each `if` clause is its own branch point.
        self.count += 1 + len(node.ifs)
        self.generic_visit(node)

    def visit_match_case(self, node: ast.match_case) -> None:
        self.count += 1
        self.generic_visit(node)


def _cyclomatic_complexity(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    visitor = _ComplexityVisitor()
    visitor.generic_visit(node)  # visits node's children, not node itself
    return visitor.count


@dataclass
class _RawCall:
    enclosing_qualname: str | None
    kind: str  # "name" | "self_attr" | "name_attr"
    name: str
    base: str | None
    line: int


@dataclass
class _RawImport:
    kind: str  # "import" | "from"
    module: str | None
    level: int
    # (imported_name, local_binding_name) pairs -- for "import X" this is
    # [(X, X)] (or [(X, asname)]); for "from X import a, b as c" it's
    # [(a, a), (b, c)].
    names: list[tuple[str, str]]


@dataclass
class _FileParse:
    path: str
    functions: list[FunctionDef] = field(default_factory=list)
    name_to_ids: dict[str, list[str]] = field(default_factory=dict)
    raw_calls: list[_RawCall] = field(default_factory=list)
    raw_imports: list[_RawImport] = field(default_factory=list)


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: str, source: str):
        self.path = path
        self._lines = source.splitlines()
        self.scope_stack: list[str] = []
        self.in_class: list[bool] = []  # top of stack: are we directly inside a class body right now
        self.functions: list[FunctionDef] = []
        self.name_to_ids: dict[str, list[str]] = {}
        self.raw_calls: list[_RawCall] = []
        self.raw_imports: list[_RawImport] = []
        # Counts how many definitions share a qualname within this file, so
        # a genuine collision (most commonly @property getter/setter/
        # deleter trios sharing one name, or a conditionally-redefined
        # function) gets a distinct id instead of one definition silently
        # overwriting another's node at load time.
        self._qualname_counts: dict[str, int] = {}

    def _qualname(self, name: str) -> str:
        return ".".join([*self.scope_stack, name]) if self.scope_stack else name

    def _source_text(self, node: ast.FunctionDef | ast.AsyncFunctionDef, end_line: int) -> str:
        """Full text of a function's definition, decorators included.

        `ast.get_source_segment` alone would start at the `def` line --
        decorators are separate nodes with their own (earlier) line numbers
        in the ast module, not part of the FunctionDef's own span -- but a
        decorator like Flask's own @app.route(...) is usually the most
        useful line of context when actually reading a function, so this
        widens the range to the first decorator when any exist. Plain line
        slicing rather than get_source_segment for that widened range,
        since get_source_segment only accepts a single node's own bounds.
        """
        start_line = node.decorator_list[0].lineno if node.decorator_list else node.lineno
        return "\n".join(self._lines[start_line - 1 : end_line])

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope_stack.append(node.name)
        self.in_class.append(True)
        self.generic_visit(node)
        self.in_class.pop()
        self.scope_stack.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qualname = self._qualname(node.name)
        is_method = bool(self.in_class and self.in_class[-1])

        count = self._qualname_counts.get(qualname, 0) + 1
        self._qualname_counts[qualname] = count
        fn_id = f"{self.path}::{qualname}" if count == 1 else f"{self.path}::{qualname}#{count}"

        end_line = getattr(node, "end_lineno", node.lineno) or node.lineno
        self.functions.append(
            FunctionDef(
                id=fn_id,
                path=self.path,
                name=node.name,
                qualname=qualname,
                language="python",
                start_line=node.lineno,
                end_line=end_line,
                is_exported=not node.name.startswith("_"),
                is_method=is_method,
                source=self._source_text(node, end_line),
                complexity=_cyclomatic_complexity(node),
            )
        )
        # All definitions sharing a bare name are kept as candidates (not
        # "last wins") -- same-file call resolution below only trusts this
        # when exactly one candidate exists, so a genuine collision (e.g. a
        # property's getter and setter both named "debug") correctly falls
        # through to the heuristic/unresolved path rather than the wrong
        # one silently winning.
        self.name_to_ids.setdefault(node.name, []).append(fn_id)

        self.scope_stack.append(node.name)
        self.in_class.append(False)
        self.generic_visit(node)
        self.in_class.pop()
        self.scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Call(self, node: ast.Call) -> None:
        enclosing = ".".join(self.scope_stack) if self.scope_stack else None
        func = node.func
        if isinstance(func, ast.Name):
            self.raw_calls.append(_RawCall(enclosing, "name", func.id, None, node.lineno))
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            base = func.value.id
            if base in ("self", "cls"):
                self.raw_calls.append(_RawCall(enclosing, "self_attr", func.attr, None, node.lineno))
            else:
                self.raw_calls.append(_RawCall(enclosing, "name_attr", func.attr, base, node.lineno))
        # Anything more dynamic (chained calls, subscripts, computed attrs)
        # is not resolvable even heuristically -- skipped rather than
        # guessed, same philosophy as the rest of the resolution ladder.
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        names = [(alias.name, alias.asname or alias.name.split(".")[0]) for alias in node.names]
        self.raw_imports.append(_RawImport("import", None, 0, names))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        names = [(alias.name, alias.asname or alias.name) for alias in node.names]
        self.raw_imports.append(_RawImport("from", node.module, node.level or 0, names))


def _to_module_dotted(path: str) -> str:
    parts = path.split("/")
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1].rsplit(".", 1)[0]
    return ".".join(parts)


def _build_module_index(py_files: list[str]) -> dict[str, list[str]]:
    """dotted-suffix -> candidate file paths, indexing every file under
    every suffix of its own dotted path so `from app import db` resolves
    regardless of which ancestor directory is the repo's real import root
    (this tool never knows that for certain -- see module docstring)."""
    index: dict[str, list[str]] = {}
    for path in py_files:
        segments = _to_module_dotted(path).split(".")
        for i in range(len(segments)):
            suffix = ".".join(segments[i:])
            index.setdefault(suffix, []).append(path)
    return index


def _resolve_absolute_module(dotted: str, index: dict[str, list[str]]) -> str | None:
    candidates = index.get(dotted)
    return candidates[0] if candidates and len(candidates) == 1 else None


def _resolve_relative_module(importer_path: str, level: int, module: str | None, file_set: set[str]) -> str | None:
    base_dir = posixpath.dirname(importer_path)
    for _ in range(max(0, level - 1)):
        base_dir = posixpath.dirname(base_dir)
    if not module:
        return None
    rel = module.replace(".", "/")
    candidate = posixpath.normpath(posixpath.join(base_dir, rel) + ".py") if base_dir else rel + ".py"
    candidate_init = (
        posixpath.normpath(posixpath.join(base_dir, rel, "__init__.py")) if base_dir else posixpath.join(rel, "__init__.py")
    )
    if candidate in file_set:
        return candidate
    if candidate_init in file_set:
        return candidate_init
    return None


def _resolve_relative_bare_name(importer_path: str, level: int, name: str, file_set: set[str]) -> str | None:
    """`from . import X` (no module given) -- X might be a submodule of the
    current package (base_dir/X.py) or a symbol defined in that package's
    __init__.py. Submodule checked first since that's the more common
    "from package import submodule" pattern."""
    base_dir = posixpath.dirname(importer_path)
    for _ in range(max(0, level - 1)):
        base_dir = posixpath.dirname(base_dir)
    submodule = posixpath.normpath(posixpath.join(base_dir, name) + ".py") if base_dir else name + ".py"
    if submodule in file_set:
        return submodule
    init_file = posixpath.normpath(posixpath.join(base_dir, "__init__.py")) if base_dir else "__init__.py"
    return init_file if init_file in file_set else None


def parse(repo_path: str, py_files: list[str]) -> tuple[list[FunctionDef], list[CallSite], list[ImportEdge]]:
    file_set = set(py_files)
    module_index = _build_module_index(py_files)

    parsed_files: dict[str, _FileParse] = {}
    for path in py_files:
        try:
            with open(posixpath.join(repo_path, path), "r", encoding="utf-8", errors="replace") as fh:
                source = fh.read()
            tree = ast.parse(source, filename=path)
        except (OSError, SyntaxError, ValueError):
            # One unreadable/unparseable file (e.g. a syntax error under an
            # unsupported Python version, or a generated file) must not
            # lose the rest of the repo's graph.
            continue
        visitor = _Visitor(path, source)
        visitor.visit(tree)
        parsed_files[path] = _FileParse(
            path=path,
            functions=visitor.functions,
            name_to_ids=visitor.name_to_ids,
            raw_calls=visitor.raw_calls,
            raw_imports=visitor.raw_imports,
        )

    global_name_index: dict[str, list[str]] = {}
    for fp in parsed_files.values():
        for name, ids in fp.name_to_ids.items():
            global_name_index.setdefault(name, []).extend(ids)

    all_functions: list[FunctionDef] = []
    all_calls: list[CallSite] = []
    all_imports: list[ImportEdge] = []

    for fp in parsed_files.values():
        all_functions.extend(fp.functions)

        # local_name -> resolved target file path (module-level binding),
        # built once per file so every call site in it can reuse it.
        module_bindings: dict[str, str] = {}
        for imp in fp.raw_imports:
            if imp.kind == "import":
                for dotted, local in imp.names:
                    target = _resolve_absolute_module(dotted, module_index)
                    if target:
                        module_bindings[local] = target
                        all_imports.append(ImportEdge(fp.path, target, [dotted]))
                continue

            # "from module import a, b as c" (module is None for a plain
            # relative "from . import a").
            if imp.level > 0:
                module_file = _resolve_relative_module(fp.path, imp.level, imp.module, file_set)
            else:
                module_file = _resolve_absolute_module(imp.module, module_index) if imp.module else None

            for original, local in imp.names:
                target: str | None = None
                if imp.level > 0 and imp.module is None:
                    target = _resolve_relative_bare_name(fp.path, imp.level, original, file_set)
                elif module_file:
                    # Common "from package import submodule" pattern (this
                    # codebase's own `from app import db, queries` is
                    # exactly this): check whether module.original is
                    # itself a registered submodule before assuming it's a
                    # plain symbol inside module_file.
                    if imp.level == 0 and imp.module:
                        submodule = _resolve_absolute_module(f"{imp.module}.{original}", module_index)
                        target = submodule or module_file
                    else:
                        target = module_file
                if target:
                    module_bindings[local] = target
                    all_imports.append(ImportEdge(fp.path, target, [original]))

        for call in fp.raw_calls:
            if call.enclosing_qualname is None:
                continue  # module-level call, not attributable to a function
            caller_id = f"{fp.path}::{call.enclosing_qualname}"

            callee_id: str | None = None
            confidence = ""
            resolution = ""

            if call.kind in ("name", "self_attr"):
                same_file = fp.name_to_ids.get(call.name)
                if same_file and len(same_file) == 1:
                    callee_id, confidence, resolution = same_file[0], "high", "same_file"
                elif call.kind == "name" and call.name in module_bindings:
                    target_file = module_bindings[call.name]
                    target_ids = parsed_files.get(target_file, _FileParse(target_file)).name_to_ids.get(call.name)
                    if target_ids and len(target_ids) == 1:
                        callee_id, confidence, resolution = target_ids[0], "high", "import_resolved"
                if callee_id is None:
                    candidates = global_name_index.get(call.name)
                    if candidates and len(candidates) == 1:
                        callee_id, confidence, resolution = candidates[0], "low", "name_heuristic"
            elif call.kind == "name_attr":
                target_file = module_bindings.get(call.base)
                if target_file:
                    target_ids = parsed_files.get(target_file, _FileParse(target_file)).name_to_ids.get(call.name)
                    if target_ids and len(target_ids) == 1:
                        callee_id, confidence, resolution = target_ids[0], "high", "import_resolved"
                if callee_id is None:
                    candidates = global_name_index.get(call.name)
                    if candidates and len(candidates) == 1:
                        callee_id, confidence, resolution = candidates[0], "low", "name_heuristic"

            if callee_id and callee_id != caller_id:
                all_calls.append(CallSite(caller_id, callee_id, confidence, resolution, call.line))

    return all_functions, all_calls, all_imports
