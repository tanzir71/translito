"""One reply set shared by the main strip, desktop captions and hotkeys."""
from ui_scale import px, scaled_geometry
from engines.display import font_family, display_text, wrap_text
from ui_dispatch import post
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
        self.request_stop = threading.Event()
        self.busy = False
        self.reply_player, self.overlay_signature = None, None
        self.main_signature = None
        self.frame = tk.Frame(app.root,bg=colors["bg"],padx=px(16),pady=px(10))
        self.status = tk.StringVar()
        self.visible_var.trace_add("write",lambda *_:self.render())
        for variable in self.options.values():
            variable.trace_add("write",lambda *_:self.render())
        self.options["enabled"].trace_add("write", self.enabled_changed)
        app.subtitles_enabled_var.trace_add("write",lambda *_:self.render_overlay())

    def somewhere_visible(self):
        main = self.visible_var.get() and self.app.root.winfo_viewable() and self.app.root.state() != "iconic"
        window = self.app.subtitle_controller.overlay
        overlay = (self.app.subtitles_enabled_var.get() and self.options["show_on_overlay"].get()
                   and window is not None and self.app.transcriber is not None and self.app.mode_var.get() == "listen")
        return main or overlay

    def enabled_changed(self, *_):
        if not self.options["enabled"].get():
            self.generation += 1
            self.request_stop.set()
            self.replies = ()
            self.busy = False
            self.stop_speaking()
            self.render()
        elif self.context:
            self.show_and_request()

    def accept(self, entry):
        text, identity = entry.get("source_text",""), entry.get("id")
        if not text:
            return
        if identity != self.current_id:
            self.current_id = identity
        previous_pair = getattr(self, "language", ""), getattr(self, "target", "")
        self.language = entry.get("source_language") or self.app.language_entry_by_name(self.app.listen_source_var.get())[2]
        if entry.get("language_tag") == "mix":
            self.language = self.app.current_conversation().other_language
        self.target = entry.get("target_language") or self.app.language_entry_by_name(self.app.listen_target_var.get())[2]
        if previous_pair[0] and previous_pair != (self.language, self.target):
            self.replies = ()
            self.generation += 1
            self.request_stop.set()
            self.busy = False
            self.status.set("")
        if not self.context or self.context[-1][0] != identity:
            self.context.append((identity,text))
            self.context = self.context[-3:]
        else:
            self.context[-1] = identity,text
        marker = identity,text
        source_final = not entry.get("source_provisional", entry.get("translation_pending", False))
        question = any(value.rstrip(' \t\n\"\u201d\u2019\u00bb)').endswith(("?", "؟", "？"))
                       for value in (text, entry.get("translated_text", "")))
        self.render()
        if (self.options["enabled"].get() and self.options["trigger"].get() == "question" and source_final
                and not entry.get("pass_through") and question and marker != self.suggested):
            self.suggested = marker
            self.request()

    def translator(self, language, target, config_path, offline_only, preview):
        if preview:
            return None
        from types import SimpleNamespace
        from engines.settings import load_engine_settings
        from engines.registry import build_session_routers
        local = SimpleNamespace(name="local",requires_network=False,supports=lambda *a:True)
        _, router = build_session_routers(local,local,load_engine_settings(config_path),
            pair=(language,target),on_event=lambda *args: None, offline_only=offline_only)
        return router

    def request(self):
        if not self.options["enabled"].get() or not self.context or not self.somewhere_visible():
            return
        self.generation += 1
        self.request_stop.set()
        stop = self.request_stop = threading.Event()
        generation, language, target = self.generation,self.language,self.target
        context, variety = [text for _,text in self.context],self.app.variety_var.get()
        config_path, offline_only, preview = self.app.preferences.path, self.app.offline_only_var.get(), self.app.preview_mode
        self.busy = True
        self.status.set("Suggesting replies…")
        self.render()
        def work():
            from engines.cancellation import generation_scope, GenerationCancelled
            try:
                with generation_scope(stop):
                    translator = self.translator(language, target, config_path, offline_only, preview)
                    result = ReplyService(translator).suggest(context,language,target,variety=variety)
            except GenerationCancelled:
                return
            except Exception:
                result = ReplyService().suggest(context,language,target,variety=variety)
            if stop.is_set():
                return
            def finish():
                if generation != self.generation or not self.options["enabled"].get():
                    return
                self.replies = result.replies
                self.busy = False
                self.status.set("Quick replies · free" if result.provider == "phrasebook" else "Short replies · usage included in your budget")
                if not self.replies:
                    self.status.set("No quick replies are available for this language.")
                self.render()
            post(self.app,finish)
        threading.Thread(target=work,daemon=True).start()

    def render(self):
        signature = (self.replies, self.visible_var.get(), self.options["enabled"].get(),
                     self.options["show_native"].get(), bool(self.context), self.busy, self.language, self.target)
        if signature == self.main_signature:
            self.render_overlay()
            return
        self.main_signature = signature
        for child in self.frame.winfo_children():
            child.destroy()
        if (not self.replies and not self.context) or not self.visible_var.get() or not self.options["enabled"].get():
            self.frame.grid_remove()
        else:
            self.frame.grid(row=9,column=0,sticky="ew")
            header = tk.Frame(self.frame,bg=self.colors["bg"])
            header.pack(fill="x",pady=px((0,8)))
            tk.Label(header,textvariable=self.status,bg=self.colors["bg"],fg=self.colors["secondary"],font=("Segoe UI",8)).pack(side="left")
            ttk.Button(header,text="Hide",command=lambda:self.visible_var.set(False),style="Mac.TButton").pack(side="right")
            ttk.Button(header,text="Suggest replies" if not self.replies else "More",command=self.show_and_request,
                       state="disabled" if self.busy else "normal",style="Mac.TButton").pack(side="right",padx=px(6))
            if not self.status.get():
                self.status.set("Suggestions appear after questions. Request replies for any line.")
            cards = tk.Frame(self.frame,bg=self.colors["bg"])
            cards.pack(fill="x")
            for index, reply in enumerate(self.replies):
                card = tk.Frame(cards,bg=self.colors["surface_2"],highlightthickness=px(1),highlightbackground=self.colors["border"],padx=px(10),pady=px(8))
                card.grid(row=0,column=index,sticky="nsew",padx=px((0,8)))
                cards.columnconfigure(index,weight=1,uniform="replies")
                tk.Label(card,text=f"{index+1}  {reply.spoken}",bg=self.colors["surface_2"],fg=self.colors["text"],font=("Segoe UI Semibold",10),wraplength=px(210),justify="left",anchor="w").pack(fill="x")
                tk.Label(card,text=wrap_text(display_text(reply.meaning),self.target,18),bg=self.colors["surface_2"],fg=self.colors["secondary"],font=(font_family(self.target),9),wraplength=px(210),justify="left",anchor="w").pack(fill="x",pady=px((4,0)))
                if self.options["show_native"].get() and reply.romanized:
                    tk.Label(card,text=wrap_text(display_text(reply.native),self.language,18),bg=self.colors["surface_2"],fg=self.colors["tertiary"],font=(font_family(self.language),9),wraplength=px(210)).pack(fill="x")
                self.card_actions(card,index)
        self.render_overlay()

    def card_actions(self, card, index):
        row = tk.Frame(card,bg=self.colors["surface_2"])
        row.pack(fill="x",pady=px((6,0)))
        binding = self.app.hotkey_vars.get(f"reply_{index+1}")
        tk.Label(row,text=binding.get() if binding else "",bg=self.colors["surface_2"],fg=self.colors["tertiary"],font=("Segoe UI",8)).pack(side="left")
        ttk.Button(row,text="Say",command=lambda:self.say(index),style="Mac.TButton").pack(side="right")

    def render_overlay(self):
        overlay = self.app.subtitle_controller.overlay
        if overlay is None:
            return
        signature = (self.replies,self.options["enabled"].get(),self.options["show_on_overlay"].get(),
            self.app.subtitles_enabled_var.get(),overlay.option("text_size",24),self.busy,bool(self.context),
            getattr(overlay,"layout_width",px(720)))
        overlay._reply_pinned = all(signature[1:4]) and self.busy
        if signature == self.overlay_signature:
            return
        self.overlay_signature = signature
        if all(signature[1:4]) and (self.replies or self.busy):
            overlay.updated = overlay.clock()
        tray = overlay.reply_tray
        for child in tray.winfo_children():
            child.destroy()
        if (not self.replies and not self.context) or not all(signature[1:4]):
            tray.pack_forget()
            overlay.fit_to_monitor()
            return
        tray.pack(fill="x",pady=px((6,0)))
        if not self.replies:
            tk.Label(tray,textvariable=self.status,bg=self.colors["black"],fg=self.colors["secondary"],
                     wraplength=max(px(120),signature[-1]-px(160)),font=("Segoe UI",9)).pack(side="left",fill="x",expand=True)
            ttk.Button(tray,text="Suggest replies",command=self.show_and_request,
                       state="disabled" if self.busy else "normal",style="Mac.TButton").pack(side="right")
        for index, reply in enumerate(self.replies):
            card = tk.Frame(tray,bg=self.colors["black"],padx=px(8))
            card.grid(row=0,column=index,sticky="nsew")
            tray.columnconfigure(index,weight=1,uniform="reply-tray")
            size = max(9,round(overlay.option("text_size",24)*.4))
            wrap = max(px(40), (signature[-1] - px(48)) // len(self.replies) - px(16))
            tk.Button(card,text=f"{index+1}  {reply.spoken}",command=lambda i=index:self.say(i),bg=self.colors["black"],
                fg=self.colors["text"],activebackground=self.colors["field"],activeforeground=self.colors["text"],relief="flat",bd=0,
                font=("Segoe UI Semibold",size),wraplength=wrap,anchor="w",justify="left").pack(fill="x")
            tk.Label(card,text=wrap_text(display_text(reply.meaning),self.target,18),bg=self.colors["black"],fg=self.colors["secondary"],font=(font_family(self.target),max(8,size-1)),
                wraplength=wrap,anchor="w",justify="left").pack(fill="x")
        overlay.fit_to_monitor()

    def show_and_request(self):
        if not self.context:
            self.status.set("Listen to a line first, then request replies.")
            return
        if not self.somewhere_visible():
            self.app.show_main_window()
            self.visible_var.set(True)
            self.app.root.after_idle(self.request)
            return
        if self.app.root.winfo_viewable() and self.app.root.state() != "iconic":
            self.visible_var.set(True)
        self.request()

    def say(self, index):
        if not 0 <= index < len(self.replies) or not self.somewhere_visible():
            return
        reply = self.replies[index]
        output = self.app.speak_output_var.get()
        if not output:
            self.app.root.clipboard_clear()
            self.app.root.clipboard_append(reply.spoken)
            self.status.set("Copied the readable reply. Set a Speak output to say it.")
        else:
            from speech_output import SpeechOutputPlayer
            if self.reply_player is None or self.reply_player.output_device_name != output:
                self.stop_speaking()
                self.reply_player = SpeechOutputPlayer(output_device_name=output,monitor=self.app.monitor_var.get(),
                    synthesizer=self.app.synthesizer,on_event=self.app.on_event)
            self.reply_player.enqueue(reply.native,self.language,self.app.voice_var.get())
            self.status.set(f"Saying reply {index+1}")

    def stop_speaking(self):
        if self.reply_player:
            self.reply_player.stop(join_timeout=0)

    def close(self):
        self.generation += 1
        self.request_stop.set()
        self.stop_speaking()


def page(app, colors):
    from engine_ui import heading, field
    from ui_widgets import Switch
    parent, controller = app.settings_shell.contents["Languages"], app.reply_controller
    heading(parent,"Reply suggestions","Automatic suggestions appear after questions. Use Suggest replies or the reply shortcut for any line. Quick replies work without an extra model.",colors)
    row = tk.Frame(parent,bg=colors["bg"])
    row.pack(fill="x",pady=px(8))
    tk.Label(row,text="Suggest short replies",bg=colors["bg"],fg=colors["text"]).pack(side="left")
    Switch(row,controller.options["enabled"],colors).pack(side="right")
    field(parent,"Suggest",controller.options["trigger"],colors,("question","hotkey"))
    for key,label in (("show_native","Show the native script as well"),("show_on_overlay","Show suggestions on the subtitle bar")):
        tk.Checkbutton(parent,text=label,variable=controller.options[key],**{**app._checkbutton_options(),"bg":colors["bg"]}).pack(anchor="w",pady=px(6))
    tk.Checkbutton(parent,text="Show reply strip in the main window",variable=controller.visible_var,
        **{**app._checkbutton_options(),"bg":colors["bg"]}).pack(anchor="w",pady=px(6))
