"""One-off source migration for explicit pixel units; source spans stay intact."""
import ast
from pathlib import Path

FILES = ("gui.py", "meeting_app.py", "ui_theme.py", "ui_widgets.py", "settings_shell.py", "engine_ui.py", "cloud_ui.py",
         "provider_settings.py", "quality_settings.py", "model_library_ui.py", "check_ui.py", "schedule_ui.py",
         "weekly_schedule_ui.py", "subtitle_overlay.py", "reply_ui.py", "virtual_mic_ui.py", "download_ui.py", "settings_feedback.py")
CHAR_WIDTH = {"Entry", "Label", "Button", "Checkbutton", "Radiobutton", "Combobox", "Listbox", "Spinbox", "Text"}
ROW_HEIGHT = CHAR_WIDTH | {"Treeview"}
PIXEL_OPTIONS = {"padx", "pady", "ipadx", "ipady", "wraplength", "borderwidth", "highlightthickness", "padding", "rowheight", "arrowsize", "length"}


def migrate(path):
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    def offset(line, column):
        return starts[line-1] + len(lines[line-1].encode("utf-8")[:column].decode("utf-8"))
    def span(node):
        return offset(node.lineno,node.col_offset), offset(node.end_lineno,node.end_col_offset)
    edits = []
    def wrap(node, function="px", suffix=""):
        a,b = span(node)
        edits.append((a,b,function+"("+source[a:b]+suffix+")"))
    def numeric(node):
        return (isinstance(node, ast.Constant) and type(node.value) in {int,float}) or (
            isinstance(node,(ast.Tuple,ast.List)) and all(numeric(item) for item in node.elts))
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        name = call.func.attr if isinstance(call.func,ast.Attribute) else call.func.id if isinstance(call.func,ast.Name) else ""
        if name == "minsize":
            for argument in call.args:
                if numeric(argument):
                    wrap(argument)
        if name in {"geometry", "wm_geometry"} and call.args and isinstance(call.args[0],ast.Constant) and isinstance(call.args[0].value,str) and "x" in call.args[0].value:
            wrap(call.args[0],"scaled_geometry")
        for key in call.keywords:
            if not numeric(key.value):
                continue
            if key.arg in PIXEL_OPTIONS or key.arg in {"width", "height"}:
                chars = key.arg == "width" and name in CHAR_WIDTH or key.arg == "height" and name in ROW_HEIGHT
                wrap(key.value,suffix=", chars=True" if chars else "")
    for a,b,replacement in sorted(edits,reverse=True):
        source = source[:a]+replacement+source[b:]
    if edits:
        # Keep module docstrings and __future__ ordering intact.
        original_lines=source.splitlines(keepends=True)
        first=1 if tree.body and isinstance(tree.body[0],ast.Expr) and isinstance(tree.body[0].value,ast.Constant) and isinstance(tree.body[0].value.value,str) else 0
        insert_at=tree.body[0].end_lineno if first else 0
        original_lines.insert(insert_at,"from ui_scale import px, scaled_geometry\n")
        path.write_text("".join(original_lines),encoding="utf-8")


if __name__ == "__main__":
    root=Path(__file__).resolve().parents[1]
    for filename in FILES:
        migrate(root/filename)
