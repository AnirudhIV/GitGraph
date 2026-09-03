#!/usr/bin/env node
/**
 * Extracts function definitions, call sites, and import statements from a
 * repo's TS/JS files using the real TypeScript checker (via ts-morph), for
 * GitGraph's function-level dependency graph.
 *
 * Invoked as a subprocess from backend/seed/parse/ts_parser.py:
 *   node extract.js <repoPath> <filesListJsonPath> <outJsonPath>
 *
 * <filesListJsonPath> is a JSON array of repo-relative (posix-style) paths
 * to restrict analysis to -- the same mined file list py_parser.py works
 * from, so both languages only ever report on files GitGraph already knows
 * about. Output is one JSON document at <outJsonPath>:
 *   { functions: [...], calls: [...], imports: [...] }
 * matching the FunctionDef/CallSite/ImportEdge contract in
 * backend/seed/parse/__init__.py exactly, so ts_parser.py's job is just to
 * read this file back -- no per-language special-casing anywhere else in
 * the pipeline.
 */
const fs = require("fs");
const path = require("path");
const { Project, SyntaxKind, Node } = require("ts-morph");

function toPosix(p) {
  return p.split(path.sep).join("/");
}

// ts-morph normalizes its own file paths to forward slashes internally
// regardless of platform, while path.resolve()/path.join() on Windows
// produce backslash paths -- comparing those directly as strings never
// matches. normKey() puts both sides through the same forward-slash (and,
// on win32 only, lowercase -- Windows paths are case-insensitive but
// case-preserving, so two paths differing only in drive-letter or
// directory casing are still the same file) form before every set
// membership check below.
const IS_WIN = process.platform === "win32";
function normKey(p) {
  const posix = path.resolve(p).split(path.sep).join("/");
  return IS_WIN ? posix.toLowerCase() : posix;
}

function findTsConfig(repoPath, relFiles) {
  const direct = path.join(repoPath, "tsconfig.json");
  if (fs.existsSync(direct)) return direct;
  // Monorepo-friendly best effort: check the tsconfig.json of each distinct
  // top-level directory among the files we were asked to parse (e.g. this
  // repo's own frontend/tsconfig.json), without hardcoding any folder name.
  const topDirs = new Set(relFiles.map((f) => f.split("/")[0]).filter(Boolean));
  for (const dir of topDirs) {
    const candidate = path.join(repoPath, dir, "tsconfig.json");
    if (fs.existsSync(candidate)) return candidate;
  }
  return null;
}

function buildProject(repoPath, relFiles) {
  const tsConfigFilePath = findTsConfig(repoPath, relFiles);
  let project;
  if (tsConfigFilePath) {
    project = new Project({ tsConfigFilePath, skipAddingFilesFromTsConfig: false, skipFileDependencyResolution: false });
  } else {
    project = new Project({
      compilerOptions: {
        allowJs: true,
        checkJs: false,
        target: 99, // ts.ScriptTarget.Latest
        module: 99, // ts.ModuleKind.ESNext
        moduleResolution: 100, // ts.ModuleResolutionKind.Bundler
        jsx: 4, // ts.JsxEmit.ReactJSX
        esModuleInterop: true,
        skipLibCheck: true,
      },
      skipAddingFilesFromTsConfig: true,
      useInMemoryFileSystem: false,
    });
  }
  // Defensively ensure every file we were asked about is actually in the
  // project, whether or not the tsconfig's own include/exclude happened to
  // reach it -- addSourceFileAtPathIfExists is a no-op if it's already
  // there via the tsconfig.
  for (const rel of relFiles) {
    const abs = path.join(repoPath, rel);
    if (fs.existsSync(abs)) project.addSourceFileAtPathIfExists(abs);
  }
  return project;
}

