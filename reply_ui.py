"""One reply set shared by the main strip, desktop captions and hotkeys."""
import threading
import tkinter as tk
from tkinter import ttk

from engines.replies import ReplyService


class ReplyController:
    def __init__(self, app, colors):
        self.app, self.colors = app, colors
        self.options = {}
        for key, default in (("enabled", True), ("trigger", "question"), ("show_native", False), ("show_on_overlay", True)):
            var = tk.BooleanVar(app.root) if isinstance(default,bool) else tk.StringVar(app.root)
            self.options[key] = app.preferences.bind(var,"REPLIES",key,default)
        self.visible_var = app.preferences.bind(tk.BooleanVar(app.root),"UI","reply_strip_visible",True)
        self.replies, self.context, self.language, self.target = (), [], "", "en"
        self.current_id, self.suggested, self.generation = None, None, 0
        self.frame = tk.Frame(app.root,bg=colors["bg"],padx=16,pady=10)
        self.status = tk.StringVar()
        self.visible_var.trace_add("write",lambda *_:self.render())
        for variable in self.options.values():
            variable.trace_add("write",lambda *_:self.render())

    def somewhere_visible(self):
        main = self.visible_var.get() and self.app.root.winfo_viewable()
        overlay = self.app.subtitles_enabled_var.get() and self.options["show_on_overlay"].get()
        return main or overlay

    def accept(self, entry):
        text, identity = entry.get("source_text",""), entry.get("id")
        if not text:
            return
        if identity != self.current_id:
            self.current_id, self.replies = identity, ()
            self.generation += 1
            self.render()
        self.language = entry.get("source_language") or self.app.language_entry_by_name(self.app.listen_source_var.get())[2]
        self.target = entry.get("target_language") or self.app.language_entry_by_name(self.app.listen_target_var.get())[2]
        if not self.context or self.context[-1][0] != identity:
            self.context.append((identity,text))
            self.context = self.context[-3:]
        else:
            self.context[-1] = identity,text
        marker = identity,text
        if (self.options["enabled"].get() and self.options["trigger"].get() == "question" and not entry.get("translation_pending")
                and not entry.get("pass_through") and text.rstrip().endswith(("?","؟")) and marker != self.suggested):
            self.suggested = marker
            self.request()

    def translator(self):
        if self.app.preview_mode:
            return None
        from types import SimpleNamespace
        from engines.settings import load_engine_settings
        from engines.registry import build_session_routers
        local = SimpleNamespace(name="local",requires_network=False,supports=lambda *a:True)
        _, router = build_session_routers(local,local,load_engine_settings(self.app.preferences.path),
            pair=(self.language,self.target),on_event=self.app.on_event)
        return router

    def request(self):
        if not self.options["enabled"].get() or not self.context or not self.somewhere_visible():
            return
        self.generation += 1
        generation, language, target = self.generation,self.language,self.target
        context, variety = [text for _,text in self.context],self.app.variety_var.get()
        self.status.set("Suggesting replies…")
        def work():
            result = ReplyService(self.translator()).suggest(context,language,target,variety=variety)
            def finish():
                if generation != self.generation or not self.options["enabled"].get():
                    return
                self.replies = result.replies
                self.status.set("Phrasebook · free" if result.provider == "phrasebook" else "Short replies · usage included in your budget")
                self.render()
            self.app.root.after(0,finish)
        threading.Thread(target=work,daemon=True).start()

    def render(self):
        for child in self.frame.winfo_children():
            child.destroy()
        if not self.replies or not self.visible_var.get() or not self.options["enabled"].get():
            self.frame.grid_remove()
        else:
            self.frame.grid(row=9,column=0,sticky="ew")
            header = tk.Frame(self.frame,bg=self.colors["bg"])
            header.pack(fill="x",pady=(0,8))
            tk.Label(header,textvariable=self.status,bg=self.colors["bg"],fg=self.colors["secondary"],font=("Segoe UI",8)).pack(side="left")
            ttk.Button(header,text="Hide",command=lambda:self.visible_var.set(False),style="Mac.TButton").pack(side="right")
            ttk.Button(header,text="More",command=self.request,style="Mac.TButton").pack(side="right",padx=6)
            cards = tk.Frame(self.frame,bg=self.colors["bg"])
            cards.pack(fill="x")
            for index, reply in enumerate(self.replies):
                card = tk.Frame(cards,bg=self.colors["surface_2"],highlightthickness=1,highlightbackground=self.colors["border"],padx=10,pady=8)
                card.grid(row=0,column=index,sticky="nsew",padx=(0,8))
                cards.columnconfigure(index,weight=1,uniform="replies")
                tk.Label(card,text=f"{index+1}  {reply.spoken}",bg=self.colors["surface_2"],fg=self.colors["text"],font=("Segoe UI Semibold",10),wraplength=210,justify="left",anchor="w").pack(fill="x")
                tk.Label(card,text=reply.meaning,bg=self.colors["surface_2"],fg=self.colors["secondary"],font=("Segoe UI",9),wraplength=210,justify="left",anchor="w").pack(fill="x",pady=(4,0))
                if self.options["show_native"].get() and reply.romanized:
                    from engines.display import display_text
                    tk.Label(card,text=display_text(reply.native),bg=self.colors["surface_2"],fg=self.colors["tertiary"],font=("Segoe UI",9)).pack(fill="x")
                self.card_actions(card,index)
        self.render_overlay()

    def card_actions(self, card, index):
        pass

    def render_overlay(self):
        pass


def page(app, colors):
    from engine_ui import heading, field
    from ui_widgets import Switch
    parent, controller = app.settings_shell.contents["Languages"], app.reply_controller
    heading(parent,"Reply suggestions","Short replies in the spoken language, with readable English letters and a meaning.",colors)
    row = tk.Frame(parent,bg=colors["bg"])
    row.pack(fill="x",pady=8)
    tk.Label(row,text="Suggest short replies",bg=colors["bg"],fg=colors["text"]).pack(side="left")
    Switch(row,controller.options["enabled"],colors).pack(side="right")
    field(parent,"Suggest",controller.options["trigger"],colors,("question","hotkey"))
    for key,label in (("show_native","Show the native script as well"),("show_on_overlay","Show suggestions on the subtitle bar")):
        tk.Checkbutton(parent,text=label,variable=controller.options[key],**{**app._checkbutton_options(),"bg":colors["bg"]}).pack(anchor="w",pady=6)
    tk.Checkbutton(parent,text="Show reply strip in the main window",variable=controller.visible_var,
        **{**app._checkbutton_options(),"bg":colors["bg"]}).pack(anchor="w",pady=6)
