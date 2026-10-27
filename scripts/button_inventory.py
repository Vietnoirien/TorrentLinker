"""List every desktop button with its label and role, to track the move to shared roles.

Run from the repository root: `python scripts/button_inventory.py [--markdown]`.
In the table, "—" means the default secondary role.
A button without a role uses the plain secondary style; see gui/controls.py.
"""

from __future__ import annotations

import ast
import collections
import sys
from pathlib import Path

GUI = Path("src/torrentlinker/gui")


def label_of(call: ast.Call) -> str:
    if not call.args:
        return ""
    arg = call.args[0]
    if isinstance(arg, ast.Call) and getattr(arg.func, "attr", "") == "tr" and arg.args:
        first = arg.args[0]
        return str(first.value) if isinstance(first, ast.Constant) else "(computed)"
    return str(arg.value) if isinstance(arg, ast.Constant) else "(computed)"


def roles_in(tree: ast.AST) -> dict[str, str]:
    """Role given to each button expression, such as `self.play_button` -> `primary`."""
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "set_role":
            if len(node.args) == 2 and isinstance(node.args[1], ast.Constant):
                found[ast.unparse(node.args[0])] = node.args[1].value
        elif isinstance(node, ast.For) and isinstance(node.iter, ast.Tuple):
            # `for widget in (a, b): set_role(widget, "icon")` gives each item the role.
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Call)
                    and getattr(inner.func, "id", "") == "set_role"
                    and ast.unparse(inner.args[0]) == ast.unparse(node.target)
                    and isinstance(inner.args[1], ast.Constant)
                ):
                    for item in node.iter.elts:
                        found[ast.unparse(item)] = inner.args[1].value
    return found


def inventory() -> list[tuple[str, int, str, str]]:
    rows = []
    for path in sorted(GUI.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        roles = roles_in(tree)
        for node in ast.walk(tree):
            targets = node.targets if isinstance(node, ast.Assign) else []
            call = node.value if isinstance(node, ast.Assign) else None
            if not isinstance(call, ast.Call):
                continue
            name = getattr(call.func, "id", getattr(call.func, "attr", ""))
            if name in {"QPushButton", "QToolButton", "icon_button"}:
                target = ast.unparse(targets[0])
                role = "icon" if name == "icon_button" else roles.get(target, "")
                rows.append((path.name, node.lineno, label_of(call), role))
    return rows


def main() -> None:
    rows = inventory()
    with_role = sum(1 for row in rows if row[3])
    if "--markdown" in sys.argv:
        print("| File | Line | Label | Role |\n| --- | --- | --- | --- |")
        for file, line, label, role in rows:
            print(f"| {file} | {line} | {label} | {role or '—'} |")
        return
    print(f"{len(rows)} buttons, {with_role} with an explicit role")
    for name, count in collections.Counter(row[0] for row in rows).most_common():
        print(f"{count:4} {name}")


if __name__ == "__main__":
    main()