// A stable name for a function-like node: its own name if declared with
// one (FunctionDeclaration/MethodDeclaration name, or the variable/property
// name it's assigned to), else null (truly anonymous -- e.g. an inline
// callback passed straight into another call -- skipped as not worth a
// graph node, same philosophy as py_parser.py only tracking named defs).
function functionName(node) {
  const kind = node.getKind();
  if (kind === SyntaxKind.FunctionDeclaration || kind === SyntaxKind.MethodDeclaration) {
    return node.getName() || null;
  }
  if (kind === SyntaxKind.ArrowFunction || kind === SyntaxKind.FunctionExpression) {
    const parent = node.getParent();
    if (parent && Node.isVariableDeclaration(parent)) return parent.getName();
    if (parent && Node.isPropertyAssignment(parent)) return parent.getName();
    if (parent && Node.isPropertyDeclaration(parent)) return parent.getName();
    return null;
  }
  return null;
}

function isMethodLike(node) {
  return node.getKind() === SyntaxKind.MethodDeclaration;
}

function isExported(node) {
  const kind = node.getKind();
  if (kind === SyntaxKind.FunctionDeclaration) return node.isExported();
  if (kind === SyntaxKind.ArrowFunction || kind === SyntaxKind.FunctionExpression) {
    const parent = node.getParent();
    if (parent && Node.isVariableDeclaration(parent)) {
      const stmt = parent.getFirstAncestorByKind(SyntaxKind.VariableStatement);
      return !!(stmt && stmt.isExported());
    }
  }
  return false;
}

// The node whose .getText() is actually worth showing as "this function's
// source": a FunctionDeclaration/MethodDeclaration's own text already
// includes its decorators (TS decorators are syntactically part of the
// node itself, unlike Python's ast module), so those need no adjustment.
// An arrow/function-expression's own text is just "() => {...}" -- walk up
// to the VariableStatement ("const foo = () => {...}", full statement
// incl. export/const) or PropertyAssignment/PropertyDeclaration ("foo: () =>
// {...}") so the display includes what it's actually bound to.
function displaySourceNode(node) {
  const kind = node.getKind();
  if (kind === SyntaxKind.FunctionDeclaration || kind === SyntaxKind.MethodDeclaration) return node;
  const parent = node.getParent();
  if (parent && Node.isVariableDeclaration(parent)) {
    return parent.getFirstAncestorByKind(SyntaxKind.VariableStatement) || parent;
  }
  if (parent && (Node.isPropertyAssignment(parent) || Node.isPropertyDeclaration(parent))) return parent;
  return node;
}

// Dot-joined qualname mirroring py_parser.py's CPython-style scheme:
// enclosing class/function names, own name last.
function qualnameOf(node) {
  const parts = [];
  let current = node;
  while (current) {
    const kind = current.getKind();
    if (kind === SyntaxKind.ClassDeclaration) {
      const name = current.getName();
      if (name) parts.unshift(name);
    } else if (
      kind === SyntaxKind.FunctionDeclaration ||
      kind === SyntaxKind.MethodDeclaration ||
      kind === SyntaxKind.ArrowFunction ||
      kind === SyntaxKind.FunctionExpression
    ) {
      const name = functionName(current);
      if (name) parts.unshift(name);
    }
    current = current.getParent();
  }
  return parts.join(".");
}

// Same boundary set qualnameOf/nearestEnclosingFunction use for "is this a
// function of its own" -- a nested function-like node gets its own
// functions[] entry (and its own complexity), so walking into one here
// would double-count its branches into the enclosing function's score.
// Mirrors py_parser.py's _ComplexityVisitor.visit_FunctionDef/
// AsyncFunctionDef no-op override, just expressed as a kind-set check
// instead of overridden visitor methods (ts-morph's forEachChild has no
// per-kind dispatch to override).
const FUNCTION_LIKE_KINDS = new Set([
  SyntaxKind.FunctionDeclaration,
  SyntaxKind.MethodDeclaration,
  SyntaxKind.ArrowFunction,
  SyntaxKind.FunctionExpression,
]);

