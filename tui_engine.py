import os
import sys
import time
import threading

WINDOWS = sys.platform == "win32"

# ---------------- INPUT ----------------
if WINDOWS:
    import msvcrt

    def get_key():
        if msvcrt.kbhit():
            try:
                return msvcrt.getch().decode()
            except:
                return None
        return None

else:
    import termios, tty, select

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    tty.setcbreak(fd)

    def get_key():
        dr, _, _ = select.select([sys.stdin], [], [], 0)
        if dr:
            return sys.stdin.read(1)
        return None


# ---------------- SCREEN BUFFER ----------------
class Screen:
    def __init__(self):
        self.lines = []

    def clear(self):
        self.lines = []

    def draw(self, text=""):
        self.lines.append(text)

    def render(self):
        os.system("cls" if WINDOWS else "clear")
        print("\n".join(self.lines))


screen = Screen()


# ---------------- INPUT THREAD ----------------
class InputHandler:
    def __init__(self):
        self.running = True
        self.last_key = None
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        while self.running:
            k = get_key()
            if k:
                self.last_key = k
            time.sleep(0.01)

    def get(self):
        k = self.last_key
        self.last_key = None
        return k

    def stop(self):
        self.running = False


# ---------------- CLEANUP ----------------
def restore_terminal():
    if not WINDOWS:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


# ---------------- MAIN LOOP ----------------
def run_tui(update_callback, fps=30):
    """
    Calls update_callback(screen, key) every frame.
    Return True to exit the loop.
    """
    inp = InputHandler()
    delay = 1 / fps

    try:
        while True:
            key = inp.get()
            screen.clear()

            if update_callback(screen, key):
                break

            screen.render()
            time.sleep(delay)

    finally:
        inp.stop()
        restore_terminal()
        os.system("cls" if WINDOWS else "clear")
        print("Exited cleanly.")
