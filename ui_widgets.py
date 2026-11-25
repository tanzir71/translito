"""Compact native Tk controls matching the shared Figma tokens."""
import tkinter as tk


class Switch(tk.Canvas):
    def __init__(self, parent, variable, colors, *, command=None):
        super().__init__(parent, width=34, height=20, bg=parent.cget("bg"), highlightthickness=0,
                         takefocus=True, cursor="hand2")
        self.variable, self.colors, self.command = variable, colors, command
        self.token = variable.trace_add("write", lambda *_: self.draw())
        self.bind("<Button-1>", self.toggle)
        self.bind("<space>", self.toggle)
        self.bind("<Return>", self.toggle)
        self.bind("<Destroy>", lambda event: variable.trace_remove("write", self.token) if event.widget is self else None)
        self.draw()

    def toggle(self, _event=None):
        self.variable.set(not self.variable.get())
        if self.command:
            self.command()
        return "break"

    def draw(self):
        self.delete("all")
        on = self.variable.get()
        color = self.colors["blue" if on else "field"]
        self.create_rectangle(10, 0, 24, 20, fill=color, outline="")
        for left in (0, 14):
            self.create_oval(left, 0, left+20, 20, fill=color, outline="")
        left = 16 if on else 2
        self.create_oval(left, 2, left+16, 18, fill=self.colors["on_accent"], outline="")