// McCabe cyclomatic complexity: 1 (base path) + one per decision point --
// same practical definition as py_parser.py::_cyclomatic_complexity (see
// its docstring for why this node-counting form is equivalent to the full
// CFG derivation for structured code). && / || each add a branch the same
// way Python's BoolOp handling does (one per operator, so a chain of N
// operands contributes N-1); ?? is treated as a plain value expression,
// not a branch, matching most JS complexity linters' default.
function cyclomaticComplexity(fnNode) {
  let count = 1;
  function walk(node) {
    switch (node.getKind()) {
      case SyntaxKind.IfStatement:
      case SyntaxKind.ForStatement:
      case SyntaxKind.ForInStatement:
      case SyntaxKind.ForOfStatement:
      case SyntaxKind.WhileStatement:
      case SyntaxKind.DoStatement:
      case SyntaxKind.ConditionalExpression:
      case SyntaxKind.CatchClause:
      case SyntaxKind.CaseClause:
        count += 1;
        break;
      case SyntaxKind.BinaryExpression: {
        const op = node.getOperatorToken().getText();
        if (op === "&&" || op === "||") count += 1;
        break;
      }
      default:
        break;
    }
    node.forEachChild((child) => {
      if (!FUNCTION_LIKE_KINDS.has(child.getKind())) walk(child);
    });
  }
  fnNode.forEachChild((child) => {
    if (!FUNCTION_LIKE_KINDS.has(child.getKind())) walk(child);
  });
  return count;
}

function nearestEnclosingFunction(node) {
  let current = node.getParent();
  while (current) {
    const kind = current.getKind();
    if (
      kind === SyntaxKind.FunctionDeclaration ||
      kind === SyntaxKind.MethodDeclaration ||
      kind === SyntaxKind.ArrowFunction ||
      kind === SyntaxKind.FunctionExpression
    ) {
      if (functionName(current)) return current;
    }
    current = current.getParent();
  }
  return null;
}

