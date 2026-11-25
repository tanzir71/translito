"""The Figma settings shell: 188px sidebar and one scrollable page at a time."""
import tkinter as tk

PAGE_GROUPS = (("Translation", ("Languages", "Engine", "Cost & usage")),
               ("On screen", ("Subtitles", "Schedule")),
               ("System", ("Audio", "Models", "General")))
SECTION_PAGES = {"General": "General", "Hotkeys": "General", "Transcripts": "General",
    "Bilingual conversation": "Languages", "Advanced one-way pair": "Languages",
    "Speech Recognition": "Models", "Translation engine": "Engine", "Local translation": "Models",
    "Capture": "Audio", "Speak Mode": "Audio"}


class SettingsShell:
    def __init__(self, window, colors, scroll_class, *, initial="Languages", on_page=lambda name: None):
        self.colors, self.on_page = colors, on_page
        body = tk.Frame(window, bg=colors["bg"])
        body.pack(fill="both", expand=True)
        sidebar = tk.Frame(body, bg=colors["surface"], width=188, padx=10, pady=6)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Frame(body, bg=colors["separator"], width=1).pack(side="left", fill="y")
        self.host = tk.Frame(body, bg=colors["bg"])
        self.host.pack(side="left", fill="both", expand=True)
        self.pages, self.buttons, self.contents = {}, {}, {}
        for heading, pages in PAGE_GROUPS:
            tk.Label(sidebar, text=heading, bg=colors["surface"], fg=colors["tertiary"],
                     anchor="w", font=("Segoe UI", 8)).pack(fill="x", padx=10, pady=(12, 4))
            for page in pages:
                button = tk.Button(sidebar, text=page, command=lambda p=page: self.show(p),
                    bg=colors["surface"], fg=colors["secondary"], activebackground=colors["surface_2"],
                    activeforeground=colors["text"], relief="flat", borderwidth=0, anchor="w",
                    padx=10, pady=7, font=("Segoe UI", 10), cursor="hand2", takefocus=True)
                button.pack(fill="x", pady=1)
                self.buttons[page] = button
                scroll = scroll_class(self.host, background=colors["bg"])
                scroll.content.configure(padx=26, pady=22)
                self.pages[page], self.contents[page] = scroll, scroll.content
        self.show(initial if initial in self.pages else "Languages")

    def show(self, name):
        for page, widget in self.pages.items():
            widget.pack_forget()
            self.buttons[page].configure(bg=self.colors["surface_2"] if page == name else self.colors["surface"],
                                        fg=self.colors["text"] if page == name else self.colors["secondary"])
        self.pages[name].pack(fill="both", expand=True)
        self.current = name
        self.on_page(name)

    def section_parent(self, title):
        return self.contents[SECTION_PAGES.get(title, title if title in self.contents else "General")]
