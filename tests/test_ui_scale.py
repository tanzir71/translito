import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from ui_scale import px, scaled_geometry, restore_geometry, enable_system_dpi_awareness
from tools.scale_ui_literals import FILES
from test_settings_ui import desktop, widgets


def test_pixel_scaling_is_idempotent_and_keeps_character_units(monkeypatch):
    monkeypatch.setenv("TRANSLITO_UI_SCALE","1.5")
    assert px(188)==282 and px(px(188))==282
    assert px((12,6))==(18,9)
    assert px(22,chars=True)==22
    assert scaled_geometry("820x680")=="1230x1020"
    assert restore_geometry("800x640+20+30",96)=="1200x960+20+30"
    assert restore_geometry("1200x960",144)=="1200x960"


def test_manifest_and_source_awareness_are_system_only():
    root=ET.parse("installer/Translito.manifest").getroot()
    assert root.find(".//{http://schemas.microsoft.com/SMI/2005/WindowsSettings}dpiAware").text=="true"
    assert root.find(".//{http://schemas.microsoft.com/SMI/2016/WindowsSettings}dpiAwareness").text=="system"
    assert 'manifest=' in Path("installer/Translito.spec").read_text()
    api=SimpleNamespace(SetProcessDpiAwareness=Mock())
    enable_system_dpi_awareness(shcore=api)
    api.SetProcessDpiAwareness.assert_called_once_with(1)
    tree=ast.parse(Path("gui.py").read_text(encoding="utf-8"))
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="gui_main")
    calls=[(n.lineno,ast.unparse(n.func)) for n in ast.walk(function) if isinstance(n,ast.Call)]
    assert min(line for line,name in calls if name=="enable_system_dpi_awareness") < min(line for line,name in calls if name=="tk.Tk")


def test_fixed_geometry_width_and_wrap_literals_use_pixel_helpers():
    failures=[]
    for filename in FILES:
        tree=ast.parse(Path(filename).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node,ast.Call):
                continue
            name=node.func.attr if isinstance(node.func,ast.Attribute) else ""
            for key in node.keywords:
                if key.arg in {"width","wraplength"} and isinstance(key.value,ast.Constant) and type(key.value.value) in {int,float}:
                    failures.append((filename,key.value.lineno,key.arg))
            if name=="minsize" and any(isinstance(a,ast.Constant) and type(a.value) in {int,float} for a in node.args):
                failures.append((filename,node.lineno,"minsize"))
            if name in {"geometry","wm_geometry"} and node.args and isinstance(node.args[0],ast.Constant) and "x" in str(node.args[0].value):
                failures.append((filename,node.lineno,"geometry"))
    assert not failures,failures


def test_settings_and_dialogs_fit_at_one_and_a_half_scale(desktop,monkeypatch):
    import gui
    import tkinter as tk
    from quality_settings import open_translategemma_setup
    from provider_settings import open_provider_settings
    from check_ui import open_check
    monkeypatch.setenv("TRANSLITO_UI_SCALE","1.5")
    create,_=desktop
    app=create()
    app.credential_store=SimpleNamespace(get=lambda name:None,save=lambda *a:None,delete=lambda *a:None)
    app.root.deiconify()
    app.root.update()
    app.open_settings()
    window=app.settings_window
    window.transient("")
    window.deiconify()
    import time
    for _ in range(10):
        window.update()
        time.sleep(.01)
    assert window.wm_geometry().split("+")[0]=="1230x1020"
    def assert_fit(parent):
        failures=[]
        for widget in widgets(parent):
            if widget is parent or not widget.winfo_ismapped() or isinstance(widget,tk.Toplevel):
                continue
            owner=widget.master
            if owner.winfo_width()>2 and widget.winfo_x()+widget.winfo_width()>owner.winfo_width()+2:
                failures.append((str(widget),widget.winfo_class(),widget.winfo_width(),owner.winfo_width()))
        assert not failures,failures[:12]
    for page in app.settings_shell.pages:
        app.settings_shell.show(page)
        window.update()
        scroll = app.settings_shell.pages[page]
        scroll._fit_content_width(SimpleNamespace(width=scroll.canvas.winfo_width()+200))
        window.update_idletasks()
        assert scroll.content.winfo_width() == scroll.canvas.winfo_width()
        assert_fit(window)
    for factory in (open_translategemma_setup,open_provider_settings,open_check):
        dialog=factory(app,gui.COLORS,gui.center_window)
        dialog.transient("")
        dialog.deiconify()
        dialog.update()
        assert_fit(dialog)
        dialog.destroy()
