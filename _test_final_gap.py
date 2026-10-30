
import sys, time
sys.path.insert(0, r'C:\Users\nickd\Downloads\Project_AI')
import importlib.util, tkinter.font as tkfont
spec = importlib.util.spec_from_file_location("m", r'C:\Users\nickd\Downloads\Project_AI\opencode_provider_manager.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
app = m.App(); root = app.root; root.update()
app.aos = m.AOSOverlay(app)
ids = [p["id"] for p in app.profiles]
for n, tag in ((3, "3 профиля"), (2, "2 профиля"), (1, "1 профиль")):
    app.aos.settings["profiles"] = ids[:n]
    app.aos.toggle(True)
    for _ in range(250): root.update(); time.sleep(0.02)
    app.aos.fit_to_content()
    for _ in range(30): root.update(); time.sleep(0.02)
    w = app.aos.win.winfo_width(); h = app.aos.win.winfo_height()
    f_s = tkfont.Font(font=app.aos._row_font); f_b = tkfont.Font(font=app.aos._row_font_big)
    need = 0
    for pid, (val, est) in app.aos._row_labels.items():
        row = val.master
        for ch in row.winfo_children():
            try: need = max(need, f_b.measure(ch.cget("text")), f_s.measure(ch.cget("text")))
            except Exception: pass
    print("%-10s окно %3dx%-3d | текст %3d | отступ справа %2d px" % (tag, w, h, need, w - need))
    app.aos.toggle(False)
app.aos.settings["profiles"] = []
root.after(200, root.destroy); root.mainloop()
