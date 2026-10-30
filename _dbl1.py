
import io
p = r'C:\Users\nickd\Downloads\Project_AI\opencode_provider_manager.py'
s = io.open(p, encoding='utf-8').read()

# 1) wnd_proc различает типы клика
s = s.replace('''                    if msg == self.WM_TRAYICON:
                        low = int(lparam) & 0xFFFF
                        if low in (self.WM_RBUTTONUP,
                                   self.WM_LBUTTONUP,
                                   self.WM_LBUTTONDBLCLK):
                            self._pending_menu = True
                            return 0''',
'''                    if msg == self.WM_TRAYICON:
                        low = int(lparam) & 0xFFFF
                        if low == self.WM_RBUTTONUP:
                            self._pending_menu = True
                            return 0
                        if low == self.WM_LBUTTONDBLCLK:
                            self._pending_dblclick = True
                            return 0
                        if low == self.WM_LBUTTONUP:
                            # может стать двойным кликом — решает главный поток
                            self._pending_single = True
                            return 0''')

# 2) опрос: одиночный клик -> меню через задержку; двойной -> развернуть/свернуть
s = s.replace('''    def _start_menu_pump(self):
        """Опрашивает флаг из оконной процедуры в главном потоке Tk."""
        try:
            if getattr(self, "_pending_menu", False):
                self._pending_menu = False
                self._build_and_show_menu()
        except Exception:
            pass
        try:
            self.app.root.after(120, self._start_menu_pump)
        except Exception:
            pass''',
'''    def _start_menu_pump(self):
        """Опрашивает флаги из оконной процедуры в главном потоке Tk.

        Левый клик  — открыть меню (с задержкой, чтобы отличить двойной);
        двойной левый — развернуть/свернуть окно программы;
        правый клик — меню.
        """
        try:
            now = time.monotonic()

            if getattr(self, "_pending_dblclick", False):
                self._pending_dblclick = False
                self._pending_single = False
                self._single_due = 0.0
                self.app.root.after(0, self._toggle_app_window)

            elif getattr(self, "_pending_single", False):
                self._pending_single = False
                self._single_due = now + 0.35   # ждём возможный второй клик

            if self._single_due and now >= self._single_due:
                self._single_due = 0.0
                self._build_and_show_menu()

            if getattr(self, "_pending_menu", False):
                self._pending_menu = False
                self._build_and_show_menu()
        except Exception:
            pass
        try:
            self.app.root.after(60, self._start_menu_pump)
        except Exception:
            pass''')

# 3) инициализация флагов
s = s.replace('''        self._pending_menu = False
        self._start_menu_pump()''',
'''        self._pending_menu = False
        self._pending_single = False
        self._pending_dblclick = False
        self._single_due = 0.0
        self._start_menu_pump()''')

# 4) импорт time
if "\nimport time" not in s:
    s = s.replace("import threading\n", "import threading\nimport time\n", 1)

io.open(p, 'w', encoding='utf-8', newline='').write(s)
print("double-click logic added")
