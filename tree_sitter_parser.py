import re
from dataclasses import dataclass, field


@dataclass
class ParsedFile:
    filename: str
    functions: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    added_lines: list[str] = field(default_factory=list)
    removed_lines: list[str] = field(default_factory=list)


def _extract_patch_lines(patch: str) -> tuple[list[str], list[str]]:
    added, removed = [], []
    for line in patch.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:])
    return added, removed


def _extract_symbols_from_lines(lines: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Pull function names, class names, and imports out of a list of code lines."""
    functions, classes, imports = [], [], []
    for line in lines:
        stripped = line.strip()
        fn = re.match(r"def\s+(\w+)\s*\(", stripped)
        if fn:
            functions.append(fn.group(1))
        cls = re.match(r"class\s+(\w+)\s*[:(]", stripped)
        if cls:
            classes.append(cls.group(1))
        if stripped.startswith("import ") or stripped.startswith("from "):
            imports.append(stripped)
    return functions, classes, imports


def parse_changed_files(changed_files: list[dict]) -> list[ParsedFile]:
    """
    Parse each changed file's patch and extract semantic symbols.
    Falls back gracefully when tree-sitter bindings are unavailable.
    """
    try:
        import tree_sitter_python as tspython
        from tree_sitter import Language, Parser

        PY_LANGUAGE = Language(tspython.language())
        parser = Parser(PY_LANGUAGE)
        use_tree_sitter = True
    except Exception:
        use_tree_sitter = False

    results = []
    for f in changed_files:
        filename = f["filename"]
        patch = f.get("patch", "")

        if not patch:
            continue

        added_lines, removed_lines = _extract_patch_lines(patch)
        all_new_lines = added_lines

        if use_tree_sitter and filename.endswith(".py"):
            source = "\n".join(all_new_lines).encode()
            tree = parser.parse(source)
            functions = _query_names(tree, source, "(function_definition name: (identifier) @name)")
            classes = _query_names(tree, source, "(class_definition name: (identifier) @name)")
            imports = [l.strip() for l in all_new_lines if l.strip().startswith(("import ", "from "))]
        else:
            functions, classes, imports = _extract_symbols_from_lines(all_new_lines)

        results.append(
            ParsedFile(
                filename=filename,
                functions=list(dict.fromkeys(functions)),
                classes=list(dict.fromkeys(classes)),
                imports=imports,
                added_lines=added_lines,
                removed_lines=removed_lines,
            )
        )

    return results


def _query_names(tree, source: bytes, query_str: str) -> list[str]:
    try:
        from tree_sitter import Language, Query
        import tree_sitter_python as tspython

        lang = Language(tspython.language())
        query = lang.query(query_str)
        captures = query.captures(tree.root_node)
        names = []
        for node, _ in captures:
            names.append(source[node.start_byte:node.end_byte].decode())
        return names
    except Exception:
        return []


def summarize_for_prompt(parsed_files: list[ParsedFile]) -> str:
    """Produce a compact text summary suitable for inclusion in the Claude prompt."""
    lines = []
    for pf in parsed_files:
        lines.append(f"\n### {pf.filename}")
        if pf.functions:
            lines.append(f"  Functions added/modified: {', '.join(pf.functions)}")
        if pf.classes:
            lines.append(f"  Classes added/modified:   {', '.join(pf.classes)}")
        if pf.imports:
            lines.append(f"  Imports changed:          {len(pf.imports)} import(s)")
        lines.append(f"  Lines added: {len(pf.added_lines)}  |  Lines removed: {len(pf.removed_lines)}")
    return "\n".join(lines) if lines else "No Python files changed."