function main() {
  const [, , repoPath, filesListJsonPath, outJsonPath] = process.argv;
  const relFiles = JSON.parse(fs.readFileSync(filesListJsonPath, "utf8"));
  const targetAbsSet = new Set(relFiles.map((f) => normKey(path.join(repoPath, f))));

  const project = buildProject(repoPath, relFiles);

  // nodeKey (file::start-pos) -> functionId, built once so the call-
  // resolution pass can map a resolved declaration node straight back to
  // our own id scheme without re-walking anything.
  const nodeKeyToId = new Map();
  const nameIndex = new Map(); // bare name -> [functionId, ...]
  const functions = [];

  function nodeKey(n) {
    return `${n.getSourceFile().getFilePath()}::${n.getStart()}`;
  }

  for (const sourceFile of project.getSourceFiles()) {
    const absPath = sourceFile.getFilePath();
    if (!targetAbsSet.has(normKey(absPath))) continue;
    const relPath = toPosix(path.relative(repoPath, absPath));
    const ext = path.extname(relPath).replace(".", "");
    const language = ext === "ts" || ext === "tsx" ? "typescript" : "javascript";

    const candidateKinds = [
      SyntaxKind.FunctionDeclaration,
      SyntaxKind.MethodDeclaration,
      SyntaxKind.ArrowFunction,
      SyntaxKind.FunctionExpression,
    ];
    for (const kind of candidateKinds) {
      for (const node of sourceFile.getDescendantsOfKind(kind)) {
        const name = functionName(node);
        if (!name) continue; // anonymous, not worth a graph node
        const qualname = qualnameOf(node);
        const id = `${relPath}::${qualname}`;
        functions.push({
          id,
          path: relPath,
          name,
          qualname,
          language,
          start_line: node.getStartLineNumber(),
          end_line: node.getEndLineNumber(),
          is_exported: isExported(node),
          is_method: isMethodLike(node),
          source: displaySourceNode(node).getText(),
          complexity: cyclomaticComplexity(node),
        });
        nodeKeyToId.set(nodeKey(node), id);
        // A call's resolved symbol declaration for `const foo = () => {}`
        // or `{ foo: () => {} }` is the VariableDeclaration/
        // PropertyAssignment/PropertyDeclaration wrapping the arrow/
        // function expression, not the arrow itself -- register that
        // wrapper's own key too so the checker-resolution pass below finds
        // it. FunctionDeclaration/MethodDeclaration need no such alias:
        // their own node *is* what a symbol resolves to.
        const parent = node.getParent();
        if (parent && (Node.isVariableDeclaration(parent) || Node.isPropertyAssignment(parent) || Node.isPropertyDeclaration(parent))) {
          nodeKeyToId.set(nodeKey(parent), id);
        }
        if (!nameIndex.has(name)) nameIndex.set(name, []);
        nameIndex.get(name).push(id);
      }
    }
  }

  const calls = [];
  const importsByPair = new Map(); // "from|to" -> Set(names)

  for (const sourceFile of project.getSourceFiles()) {
    const absPath = sourceFile.getFilePath();
    if (!targetAbsSet.has(normKey(absPath))) continue;
    const relPath = toPosix(path.relative(repoPath, absPath));

    // Imports: getModuleSpecifierSourceFile() does full module resolution
    // (tsconfig baseUrl/paths honored) -- if it lands outside our own
    // target set (node_modules, ambient .d.ts, unresolvable) the edge is
    // dropped rather than stored with a guessed target.
    for (const importDecl of sourceFile.getImportDeclarations()) {
      const targetFile = importDecl.getModuleSpecifierSourceFile();
      if (!targetFile) continue;
      const targetAbs = targetFile.getFilePath();
      if (!targetAbsSet.has(normKey(targetAbs))) continue;
      const targetRel = toPosix(path.relative(repoPath, targetAbs));
      const names = [];
      const defaultImport = importDecl.getDefaultImport();
      if (defaultImport) names.push(defaultImport.getText());
      const namespaceImport = importDecl.getNamespaceImport();
      if (namespaceImport) names.push(namespaceImport.getText());
      for (const named of importDecl.getNamedImports()) names.push(named.getName());
      const key = `${relPath}|${targetRel}`;
      if (!importsByPair.has(key)) importsByPair.set(key, new Set());
      const set = importsByPair.get(key);
      names.forEach((n) => set.add(n));
    }

    // Calls
    for (const callExpr of sourceFile.getDescendantsOfKind(SyntaxKind.CallExpression)) {
      const enclosing = nearestEnclosingFunction(callExpr);
      if (!enclosing) continue; // module-level call, not attributable to a function
      const callerId = nodeKeyToId.get(nodeKey(enclosing));
      if (!callerId) continue;

      const calleeExpr = callExpr.getExpression();
      let calleeId = null;
      let confidence = "";
      let resolution = "";

      let symbol = calleeExpr.getSymbol();
      if (symbol && symbol.isAlias && symbol.isAlias()) {
        // `import { foo } from "./bar"` binds a local alias symbol at the
        // call site (declaration: the ImportSpecifier itself), not foo's
        // own declaration -- follow it through so a plain named-import
        // call resolves exactly as well as same-file or object-property
        // calls already do.
        try {
          symbol = symbol.getAliasedSymbol() || symbol;
        } catch {
          // Not actually resolvable as an alias (e.g. a type-only import) --
          // fall through to the heuristic below via the original symbol's
          // (empty/irrelevant) declarations.
        }
      }
      if (symbol) {
        for (const decl of symbol.getDeclarations()) {
          const key = nodeKey(decl);
          if (nodeKeyToId.has(key)) {
            calleeId = nodeKeyToId.get(key);
            const declFile = decl.getSourceFile().getFilePath();
            resolution = declFile === absPath ? "same_file" : "type_checked";
            confidence = "high";
            break;
          }
        }
      }

      if (!calleeId) {
        // Bare callee name for the heuristic fallback: last identifier of
        // a property access (obj.method()) or the identifier itself.
        let bareName = null;
        if (Node.isPropertyAccessExpression(calleeExpr)) bareName = calleeExpr.getName();
        else if (Node.isIdentifier(calleeExpr)) bareName = calleeExpr.getText();
        if (bareName) {
          const candidates = nameIndex.get(bareName);
          if (candidates && candidates.length === 1) {
            calleeId = candidates[0];
            confidence = "low";
            resolution = "name_heuristic";
          }
        }
      }

      if (calleeId && calleeId !== callerId) {
        calls.push({ caller_id: callerId, callee_id: calleeId, confidence, resolution, line: callExpr.getStartLineNumber() });
      }
    }
  }

  const imports = Array.from(importsByPair.entries()).map(([key, names]) => {
    const [fromPath, toPath] = key.split("|");
    return { from_path: fromPath, to_path: toPath, imported_names: Array.from(names).sort() };
  });

  fs.writeFileSync(outJsonPath, JSON.stringify({ functions, calls, imports }), "utf8");
}

main();
