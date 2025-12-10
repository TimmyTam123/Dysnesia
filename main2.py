import os
import sys
import time
import select
import random
import unicodedata
try:
    import curses
    HAVE_CURSES = True
except Exception:
    curses = None
    HAVE_CURSES = False
    # On Windows, try to install the `windows-curses` package automatically
    if sys.platform == "win32":
        try:
            import subprocess
            import importlib
            print("`curses` not found — attempting to install `windows-curses`...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "windows-curses"])
            # try to import again
            curses = importlib.import_module("curses")
            HAVE_CURSES = True
            print("Successfully installed `windows-curses`.")
        except Exception:
            # installation failed — leave HAVE_CURSES False and continue with fallback
            curses = None
            HAVE_CURSES = False
import locale
locale.setlocale(locale.LC_ALL, '')

# Debug: temporarily log raw keys to help diagnose missing admin key presses
DEBUG_KEYLOG = True

# --- CROSS-PLATFORM get_char ---
USING_WINDOWS = sys.platform == "win32"
if USING_WINDOWS:
    import msvcrt

    def get_char():
        if msvcrt.kbhit():
            ch = msvcrt.getch()
            try:
                out = ch.decode()
                try:
                    if DEBUG_KEYLOG:
                        with open("/tmp/dysnesia_keylog.txt", "a") as f:
                            f.write(f"{time.time()}:WIN:{repr(out)}\n")
                except Exception:
                    pass
                return out
            except Exception:
                return None
        return None
else:
    import termios
    import tty

    def get_char():
        dr, _, _ = select.select([sys.stdin], [], [], 0)
        if dr:
            ch = sys.stdin.read(1)
            try:
                if DEBUG_KEYLOG:
                    try:
                        with open("/tmp/dysnesia_keylog.txt", "a") as f:
                            f.write(f"{time.time()}:POSIX:{repr(ch)}\n")
                    except Exception:
                        pass
            except Exception:
                pass
            return ch
        return None

def flush_stdin(timeout=0.01):
    """Drain any pending bytes from stdin to avoid leftover escape sequences."""
    try:
        if USING_WINDOWS:
            # drain msvcrt buffer
            import msvcrt
            start = time.time()
            while time.time() - start < timeout:
                if not msvcrt.kbhit():
                    break
                try:
                    msvcrt.getch()
                except Exception:
                    break
        else:
            while True:
                dr, _, _ = select.select([sys.stdin], [], [], timeout)
                if not dr:
                    break
                # read and discard
                try:
                    sys.stdin.read(1024)
                except Exception:
                    break
    except Exception:
        pass

def display_width(s):
    w = 0
    for ch in s:
        if unicodedata.combining(ch):
            continue
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            w += 2
        else:
            w += 1
    return w

# record last printed map top row so mouse clicks can be interpreted correctly
map_last_top_row = 1
# toggle on-screen zone debug markers
SHOW_ZONE_DEBUG = False

def get_cursor_position(timeout=0.05):
    """Query terminal for current cursor position. Returns (row, col) or None on failure."""
    # DSR - Device Status Report (CPR)
    # Not reliable on Windows consoles; only attempt on POSIX
    if USING_WINDOWS or not hasattr(sys.stdin, 'fileno'):
        return None
    try:
        sys.stdout.write('\x1b[6n')
        sys.stdout.flush()
        resp = ''
        start = time.time()
        while time.time() - start < timeout:
            dr, _, _ = select.select([sys.stdin], [], [], timeout)
            if dr:
                c = sys.stdin.read(1)
                resp += c
                if c == 'R':
                    break
        if resp.startswith('\x1b[') and resp.endswith('R'):
            body = resp[2:-1]
            parts = body.split(';')
            if len(parts) == 2:
                return int(parts[0]), int(parts[1])
    except Exception:
        pass
    return None


# --- Curses helpers for reduced-flicker rendering ---
def sanitize_for_curses(s):
    out = []
    for ch in s:
        try:
            if unicodedata.combining(ch):
                continue
            if unicodedata.east_asian_width(ch) in ("W", "F"):
                out.append('?')
            else:
                out.append(ch)
        except Exception:
            out.append('?')
    return ''.join(out)


def init_curses_window(win):
    """Initialize curses window for smoother drawing."""
    try:
        curses.noecho()
    except Exception:
        pass
    try:
        curses.curs_set(0)
    except Exception:
        pass
    try:
        win.keypad(True)
    except Exception:
        pass
    try:
        win.nodelay(True)
    except Exception:
        pass
    try:
        curses.use_default_colors()
    except Exception:
        pass
    # attach a simple last-screen buffer to the window object
    try:
        maxy, maxx = win.getmaxyx()
        if not hasattr(win, '_last_screen') or len(win._last_screen) != maxy:
            win._last_screen = [''] * maxy
    except Exception:
        pass


def safe_addstr(win, y, x, text, attr=0):
    """Try to add text; on failure sanitize and retry with fewer risky chars.
    This replaces the previous platform-specific per-char fallbacks for speed."""
    try:
        win.addstr(y, x, text, attr)
        return
    except Exception:
        pass

    san = sanitize_for_curses(text)
    try:
        win.addstr(y, x, san, attr)
        return
    except Exception:
        pass

    # final fallback: write in small chunks to reduce per-char overhead
    try:
        chunk = ''
        for ch in san:
            chunk += ch
            if len(chunk) >= 8:
                try:
                    win.addstr(y, x + len(chunk) - len(chunk), chunk, attr)
                except Exception:
                    pass
                chunk = ''
        if chunk:
            try:
                win.addstr(y, x + len(text) - len(chunk), chunk, attr)
            except Exception:
                pass
    except Exception:
        pass


def render_line(win, y, text):
    """Render a single line only if it changed (line-diffing)."""
    try:
        maxy, maxx = win.getmaxyx()
    except Exception:
        return
    if y < 0 or y >= maxy:
        return
    # create a padded version so we clear any leftover characters from previous content
    line = text[:maxx-1]
    try:
        line_padded = line.ljust(maxx-1)
    except Exception:
        line_padded = line
    last = getattr(win, '_last_screen', None)
    if last is None:
        try:
            win._last_screen = [''] * maxy
            last = win._last_screen
        except Exception:
            last = None
    if last is not None and last[y] == line_padded:
        return
    try:
        safe_addstr(win, y, 0, line_padded)
        if last is not None:
            last[y] = line_padded
    except Exception:
        pass


def present_frame(win):
    """Batch refresh using noutrefresh()/doupdate() when available."""
    try:
        win.noutrefresh()
        curses.doupdate()
    except Exception:
        try:
            win.refresh()
        except Exception:
            pass


def research_view():
    """Handle the research page: only redraw when money increases or research bought."""
    global money, timea, page, world, research_needs_update, last_money_for_research
    # initial render
    need_render = True
    if last_money_for_research is None:
        need_render = True

    while world == 1 and page == 1:
        if need_render:
            clear()
            if not research_page_unlocked:
                print("Research not unlocked yet.")
            else:
                print(f"Money: {money:.2f}\n")
                print("=== RESEARCH ===\n")
                draw_research_tree()
                for res in research:
                    st = "— COMPLETED" if res["purchased"] else f"| Cost: ${res['cost']}"
                    print(f"[{res['key']}] {res['name']} {st}")
            if research_page_unlocked:
                print("\nPress [R] to switch pages.")
            last_money_for_research = money
            research_needs_update = False
            need_render = False

        # handle input and money ticks locally so we don't redraw unnecessarily
        key = get_key()
        timea += 0.1
        if timea >= 1:
            money += rate * adminmultiplier * othermultiplier
            timea = 0.0
            research_needs_update = True

        if key:
            k = key.lower()
            if k == 'k':
                if world == 1:
                    glitch_transition()
                    world = 2
            elif k == 'q':
                # ignore 'q' — do not quit the game
                pass
            elif k == 'r' and research_page_unlocked:
                page = 0
                return
            else:
                for r in research:
                    if k == r["key"]:
                        buy_research(r)
                        research_needs_update = True
                        need_render = True
                        break

        # decide if we need to re-render due to money change or purchases
        if research_needs_update or (last_money_for_research is not None and money > last_money_for_research):
            need_render = True

        time.sleep(0.1)


def kill_list_view():
    """Render the World 4 kill list once and only re-render when it changes.
    Blocks until the user presses [K] to go back to the map or [Q] to quit."""
    global world, killed_monsters
    last_snapshot = None
    need_render = True
    while world == 4:
        if need_render:
            clear()
            print("=== KILL LIST ===\n")
            print("Monsters killed:\n")
            if killed_monsters:
                for i, name in enumerate(killed_monsters, start=1):
                    print(f"{i}. {name}")
            else:
                print("[No kills yet]\n")
            print("\nPress [K] to go back to Map.")
            last_snapshot = list(killed_monsters)
            need_render = False

        key = get_key()
        if key:
            k = key.lower()
            if k == 'k':
                world = 2
                return
            elif k == 'q':
                # ignore 'q' — do not quit
                pass

        # Re-render if the kill list changed while viewing
        if killed_monsters != last_snapshot:
            need_render = True

        time.sleep(0.1)


def home_view():
    """Render World 1 main city/upgrades page only when state changes."""
    global money, timea, page, world, w1upgrades
    last_money = None
    last_upgrades = None
    need_render = True

    while world == 1 and page == 0:
        if need_render:
            clear()
            print(f"Money: {money:.2f}\n")
            update_building_heights(w1upgrades)
            draw_city()

            print("\n=== UPGRADES ===")
            any_seen = False
            for upg in upgrades:
                if money >= upg["cost"] * 0.1:
                    upg["seen"] = True
                if upg["seen"]:
                    any_seen = True
                    status = (
                        f"+{upg['rate_inc']}/sec | Cost: ${upg['cost']}"
                        if upg["count"] < upg["max"] else "MAXED"
                    )
                    print(f"[{upg['key'].upper()}] {upg['name']} ({upg['count']}/{upg['max']}) {status}")
            if not any_seen:
                print("(No upgrades available yet...)")
            if research_page_unlocked:
                print("\nPress [R] to go to Research.")
            if technology_page_unlocked:
                print("Press [T] to go to Technology.")
            sanity = 20 - w1upgrades
            bar = int((sanity / 20) * length)
            print("\n[" + "#" * bar + " " * (length - bar) + "]\n")

            last_money = money
            last_upgrades = w1upgrades
            need_render = False

        # update money timer (don't force redraw here; render only when value changed)
        timea += 0.1
        if timea >= 1:
            money += rate * adminmultiplier * othermultiplier
            timea = 0.0

        key = get_key()
        if key:
            k = key.lower()
            if k == 'k':
                world = 2
                return
            elif k == 'q':
                # ignore 'q' — do not quit
                pass
            elif k == 'r' and research_page_unlocked:
                page = 1
                return
            elif k == 't' and technology_page_unlocked:
                page = 2
                return
            else:
                for upg in upgrades:
                    if k == upg["key"]:
                        buy_upgrade(upg)
                        need_render = True
                        break

        # re-render if money or upgrades changed externally
        if money != last_money or w1upgrades != last_upgrades:
            need_render = True

        time.sleep(0.1)


def mining_view():
    """Render mining page only when relevant state changes."""
    global money, timea, page, world, current_ore, ore_hp, depth
    last_money = None
    last_ore_hp = None
    last_depth = None
    need_render = True

    while world == 1 and page == 2:
        if not technology_page_unlocked:
            clear()
            print("Mining not unlocked yet.")
            print("\nPress [R] to return to City")
            key = get_key()
            if key and key.lower() == 'r':
                page = 0
                return
            time.sleep(0.1)
            continue

        # time and auto-mining
        timea += 0.1
        if timea >= 1:
            money += rate * adminmultiplier * othermultiplier
            auto_mine_tick()
            timea = 0.0
            need_render = True

        if need_render:
            clear()
            # Left column
            print(f"Money: ${money:.2f}")
            print("")
            if current_ore is None:
                spawn_new_ore()
            draw_mine_shaft()

            # Right column: technology list
            print("=== TECHNOLOGY ===")
            available = []
            for tech in technology:
                if not tech.get("purchased"):
                    available.append(tech)
            if not available:
                print("(None available)")
            else:
                for tech in available:
                    ore_costs = " ".join(f"{n[:3]}:{a}" for n, a in tech.get("ore_costs", {}).items())
                    print(f"[{tech['key'].upper()}] {tech['name']} - {ore_costs} | ${tech['money_cost']}")

            last_money = money
            last_ore_hp = ore_hp
            last_depth = depth
            need_render = False

        key = get_key()
        if key:
            k = key.lower()
            if k == ' ':
                mine_ore()
                need_render = True
            elif k == 'k':
                glitch_transition()
                world = 2
            elif k == 'q':
                # ignore 'q' — do not quit
                pass
            elif k == 'z':
                # ADMIN BUTTON (debug): give 50 of each ore when pressed in Mining
                try:
                    for ore_name in ore_inventory:
                        ore_inventory[ore_name] += 50
                    need_render = True
                except Exception:
                    pass
            elif k == 'r':
                page = 0
                return
            elif k in '12345':
                new_depth = int(k)
                if new_depth <= max_depth:
                    depth = new_depth
                    spawn_new_ore()
                    # TRIGGER: When reaching depth 4, award sanity and send to World 2
                    if depth == 4:
                        try:
                            award_sanity_event('depth_4_reach')
                            try:
                                trigger_send_to_world2('mining', depth)
                            except Exception:
                                trigger_send_to_world2('mining')
                        except Exception:
                            pass
                    need_render = True
            else:
                for tech in technology:
                    if k == tech["key"]:
                        buy_technology(tech)
                        need_render = True
                        break

        if money != last_money or ore_hp != last_ore_hp or depth != last_depth:
            need_render = True

        time.sleep(0.1)

# --- GAME STATE ---
world = 1
timea = 0.0
money = 0
rate = 1
adminmultiplier = 10
othermultiplier = 1.0
page = 0
research_page_unlocked = False
technology_page_unlocked = False
w1upgrades = 0
length = 40
player_level = 1

# --- BLACK HOLE / WORLD1 ALTERNATE PAGE ---
# Locked by default; unlocked by completing mining end or admin button
blackhole_page_unlocked = False
blackhole_page_first_visit = False  # Track first BH page visit for sanity award
admin_ore_granted_msg = ""  # Message to display when admin button is pressed
blackhole_growth = 0
blackhole_upgrades_count = 0
ships_count = 0
blackhole_unlock_cost = 5000000000


def ships_money_multiplier():
    """Return a multiplier for money based on ships_count. 5% per ship."""
    try:
        return 1.0 + ships_count * 0.05
    except Exception:
        return 1.0

# research rendering state
last_money_for_research = None
research_needs_update = True

# --- SANITY / PROGRESSION STATE ---
# Sanity accumulates from upgrades on a rotating active page. When full,
# the player is sent to world 2. After returning, the active page rotates.
sanity_points = 0
# larger sanity scale (player sees a ~0-200 bar instead of tiny 0-5)
SANITY_TARGET = 200
# stages: 0=city upgrades,1=research,2=mining,3=blackhole final
sanity_stage = 0
# per-stage increments (how many points a normal purchase gives when that
# page is the active sanity contributor)
SANITY_INCREMENTS = {
    'city': 4,
    'research': 12,
    'technology': 8,
    'blackhole': 20,
}
# one-off event amounts (milestones)
SANITY_EVENT_AMOUNTS = {
    'mine_half': 25,
    'bh_unlock': 40,
    'bh_finish': 80,
}
SANITY_WEIGHTS = [1, 1, 2, 1]
# when true we have sent player to world2 and await their return to rotate stage
awaiting_cycle_return = False
cycle_return_applied = False
# remember what caused the send so we can pick the next active sanity stage
last_send_cause = None
# remember the depth at which we triggered the send (if applicable)
last_send_depth = None
# one-time sanity event awards to align progression milestones
sanity_awarded = {
    'research_unlock': False,
    'tech_unlock': False,
    'mine_half': False,
    'bh_unlock': False,
    'bh_finish': False,
    'post_depth3_return': False,
}


def award_sanity_event(ev_key):
    """Award one sanity point for a named event once.

    Events: 'research_unlock','tech_unlock','mine_half','bh_unlock','bh_finish'
    """
    global sanity_awarded
    if sanity_awarded.get(ev_key):
        return
    sanity_awarded[ev_key] = True
    try:
        # award different amounts for milestone events when defined
        amt = SANITY_EVENT_AMOUNTS.get(ev_key, 1) if 'SANITY_EVENT_AMOUNTS' in globals() else 1
        add_sanity(amt)
    except Exception:
        try:
            global sanity_points
            sanity_points += SANITY_EVENT_AMOUNTS.get(ev_key, 1) if 'SANITY_EVENT_AMOUNTS' in globals() else 1
        except Exception:
            pass


def add_sanity(amount=1):
    """Add sanity points and trigger world2 transition if full."""
    global sanity_points, SANITY_TARGET
    try:
        sanity_points += int(amount)
    except Exception:
        try:
            sanity_points += int(float(amount))
        except Exception:
            sanity_points += 1
    # cap at SANITY_TARGET, but do NOT auto-send to world2 here.
    # The player should be sent to World 2 only when explicitly unlocking Research.
    if sanity_points >= SANITY_TARGET:
        sanity_points = SANITY_TARGET


def trigger_send_to_world2(cause=None, depth=None):
    """Send the player to world 2 and mark that we await their return.

    Args:
        cause (str|None): optional hint about what triggered the send
            (e.g. 'mining', 'research', 'blackhole'). Used to pick the
            next active sanity stage when the player returns.
    """
    global world, awaiting_cycle_return, cycle_return_applied, last_send_cause
    try:
        glitch_transition()
        world = 2
    except Exception:
        pass
    awaiting_cycle_return = True
    cycle_return_applied = False
    last_send_cause = cause
    global last_send_depth
    try:
        last_send_depth = int(depth) if depth is not None else None
    except Exception:
        last_send_depth = None

# --- MINING STATE ---
current_ore = None
ore_hp = 100
ore_max_hp = 100
ore_damage = 10
auto_mine_damage = 0
depth = 1
max_depth = 1

# --- COMBAT STATE ---
combat_started = False
player_hp = 100
player_max_hp = 100
enemy_hp = 80
enemy_max_hp = 80
player_heals = 3
combat_log = []
player_ability_charges = 1

# --- MONSTER / KILL LIST ---
MONSTER_NAMES = [
    "Adam", "Boreal Wisp", "Cinderhound", "Dreadling", "Elder Faun",
    "Fangrat", "Gloomrot", "Hollow Stalker", "Ironclad Beetle",
    "Jaded Lurker", "Kelvin", "Lurking Shade", "Mire Serpent",
    "Nether Imp", "Oaken Brute", "Pestilent Rat", "Quarry Golem",
    "Ravaged Soldier", "Sable Wolf", "Terivon", "Umber Bat",
    "Vicious Spriggan", "Wretched Ghoul", "Xylophant", "Yawning Horror",
    "Zereth"
]
killed_monsters = []
current_enemy_name = None
current_enemy_region = None

# --- MAP ART (UPDATED MAP WITH GRAVEYARD NEAR TOP) ---
map_art = [
"                                   N",
"                                   ^",
"                                   |",
"                           ~ ~ ~ ~ | ~ ~ ~ ~ ~     ",
"         WHISPERING PINES     ~ ~  |  ~ ~         /\\        ",
"         /\\   /\\    /\\      ~ ~ ~  |    /\\   /  \\    /\\ ",
"       /  \\ /  \\  /  \\  ~ ~ ~ ~ ~  |   /  \\_/    \\__/  \\",
"      /    \\/    \\/    \\           |  /                  \\",
"     /    FOREST TRAIL    \\         | /   SILENT GRAVEYARD \\",
"    /                      \\        |/    ╔══════════════╗  \\",
"   /________________________\\       /\\    ║  XX X XXX  X ║   \\",
"                             \\     /  \\   ║   X XX    X   ║    \\",
"                              \\   /    \\  ║ XX X XXX X X  ║     \\",
"                               \\ /      \\ ╚══════════════╝      \\",
"                                |                    \\            \\",
"                                |                     \\            \\",
"                                |      HOLLOWED        \\            \\",
"                                |       FARMLANDS       |=========|",
"                                |       _____   ___     |   ||    |",
"                                |______/     \\_/   \\____|   ||    |",
"                                   | (//////////)       |   ||    |",
"                                   |                     |   ||    |",
"                                   |         SUNKEN      |   ||    |",
"                                   |       MARKETPLACE   |   ||    |",
"                 OLD RESIDENTIAL  |   ~~~~~~   ~~~~~~   |   ||    |",
"                     DISTRICT     |  / shops \\ / stalls\\ |   ||    |",
"               +----+   +----+    |                          ||    |",
"               |H01 |---|H02 |    |--------------------------||----|",
"               +----+   +----+    |                          ||",
"                 |            alleys         |                ||",
"                 |                            \\              ||",
"                 |                             \\             ||",
"                 |            MIRROR MARSH      \\            ||",
"                /             ~~~~~~~~~~~~       \\           ||",
"             ~~~   *&^%#$@$!C%!$*@*#*%&@  ~~~      \\          ||",
"                \\__________________________________\\         ||",
"                                 |                            ||",
"                                 |    OBSIDIAN QUARRY         ||",
"                                 |   █████  █████  ████       ||",
"                                 |  █████  █████  ████        ||",
"                                 |____________________________||",
"                                                 |",
"                                                 |",
"                                      FORGOTTEN SANCTUM",
"                                          ▓▓▓▓▓▓▓▓▓▓▓",
"                                         ▓           ▓",
"                                         ▓           ▓",
"                                         ▓           ▓",
"                                          ▓▓▓▓▓▓▓▓▓▓▓",
"                                                 ",
"                           (To Elysea after defeating Terivon)",
]

# clickable labels (all 8 locations + graveyard)
click_labels = {
    "WHISPERING PINES": [],
    "HOLLOWED FARMLANDS": [],
    "CRUMBLING OVERPASS": [],
    "SUNKEN MARKETPLACE": [],
    "MIRROR MARSH": [],
    "OBSIDIAN QUARRY": [],
    "OLD RESIDENTIAL DISTRICT": [],         # label spans two lines: "OLD RESIDENTIAL" + "DISTRICT"
    "FORGOTTEN SANCTUM": [],
    "SILENT GRAVEYARD": []
}

# assign one monster name per region (so each region has a set name)
# Use sequential identifiers so you can edit them manually: enemy_a, enemy_b, ...
region_enemy_map = {}
# Explicit per-region names for important regions (editable)
custom_names = {
    'whispering_pines': 'Shrouded Wanderer',
    'silent_graveyard': 'Fading Crawler',
    'hollowed_farmlands': 'Bent Wraith',
    'sunken_marketplace': 'Drifting Mannequin',
    'old_residential_district': 'Hallway Watcher',
    'mirror_marsh': 'Refracted Shade',
    # forgotten_sanctum will display a dynamic error-like name (None means dynamic)
    'forgotten_sanctum': None,
    'obsidian_quarry': 'Crystalline Husk',
}
for i, lbl in enumerate(click_labels.keys()):
    norm = lbl.lower().replace(" ", "_")
    if norm in custom_names:
        region_enemy_map[norm] = custom_names[norm]
    else:
        # generate a letter sequence (a, b, c, ...). Wrap after 'z' back to 'a'.
        letter = chr(ord('a') + (i % 26))
        region_enemy_map[norm] = f"enemy_{letter}"

# track which regions have been defeated (so each enemy can only be killed once)
defeated_regions = set()

# Dungeon progression order (sequential unlock)
dungeon_progression_order = [
    'whispering_pines',
    'silent_graveyard',
    'hollowed_farmlands',
    'sunken_marketplace',
    'old_residential_district',
    'mirror_marsh',
    'obsidian_quarry',
    'forgotten_sanctum'
]

# Track consecutive defeats for world switching (switch after every 2 defeats)
consecutive_defeats = 0


def get_next_available_dungeon():
    """Return the normalized name of the next dungeon that can be entered based on progression."""
    for region in dungeon_progression_order:
        if region not in defeated_regions:
            return region
    return None  # All dungeons defeated

def locate_labels_in_map(map_lines):
    """
    Finds the first occurrence of each label in the provided map_lines
    and returns a dict mapping normalized names to (row_index_1based, col_index_1based).
    """
    def display_width(s):
        w = 0
        for ch in s:
            if unicodedata.combining(ch):
                continue
            if unicodedata.east_asian_width(ch) in ("W", "F"):
                w += 2
            else:
                w += 1
        return w

    labels_found = {}
    keys = list(click_labels.keys())
    for i, line in enumerate(map_lines, start=1):
        upper = line.upper()
        for key in keys:
            norm = key.lower().replace(" ", "_")
            # exact single-line match
            if key == "OLD RESIDENTIAL":
                target = "OLD RESIDENTIAL"
            else:
                target = key

            if target in upper:
                start_char = upper.index(target)
                col = display_width(line[:start_char]) + 1
                labels_found[norm] = (i, start_char, len(target), 0, col)
                continue

            # try to detect a label split across this line and the next (two-line labels)
            # look ahead one line
            if i < len(map_lines):
                next_line = map_lines[i]
                # build a combined string with a single space between lines to emulate wrapped label
                combined = (line + " "+ next_line).upper()
                if target in combined:
                    # find index in combined and translate back to first/second line indices
                    idx = combined.index(target)
                    # if idx is before len(line), the start is on this line
                    if idx < len(line):
                        start_char = idx
                        # determine how many chars are on the first line
                        first_part = min(len(line) - start_char, len(target))
                        second_part = max(0, len(target) - first_part)
                        col = display_width(line[:start_char]) + 1
                        labels_found[norm] = (i, start_char, first_part, second_part, col)
                        continue
                    else:
                        # starts on next line; record as start on next line
                        start_on_next = idx - (len(line) + 1)
                        start_char = start_on_next
                        first_part = 0
                        second_part = min(len(next_line) - start_char, len(target))
                        col = display_width(next_line[:start_char]) + 1
                        labels_found[norm] = (i+1, start_char, first_part, second_part, col)
                        continue

    return labels_found

def make_absolute_zones(map_lines, map_top_row):
    """
    Given the map text lines and the top row where the map is printed,
    return clickable rectangular zones for each found label.
    """
    labels = locate_labels_in_map(map_lines)
    zones = {}
    pad_col = 2
    pad_row_top = 0
    pad_row_bottom = 0
    for name_key, data in labels.items():
        # data can be (row, start_char_index, first_len, second_len, display_col)
        if len(data) == 5:
            r, start_char, first_len, second_len, display_col = data
        elif len(data) == 4:
            # older format: (row, start_char, key_char_len, display_col)
            r, start_char, first_len, display_col = data
            second_len = 0
        else:
            # fallback
            r = data[0]
            start_char = 0
            first_len = 6
            second_len = 0
            display_col = 1

        # compute display width of the label text, possibly across two lines
        label_len = 0
        line = map_lines[r-1]
        if first_len > 0:
            snippet = line[start_char:start_char+first_len]
            label_len += display_width(snippet)
        if second_len > 0 and r < len(map_lines):
            next_line = map_lines[r]
            snippet2 = next_line[0:second_len]
            label_len += display_width(snippet2)
        if label_len == 0:
            label_len = 6

        row_start = map_top_row + r - 1 - pad_row_top
        row_end = map_top_row + r - 1 + pad_row_bottom
        # if the label spills to the next line, extend row_end
        if second_len > 0:
            row_end = map_top_row + (r) - 1 + 1 - pad_row_top

        zones[name_key] = {
            "row_start": row_start,
            "row_end":   row_end,
            "col_start": max(1, display_col - pad_col),
            "col_end":   display_col + label_len - 1 + pad_col,
        }
    # Hard overrides for known multi-line problematic labels (screen coords)
    # Expand the columns a bit so clicks are easier to hit.
    zones["sunken_marketplace"] = {
        "row_start": 26,
        "row_end": 27,
        "col_start": max(1, 25 - 3 + 20),
        "col_end": min(200, 26 + 8 + 20),
    }
    zones["hollowed_farmlands"] = {
        "row_start": 20,
        "row_end": 21,
        "col_start": max(1, 19 - 3 + 21),
        "col_end": min(200, 20 + 8 + 21),
    }
    # Hard override for OLD RESIDENTIAL DISTRICT (two-line label)
    zones["old_residential_district"] = {
        "row_start": 28,
        "row_end": 29,
        # generous column range to ensure clicks hit the multi-line label
        "col_start": max(1, 15 - 4 + 7),
        "col_end": min(200, 15 + 20),
    }
    return zones

# --- UPGRADE DATA ---
upgrades = [
    {"key": "a", "name": "Hire Worker", "rate_inc": 1, "base_cost": 10,
     "cost": 10, "multiplier": 1.15, "count": 0, "max": 100, "seen": False},
    {"key": "s", "name": "Hire Manager", "rate_inc": 10, "base_cost": 100,
     "cost": 100, "multiplier": 1.15, "count": 0, "max": 75, "seen": False},
    {"key": "d", "name": "Hire Senior Manager", "rate_inc": 100,
     "base_cost": 1000, "cost": 1000, "multiplier": 1.15, "count": 0, "max": 50, "seen": False},
    {"key": "f", "name": "Upgrade Hardware", "rate_inc": 10000,
     "base_cost": 10000, "cost": 10000, "multiplier": 1.15, "count": 0, "max": 30, "seen": False},
    {"key": "g", "name": "Unlock Research", "rate_inc": 0,
     "base_cost": 1000000, "cost": 1000000, "multiplier": 0, "count": 0, "seen": False, "max": 1,},
]
ore_inventory = {
    "stone": 0,
    "coal": 0,
    "iron": 0,
    "copper": 0,
    "silver": 0,
    "gold": 0,
    "emerald": 0,
    "ruby": 0,
    "diamond": 0,
    "mythril": 0,
    "adamantite": 0,
    "orichalcum": 0,
    "orichalcum_shard": 0,  # Depth 5 only; required to unlock Black Hole
}


# --- RESEARCH DATA ---
research = [
    {"key": "1", "name": "Quantum Processors",
     "cost": 500000, "purchased": False,
     "effect": "othermultiplier *= 1.5"},
    {"key": "2", "name": "Nanofabrication Labs",
     "cost": 2000000, "purchased": False,
     "effect": "othermultiplier *= 2.5"},
     {"key": "3", "name": "Adaptive AI Networks",
     "cost": 6000000, "purchased": False,
     "effect": "othermultiplier *= 3"},
    {"key": "4", "name": "Fusion Power Cells",
     "cost": 30000000, "purchased": False,
     "effect": "othermultiplier *= 3.5"},
    {"key": "5", "name": "Smart Infrastructure",
     "cost": 150000000, "purchased": False,
     "effect": "othermultiplier *= 4"},
    {"key": "6", "name": "Synthetic Bio-Alloys",
     "cost": 500000000, "purchased": False,
     "effect": "othermultiplier *= 5"},
    {"key": "7", "name": "Interlinked Drone Swarms",
     "cost": 2000000000, "purchased": False,
     "effect": "othermultiplier *= 10"},
    {"key": "8", "name": "Neural Cloud Integration",
     "cost": 40000000000, "purchased": False,
     "effect": "othermultiplier *= 15"},
    {"key": "9", "name": "Cryogenic Superconductors",
     "cost": 120000000000, "purchased": False,
     "effect": "othermultiplier *= 20"},
    {"key": "0", "name": "Unlock Technology",
     "cost": 1000000000000, "purchased": False,
     "effect": "technology_page_unlocked = True"},
]


# --- ORE TYPES BY DEPTH ---
ore_types = {
    1: [
        {"name": "stone", "color": "░", "hp": 50, "value": 1, "weight": 50},
        {"name": "coal", "color": "▓", "hp": 75, "value": 3, "weight": 30},
        {"name": "copper", "color": "▒", "hp": 100, "value": 5, "weight": 20},
    ],
    2: [
        {"name": "coal", "color": "▓", "hp": 75, "value": 3, "weight": 30},
        {"name": "copper", "color": "▒", "hp": 100, "value": 5, "weight": 25},
        {"name": "iron", "color": "▓", "hp": 150, "value": 10, "weight": 25},
        {"name": "silver", "color": "░", "hp": 200, "value": 20, "weight": 20},
    ],
    3: [
        {"name": "iron", "color": "▓", "hp": 150, "value": 10, "weight": 30},
        {"name": "silver", "color": "░", "hp": 200, "value": 20, "weight": 25},
        {"name": "gold", "color": "█", "hp": 300, "value": 50, "weight": 25},
        {"name": "emerald", "color": "◆", "hp": 400, "value": 100, "weight": 20},
    ],
    4: [
        {"name": "gold", "color": "█", "hp": 300, "value": 50, "weight": 30},
        {"name": "emerald", "color": "◆", "hp": 400, "value": 100, "weight": 25},
        {"name": "ruby", "color": "♦", "hp": 500, "value": 200, "weight": 25},
        {"name": "diamond", "color": "◊", "hp": 750, "value": 500, "weight": 20},
    ],
    5: [
        {"name": "diamond", "color": "◊", "hp": 750, "value": 500, "weight": 30},
        {"name": "mythril", "color": "▲", "hp": 1000, "value": 1000, "weight": 25},
        {"name": "adamantite", "color": "■", "hp": 1500, "value": 2000, "weight": 20},
        {"name": "orichalcum", "color": "★", "hp": 2500, "value": 5000, "weight": 15},
        {"name": "orichalcum_shard", "color": "✶", "hp": 3000, "value": 7500, "weight": 10},
    ],
}

ENEMY_ASCII = {
    'whispering_pines': (
        ["   .--.", "  /../ ", " (  : )", "  | ||", "   --- "],
        ["  .--.  ", " (    ) ", "  ( : )>", "   --- ", "  /___ "]
    ),
    'silent_graveyard': (
        ["   .-.", "  (   )", " ( : ) ", "  /|/", "  /  "],
        ["  ._.", " (o o)", "  -_- ", "  /|/", "  /  "]
    ),
    'hollowed_farmlands': (
        ["   /  ", "  /   ", " (    )", "  |  |", "  /__ "],
        ["   ~~  ", " (.. )", "  ( : )>", "  /  ", "  /___ "]
    ),
    'sunken_marketplace': (
        ["  [====]", "  |::..|", "  |:.. |", "   /   ", "  /____"],
        ["  _____ ", " (_____)", "  ( : )>", "  /   ", "  /___ "]
    ),
    'old_residential_district': (
        ["  |--|", " [____]", "  (..)", "  /|/", "  /__ "],
        ["  /_/_ ", " ( o.o )", "  ( : ) ", "  /   ", "  /___ "]
    ),
    'mirror_marsh': (
        ["   ~~~", "  ~o~ ", " (  : )", "  /   ", " /____"],
        ["  ~~~  ", " ~o~   ", "  ( : )>", "  /   ", " /____" ]
    ),
    'forgotten_sanctum': (
        # normal human ASCII art for the Forgotten Sanctum enemy
        ["   O", "  /|/", "  /  ", "", ""],
        ["   O", "  /|/", "  /  ", "", ""]
    ),
}

def spawn_new_ore():
    """Spawn a new ore based on current depth"""
    global current_ore, ore_hp, ore_max_hp
    
    if depth not in ore_types:
        depth_ores = ore_types[max(ore_types.keys())]
    else:
        depth_ores = ore_types[depth]
    
    # Weighted random selection
    total_weight = sum(ore["weight"] for ore in depth_ores)
    rand = random.randint(1, total_weight)
    
    current_weight = 0
    for ore in depth_ores:
        current_weight += ore["weight"]
        if rand <= current_weight:
            current_ore = ore.copy()
            ore_max_hp = ore["hp"]
            ore_hp = ore_max_hp
            return

def mine_ore():
    """Mine the current ore (manual click)"""
    global ore_hp, ore_inventory, money
    if current_ore is None:
        spawn_new_ore()
        return
    
    ore_hp -= ore_damage
    if ore_hp <= 0:
        # Ore destroyed - add to inventory and spawn new one
        ore_inventory[current_ore["name"]] += 1
        money += current_ore["value"] * adminmultiplier * othermultiplier
        spawn_new_ore()

def auto_mine_tick():
    """Auto miners damage the ore"""
    global ore_hp, ore_inventory, money, auto_mine_damage
    if auto_mine_damage <= 0:
        return
    
    if current_ore is None:
        spawn_new_ore()
        return
    
    ore_hp -= auto_mine_damage
    if ore_hp <= 0:
        ore_inventory[current_ore["name"]] += 1
        money += current_ore["value"] * adminmultiplier * othermultiplier
        spawn_new_ore()
# --- TECHNOLOGY/MINING DATA ---
# Ore inventory

mining_page_unlocked = False
auto_miner_count = 0

technology = [
    # Tier 1 - Basic tools
    {"key": "1", "name": "Stone Pickaxe", "ore_costs": {}, "money_cost": 0, 
     "damage": 15, "auto_damage": 0, "depth_unlock": 0, "purchased": False,
     "effect": "ore_damage += 15", "unlocks": ["2", "3"], "desc": "+15 damage"},
    
    {"key": "2", "name": "Iron Pickaxe", "ore_costs": {"stone": 3}, "money_cost": 100000, 
     "damage": 25, "auto_damage": 0, "depth_unlock": 0, "purchased": False,
     "effect": "ore_damage += 25", "unlocks": ["4", "5"], "desc": "+25 damage"},
    
    {"key": "3", "name": "Hire First Miner", "ore_costs": {"stone": 5, "coal": 3}, "money_cost": 50000, 
     "damage": 0, "auto_damage": 5, "depth_unlock": 0, "purchased": False,
     "effect": "auto_mine_damage += 5; auto_miner_count += 1", "unlocks": ["6"], "desc": "+5 auto damage"},
    
    # Tier 2 - Unlock Depth 2
    {"key": "4", "name": "Deeper Shaft", "ore_costs": {"coal": 5, "copper": 2}, "money_cost": 500000, 
     "damage": 0, "auto_damage": 0, "depth_unlock": 2, "purchased": False,
     "effect": "max_depth = max(max_depth, 2)", "unlocks": ["7", "8"], "desc": "Unlock Depth 2"},
    
    {"key": "5", "name": "Steel Pickaxe", "ore_costs": {"copper": 5, "iron": 2}, "money_cost": 750000, 
     "damage": 50, "auto_damage": 0, "depth_unlock": 0, "purchased": False,
     "effect": "ore_damage += 50", "unlocks": ["9"], "desc": "+50 damage"},
    
    {"key": "6", "name": "Mining Team", "ore_costs": {"coal": 10, "copper": 5}, "money_cost": 1000000, 
    "damage": 0, "auto_damage": 15, "depth_unlock": 0, "purchased": False,
    "effect": "auto_mine_damage += 15; auto_miner_count += 3", "unlocks": ["0"], "desc": "+15 auto damage"},
        
    # Tier 3 - Unlock Depth 3
    {"key": "7", "name": "Reinforced Shaft", "ore_costs": {"iron": 10, "silver": 5}, "money_cost": 5000000, 
     "damage": 0, "auto_damage": 0, "depth_unlock": 3, "purchased": False,
     "effect": "max_depth = max(max_depth, 3)", "unlocks": ["q", "w"], "desc": "Unlock Depth 3"},
    
    {"key": "8", "name": "Diamond Drill", "ore_costs": {"iron": 12, "silver": 8}, "money_cost": 10000000, 
     "damage": 100, "auto_damage": 0, "depth_unlock": 0, "purchased": False,
     "effect": "ore_damage += 100", "unlocks": ["e"], "desc": "+100 damage"},
    
    {"key": "9", "name": "Titanium Pickaxe", "ore_costs": {"silver": 10}, "money_cost": 7500000, 
     "damage": 75, "auto_damage": 0, "depth_unlock": 0, "purchased": False,
     "effect": "ore_damage += 75", "unlocks": ["e"], "desc": "+75 damage"},
    
    {"key": "0", "name": "Mining Crew", "ore_costs": {"iron": 15, "silver": 10}, "money_cost": 15000000, 
     "damage": 0, "auto_damage": 30, "depth_unlock": 0, "purchased": False,
     "effect": "auto_mine_damage += 30; auto_miner_count += 5", "unlocks": ["r"], "desc": "+30 auto damage"},
    
    # Tier 4 - Unlock Depth 4
    {"key": "w", "name": "Deep Mining Shaft", "ore_costs": {"gold": 8, "emerald": 5}, "money_cost": 50000000, 
     "damage": 0, "auto_damage": 0, "depth_unlock": 4, "purchased": False,
     "effect": "max_depth = max(max_depth, 4)", "unlocks": ["t", "y"], "desc": "Unlock Depth 4"},
    
    {"key": "e", "name": "Laser Drill", "ore_costs": {"gold": 10, "emerald": 6}, "money_cost": 75000000, 
     "damage": 200, "auto_damage": 0, "depth_unlock": 0, "purchased": False,
     "effect": "ore_damage += 200", "unlocks": ["u"], "desc": "+200 damage"},
    
    {"key": "t", "name": "Mithril Pickaxe", "ore_costs": {"gold": 12, "emerald": 8}, "money_cost": 100000000, 
     "damage": 150, "auto_damage": 0, "depth_unlock": 0, "purchased": False,
     "effect": "ore_damage += 150", "unlocks": ["u"], "desc": "+150 damage"},
    
    {"key": "y", "name": "Mining Operation", "ore_costs": {"gold": 15, "emerald": 10}, "money_cost": 125000000, 
     "damage": 0, "auto_damage": 50, "depth_unlock": 0, "purchased": False,
     "effect": "auto_mine_damage += 50; auto_miner_count += 10", "unlocks": ["i"], "desc": "+50 auto damage"},
    
    # Tier 5 - Unlock Depth 5
    {"key": "u", "name": "Ancient Depths", "ore_costs": {"ruby": 10, "diamond": 8}, "money_cost": 500000000, 
     "damage": 0, "auto_damage": 0, "depth_unlock": 5, "purchased": False,
     "effect": "max_depth = max(max_depth, 5)", "unlocks": ["o", "p"], "desc": "Unlock Depth 5"},
    
    {"key": "i", "name": "Plasma Cutter", "ore_costs": {"ruby": 12, "diamond": 10}, "money_cost": 750000000, 
     "damage": 400, "auto_damage": 0, "depth_unlock": 0, "purchased": False,
     "effect": "ore_damage += 400", "unlocks": ["o"], "desc": "+400 damage"},
    
    {"key": "o", "name": "Quantum Drill", "ore_costs": {"diamond": 15}, "money_cost": 1000000000, 
     "damage": 300, "auto_damage": 0, "depth_unlock": 0, "purchased": False,
     "effect": "ore_damage += 300", "unlocks": ["o"], "desc": "+300 damage"},
    
    {"key": "p", "name": "Industrial Complex", "ore_costs": {"ruby": 20, "diamond": 12}, "money_cost": 2000000000, 
     "damage": 0, "auto_damage": 100, "depth_unlock": 0, "purchased": False,
     "effect": "auto_mine_damage += 100; auto_miner_count += 20", "unlocks": ["p"], "desc": "+100 auto damage"},
    
    # Final upgrades
    {"key": "[", "name": "Nano-Excavator", "ore_costs": {"mythril": 25, "adamantite": 15}, "money_cost": 5000000000, 
     "damage": 1000, "auto_damage": 0, "depth_unlock": 0, "purchased": False,
     "effect": "ore_damage += 1000", "unlocks": [], "desc": "+1000 damage"},
    
    {"key": "]", "name": "Unlock Next World", "ore_costs": {"mythril": 50, "adamantite": 30, "orichalcum": 25}, "money_cost": 25000000000, 
     "damage": 0, "auto_damage": 0, "depth_unlock": 0, "purchased": False,
     "effect": "print('Next world unlocked!')", "unlocks": [], "desc": "???"},
]


# --- CITY DATA ---
city_buildings = []

def generate_city_layout():
    global city_buildings
    num_buildings = 25
    types = [
        {"name": "house",      "roof": "▲", "body": "▓"},
        {"name": "factory",    "roof": "■", "body": "▒"},
        {"name": "tower",      "roof": "▲", "body": "▌"},
        {"name": "skyscraper", "roof": "■", "body": "█"},
        {"name": "dome",       "roof": "◯", "body": "░"},
        {"name": "antenna",    "roof": "│", "body": "┃"},
        {"name": "villa",      "roof": "♢", "body": "▒"},
        {"name": "castle",     "roof": "♜", "body": "█"},
        {"name": "tent",       "roof": "△", "body": "┼"},
    ]
    mid = num_buildings // 2
    city_buildings = []
    for i in range(num_buildings):
        width = 1 + (mid - abs(i - mid)) // 2
        b_type = random.choice(types)
        offset = random.randint(0, 2)
        city_buildings.append({
            "width": width, "type": b_type, "base": 1, "height": 1,
            "pos": i, "mid_offset": abs(i - mid), "rand_offset": offset
        })

def update_building_heights(upgrades_count):
    max_height = 15
    for b in city_buildings:
        pyramid_height = int(upgrades_count / 2 / (b["mid_offset"] + 1)) + 1
        b["height"] = min(max_height, pyramid_height + b["rand_offset"])

def draw_city():
    width = 100
    max_height = 15
    spacing = 1
    cloud_line = "".join("☁" if random.random() > 0.85 else " " for _ in range(width))
    print(cloud_line + "\n")
    for y in reversed(range(max_height)):
        line = ""
        for b in city_buildings:
            b_height = b["height"]
            b_width = b["width"]
            b_type = b["type"]
            if y < b_height:
                line += (b_type["roof"] if y == b_height - 1 else b_type["body"]) * b_width
            else:
                line += " " * b_width
            line += " " * spacing
        print(line.center(width))
    print("_" * width)


# --- BLACK HOLE PAGE: art, upgrades, helpers ---
def generate_planet_art(size, ships):
    """Generate a stylized planet with orbiting ships.
    `size` controls planet radius; `ships` is number of ships on orbit."""
    import math
    art_lines = []
    planet_radius = 2 + size
    height = planet_radius * 2 + 1
    width = planet_radius * 4 + 1
    cx = width // 2
    cy = height // 2

    # create blank canvas
    canvas = [[" "] * width for _ in range(height)]

    # draw planet (filled circle)
    for y in range(height):
        for x in range(width):
            dx = (x - cx) / 2.0
            dy = y - cy
            dist = math.hypot(dx, dy)
            if dist <= planet_radius * 0.6:
                canvas[y][x] = "O"
            elif dist <= planet_radius * 0.95:
                canvas[y][x] = "o"
            elif dist <= planet_radius * 1.15:
                canvas[y][x] = "~"

    # draw multiple landscape-oriented orbits and distribute ships across them
    # number of orbits scales with size (at least 1, cap at 5)
    orbit_count = max(1, min(5, 1 + (size // 2)))
    # create orbit radii (landscape: rx significantly > ry)
    orbits = []
    for j in range(orbit_count):
        rx = int(planet_radius * (3.2 + j * 1.0))
        ry = max(1, int(planet_radius * (0.7 + j * 0.25)))
        orbits.append((rx, ry))

    # dotted orbits (more horizontal emphasis)
    for (orbit_r_x, orbit_r_y) in orbits:
        for a in range(0, 360, 8):
            ang = math.radians(a)
            ox = int(cx + orbit_r_x * math.cos(ang))
            oy = int(cy + orbit_r_y * math.sin(ang))
            if 0 <= oy < height and 0 <= ox < width and canvas[oy][ox] == " ":
                canvas[oy][ox] = "."

    # ship glyphs to make orbit pretty
    ship_glyphs = ["▲", "▶", "✦", "◉", "✺", "*", "✶"]
    if ships > 0:
        # distribute ships across orbits proportional to orbit size (approx circumference)
        weights = []
        for (rx, ry) in orbits:
            weights.append(rx + ry)
        total_w = max(1, sum(weights))
        per_orbit = [max(0, (ships * w) // total_w) for w in weights]
        # distribute remainder
        rem = ships - sum(per_orbit)
        j = 0
        while rem > 0:
            per_orbit[j % orbit_count] += 1
            rem -= 1
            j += 1

        idx = 0
        for j, (orbit_r_x, orbit_r_y) in enumerate(orbits):
            cnt = per_orbit[j]
            if cnt <= 0:
                continue
            # give each orbit a phase offset so ships stagger between rings
            phase = j * 0.6
            for k in range(cnt):
                angle = 2 * math.pi * k / max(1, cnt) + phase
                sx = int(cx + orbit_r_x * math.cos(angle))
                sy = int(cy + orbit_r_y * math.sin(angle))
                if 0 <= sy < height and 0 <= sx < width:
                    glyph = ship_glyphs[idx % len(ship_glyphs)]
                    canvas[sy][sx] = glyph
                idx += 1

    for row in canvas:
        art_lines.append("".join(row))
    art_lines.append(" ")
    art_lines.append(f" Planet Size: {size} | Ships: {ships} ")
    return art_lines


blackhole_upgrades = [
    {"key": "z", "name": "Siphon Matter", "desc": "+50 rate", "base_cost": 5000000000000, "cost": 5000000000000, "multiplier": 1.35, "count": 0, "max": 20, "seen": False},
    {"key": "x", "name": "Event Horizon", "desc": "+2 ships", "base_cost": 25000000000000, "cost": 25000000000000, "multiplier": 1.6, "count": 0, "max": 10, "seen": False},
    {"key": "c", "name": "Singularity Core", "desc": "+50% other mult", "base_cost": 10000000000000, "cost": 10000000000000, "multiplier": 1.5, "count": 0, "max": 6, "seen": False},
    {"key": "v", "name": "Accretion Ring", "desc": "Grow size", "base_cost": 250000000000000, "cost": 250000000000000, "multiplier": 1.35, "count": 0, "max": 8, "seen": False},
    {"key": "s", "name": "Orbital Dockyards", "desc": "+1 ship", "base_cost": 1000000000000000, "cost": 1000000000000000, "multiplier": 1.5, "count": 0, "max": 50, "seen": False},
    {"key": "n", "name": "Break The Reality", "desc": "Break the reality", "base_cost": 10000000000000000, "cost": 10000000000000000, "multiplier": 0, "count": 0, "max": 1, "seen": False},
]


def buy_blackhole_upgrade(upg):
    """Purchase and apply black hole upgrade effects."""
    global money, rate, adminmultiplier, othermultiplier, blackhole_growth, blackhole_upgrades_count, research_page_unlocked, ships_count
    if upg["count"] >= upg["max"]:
        return
    if money < upg["cost"]:
        return
    money -= upg["cost"]
    upg["count"] += 1
    blackhole_upgrades_count += 1

    # apply effects by key
    if upg["key"] == "z":
        rate += 50
    elif upg["key"] == "x":
        # Event Horizon now adds ships to the orbit (bigger effect than dockyards)
        ships_count += 2
    elif upg["key"] == "c":
        othermultiplier *= 1.5
    elif upg["key"] == "v":
        blackhole_growth += 1
    elif upg["key"] == "s":
        ships_count += 1
    elif upg["key"] == "n":
        # Breaking the reality unlocks research (keeps original effect)
        research_page_unlocked = True
    # Award a smaller, reliable sanity bump for BH purchases so the bar
    # progresses when the player invests in BH upgrades but doesn't jump
    # excessively. Use about one quarter of the configured BH increment.
    try:
        base = SANITY_INCREMENTS.get('blackhole', 1)
        bump = max(1, int(base // 4))
        add_sanity(bump)
    except Exception:
        try:
            global sanity_points
            sanity_points += 1
        except Exception:
            pass

    # award final-blackhole completion event when the special upgrade purchased
    try:
        if upg.get('key') == 'n':
            try:
                award_sanity_event('bh_finish')
            except Exception:
                pass
    except Exception:
        pass
    try:
        if upg.get('key') == 'n':
            try:
                trigger_send_to_world2('blackhole')
            except Exception:
                pass
    except Exception:
        pass

    # increase cost for next purchase when multiplier >0
    if upg.get("multiplier", 0) and upg["multiplier"] > 0:
        upg["cost"] = int(upg["cost"] * upg["multiplier"])


def draw_blackhole_page():
    """Render the black hole (planet + ships) page to stdout (non-curses)."""
    global blackhole_growth, ships_count
    # time-based income handled by main loop
    art = generate_planet_art(blackhole_growth, ships_count)
    # center the art to terminal width
    import shutil
    term_width = shutil.get_terminal_size().columns
    for line in art:
        print(line.center(term_width))

    print("\n=== BLACK HOLE UPGRADES ===\n")
    any_seen = False
    for upg in blackhole_upgrades:
        if money >= upg["cost"] * 0.1: upg["seen"] = True
        if upg["seen"]:
            any_seen = True
            # show count/max; if max == 1, just show count to avoid "/1" clutter
            if upg['max'] == 1:
                cnt_str = f"({upg['count']})"
            else:
                cnt_str = f"({upg['count']}/{upg['max']})"
            status = f"Cost: ${upg['cost']} | {cnt_str}"
            print(f"[{upg['key'].upper()}] {upg['name']} - {upg['desc']} {status}")
    if not any_seen:
        print("(No black hole upgrades available yet...)")


# --- INPUT / CLEAR ---
def clear(): os.system("cls" if os.name == "nt" else "clear")
def get_key():
    # unified wrapper that uses the cross-platform `get_char` implementation
    return get_char()


def render_sanity_bar_console():
    """Print the sanity bar for console pages."""
    try:
        global sanity_points, SANITY_TARGET
        filled = int(sanity_points)
        total = int(SANITY_TARGET)
        bar_width = 30
        filled_w = int((filled / total) * bar_width) if total > 0 else 0
        bar = "[" + "#" * filled_w + " " * (bar_width - filled_w) + "]"
        # show only the bar to the player; numeric fractions are hidden
        print(f"Sanity: {bar}\n")
    except Exception:
        pass

# --- BUY FUNCTIONS ---
def buy_upgrade(upg):
    global money, rate, w1upgrades, research_page_unlocked, sanity_points, SANITY_TARGET
    if upg["count"] >= upg["max"]: return
    if money < upg["cost"]: return
    money -= upg["cost"]
    rate += upg["rate_inc"]
    upg["count"] += 1
    w1upgrades += 1
    if upg["name"] == "Unlock Research":
        # Unlocking research: fill bar and send player explicitly
        research_page_unlocked = True
        try:
            sanity_points = int(SANITY_TARGET)
        except Exception:
            try:
                sanity_points = int(float(SANITY_TARGET))
            except Exception:
                sanity_points = SANITY_TARGET
        try:
            trigger_send_to_world2('research')
        except Exception:
            pass
    else:
        # Normal upgrades increase sanity only if City is the active sanity stage
        try:
            if sanity_stage == 0:
                add_sanity(SANITY_INCREMENTS.get('city', 1))
        except Exception:
                try:
                    sanity_points += SANITY_INCREMENTS.get('city', 1)
                except Exception:
                    pass
    # mark research page to update when viewing
    try:
        global research_needs_update
        research_needs_update = True
    except Exception:
        pass
    if upg["count"] < upg["max"]:
        upg["cost"] = int(upg["cost"] * upg["multiplier"])
    # (other milestone sanity awards handled elsewhere)

def buy_research(res):
    global money, adminmultiplier, othermultiplier, page
    if res["purchased"]: return
    if money < res["cost"]: return
    money -= res["cost"]
    res["purchased"] = True
    exec(res["effect"], globals())
    # ensure research view will re-render
    try:
        global research_needs_update
        research_needs_update = True
    except Exception:
        pass
    # per-stage sanity: research purchases increase sanity when research is active
    try:
        if sanity_stage == 1:
            add_sanity(SANITY_INCREMENTS.get('research', 1))
    except Exception:
        pass
    # if this research unlocks Technology, also award the one-time event
    try:
        if res.get('key') == '0' or res.get('name', '').lower().startswith('unlock technology'):
            try:
                award_sanity_event('tech_unlock')
            except Exception:
                pass
    except Exception:
        pass
    # If this research unlocked the Technology page, move the player there
    try:
        if res.get('key') == '0' or res.get('name', '').lower().startswith('unlock technology'):
            try:
                # send player to world 2 when Technology is unlocked
                trigger_send_to_world2('research')
            except Exception:
                pass
    except Exception:
        pass


def buy_technology(tech):
    global money, ore_damage, auto_mine_damage, depth, max_depth, ore_inventory, auto_miner_count
    if tech["purchased"]: 
        return

    # Check money
    if money < tech["money_cost"]: 
        return

    # Check ore costs
    for ore_name, ore_amount in tech["ore_costs"].items():
        if ore_inventory.get(ore_name, 0) < ore_amount:
            return

    # Purchase
    money -= tech["money_cost"]
    for ore_name, ore_amount in tech["ore_costs"].items():
        ore_inventory[ore_name] -= ore_amount

    tech["purchased"] = True
    exec(tech["effect"], globals())
    # If this tech unlocked a deep depth (>=4), send player to world 2
    try:
        # Only send player to world 2 when unlocking depth 4 (not depth 5)
        if tech.get('depth_unlock', 0) == 4:
            try:
                trigger_send_to_world2('mining', tech.get('depth_unlock', None))
            except Exception:
                try:
                    trigger_send_to_world2('mining')
                except Exception:
                    pass
    except Exception:
        pass
    # per-stage sanity: technology/mining purchases increase sanity when mining is active
    try:
        if sanity_stage == 2:
            add_sanity(SANITY_INCREMENTS.get('technology', 1))
    except Exception:
        pass




def draw_mine_shaft():
    """Draw the current ore being mined with HP bar"""
    if current_ore is None:
        spawn_new_ore()
    
    ore_name = current_ore["name"].upper()
    ore_symbol = current_ore["color"]
    hp_percent = ore_hp / ore_max_hp if ore_max_hp > 0 else 0
    bar_width = 30
    filled = int(hp_percent * bar_width)
    hp_bar = "[" + "#" * filled + " " * (bar_width - filled) + "]"
    
    shaft = f"""
    ╔═══════════════════════════════════════════════════╗
    ║              MINING SHAFT - DEPTH {depth}              ║
    ╚═══════════════════════════════════════════════════╝
           |                             |
           |                             |
          _|_____________________________|_
         /                                 \\
        /         {ore_symbol * 5}  {ore_symbol * 5}  {ore_symbol * 5}          \\
       /        {ore_symbol * 7}  {ore_symbol * 7}  {ore_symbol * 7}        \\
      /       {ore_symbol * 9}  {ore_symbol * 9}  {ore_symbol * 9}       \\
     /      {ore_symbol * 11}  {ore_symbol * 11}  {ore_symbol * 11}      \\
    /___________________________________________\\
    
    Current Ore: {ore_name}
    HP: {hp_bar} {ore_hp}/{ore_max_hp}
    Value: ${current_ore["value"]} | Click Damage: {ore_damage} | Auto DPS: {auto_mine_damage}
    """
    print(shaft)

def draw_technology_tree():
    """Draw mining tech tree"""
    nodes = []
    for tech in technology:
        mark = "X" if tech["purchased"] else " "
        nodes.append(f"[{tech['key'].upper()}:{mark}]")
    
    while len(nodes) < 20:
        nodes.append("[  : ]")
    
    tree = f"""
                           {nodes[0]}
                              |
                    ┌─────────┴─────────┐
                    |                   |
                 {nodes[1]}            {nodes[2]}
                    |                   |
          ┌─────────┴────────┐          |
          |                  |          |
       {nodes[3]}         {nodes[4]}  {nodes[5]}
          |                  |          |
    ┌─────┴─────┐            |          |
    |           |            |          |
 {nodes[6]}  {nodes[7]}   {nodes[8]}  {nodes[9]}
    |           |            |          |
    └─────┬─────┴────────────┴──────────┘
          |
    ┌─────┴─────┐
    |           |
 {nodes[10]}  {nodes[11]}
    |           |
    └─────┬─────┴──────┐
          |            |
       {nodes[12]}  {nodes[13]}
          |            |
    ┌─────┴─────┐      |
    |           |      |
 {nodes[14]}  {nodes[15]} {nodes[16]}
    |           |      |
    └─────┬─────┴──────┘
          |
    ┌─────┴─────┐
    |           |
 {nodes[17]}  {nodes[18]}
    |           |
    └─────┬─────┘
          |
       {nodes[19]}
    """
    print(tree)

# --- MOUSE CLICK FUNCTIONS ---
def enable_mouse():
    sys.stdout.write("\033[?1000h\033[?1006h"); sys.stdout.flush()
def disable_mouse():
    sys.stdout.write("\033[?1000l\033[?1006l"); sys.stdout.flush()

def read_mouse_sequence():
    seq = ""
    while True:
        c = sys.stdin.read(1)
        if not c: return None
        seq += c
        if c in ("M", "m"): break
    return seq

# --- RESEARCH TREE DISPLAY ---
def draw_research_tree():
    nodes = []
    for i in range(10):
        if i < len(research):
            r = research[i]
            mark = "X" if r["purchased"] else " "
            nodes.append(f"[R{i+1}:{mark}]")
        else:
            nodes.append(f"[R{i+1}: ]")
    tree = f"""
                     ┌────────{nodes[0]}────────┐
                     ||                    ||
          ┌────────{nodes[1]}────────┐        ────{nodes[2]}────────┐
          ||                     ||                         ||
          {nodes[3]}───---─┐┌────{nodes[4]}                      {nodes[5]}  
                       ||                                  || 
                       {nodes[7]}────┐                 ┌──----{nodes[8]}
                                  -------{nodes[9]}────
                                            |
    """
    print(tree)


# --- COMBAT HELPERS ---
def format_bar(value, maximum, width=20):
    pct = max(0, min(1.0, float(value) / float(maximum))) if maximum > 0 else 0
    filled = int(pct * width)
    return "[" + "#" * filled + " " * (width - filled) + "]"


def glitch_transition():
    """Display a glitch effect for 5 seconds when transitioning between worlds."""
    glitch_chars = list('#$%*^&@!~+=<>?/|')
    try:
        import shutil
        term_height, term_width = 24, 80
        try:
            term_width, term_height = shutil.get_terminal_size()
        except Exception:
            pass
        
        duration = 5.0
        start = time.time()
        frame_count = 0
        
        while time.time() - start < duration:
            clear()
            # Generate random glitch screen
            for row in range(term_height - 1):
                line = ''.join(random.choice(glitch_chars) for _ in range(term_width - 1))
                print(line)
            
            # Flash by alternating between different patterns
            time.sleep(0.08 if frame_count % 2 == 0 else 0.12)
            frame_count += 1
        
        clear()
    except Exception:
        # Fallback: simple glitch
        for _ in range(5):
            clear()
            print(''.join(random.choice(glitch_chars) for _ in range(80)))
            time.sleep(0.5)
        clear()


# --- ENEMY DISPLAY HELPERS ---
def random_error_name(length=8):
    """Return a short garbled string made of punctuation to simulate corruption."""
    chars = list('%&*^#@$!<>?/~')
    return ''.join(random.choice(chars) for _ in range(length))


def get_enemy_display_name(region_key):
    """Return the display name for a given region. If the region's name is None
    (special case for Forgotten Sanctum), return a randomized garbled string.
    Otherwise return the configured name.
    """
    try:
        if region_key is None:
            return random_error_name()
        if region_key == 'forgotten_sanctum':
            return random_error_name()
        name = region_enemy_map.get(region_key)
        if not name:
            return region_key.replace('_', ' ').title()
        return name
    except Exception:
        return random_error_name()


# ASCII art per-region (left, right)
ENEMY_ASCII = {
    'whispering_pines': (
        ["   .--.", "  /../ ", " (  : )", "  | ||", "   --- "],
        ["  .--.  ", " (    ) ", "  ( : )>", "   --- ", "  /___ "]
    ),
    'silent_graveyard': (
        ["   .-.", "  (   )", " ( : ) ", "  /|/", "  /  "],
        ["  ._.", " (o o)", "  -_- ", "  /|/", "  /  "]
    ),
    'hollowed_farmlands': (
        ["   /  ", "  /   ", " (    )", "  |  |", "  /__ "],
        ["   ~~  ", " (.. )", "  ( : )>", "  /  ", "  /___ "]
    ),
    'sunken_marketplace': (
        ["  [====]", "  |::..|", "  |:.. |", "   /   ", "  /____"],
        ["  _____ ", " (_____)", "  ( : )>", "  /   ", "  /___ "]
    ),
    'old_residential_district': (
        ["  |--|", " [____]", "  (..)", "  /|/", "  /__ "],
        ["  /_/_ ", " ( o.o )", "  ( : ) ", "  /   ", "  /___ "]
    ),
    'mirror_marsh': (
        ["   ~~~", "  ~o~ ", " (  : )", "  /   ", " /____"],
        ["  ~~~  ", " ~o~   ", "  ( : )>", "  /   ", " /____" ]
    ),
    'forgotten_sanctum': (
        # normal human ASCII art for the Forgotten Sanctum enemy
        ["   O", "  /|/", "  /  ", "", ""],
        ["   O", "  /|/", "  /  ", "", ""]
    ),
}

# Player ASCII (left side) — stays consistent across all combats
PLAYER_ASCII = [
    "  (\\_/)",
    "  (•_•)",
    " <( : ) ",
    "  /   \\",
    "  /___\\",
]


def get_ascii_for_region(region_key):
    """Return (left, right) ascii lists for a region. Falls back to default pair."""
    if not region_key:
        # default simple art (avoid backslashes to ensure portability)
        return (
            ["  (o_o)", "  (•_•)", " <( : ) ", "   -  ", "  /___ "],
            ["  (._.)", " ( o.o )", "  ( : )> ", "   -  ", "  /___ "]
        )
    art = ENEMY_ASCII.get(region_key)
    if art:
        return art
    # try approximate match by prefix
    for k in ENEMY_ASCII:
        if k in region_key:
            return ENEMY_ASCII[k]
    # default
    # fallback default
    return (
        ["  (o_o)", "  (•_•)", " <( : ) ", "   -  ", "  /___ "],
        ["  (._.)", " ( o.o )", "  ( : )> ", "   -  ", "  /___ "]
    )

def enter_combat(location_name=None):
    global combat_started, player_hp, player_max_hp, enemy_hp, enemy_max_hp, player_heals, player_ability_charges, combat_log, current_enemy_name, current_enemy_region
    # determine the region key (normalize)
    if location_name:
        region_key = str(location_name).lower()
    else:
        # pick a random region if none provided
        try:
            region_key = random.choice(list(region_enemy_map.keys()))
        except Exception:
            region_key = None

    # pick the enemy name assigned to that region (or random fallback)
    try:
        enemy_name = region_enemy_map.get(region_key, random.choice(MONSTER_NAMES))
    except Exception:
        enemy_name = random.choice(MONSTER_NAMES)

    current_enemy_region = region_key

    # if the region's enemy was already defeated, show message and do not start combat
    if region_key in defeated_regions:
        combat_started = False
        combat_log = [f"'{enemy_name}' has already been defeated!"]
        return

    # start combat normally
    combat_started = True
    player_max_hp = 100
    player_hp = player_max_hp
    enemy_max_hp = 80
    enemy_hp = enemy_max_hp
    player_heals = 3
    player_ability_charges = 1
    # store canonical name (may be None for dynamically-named regions)
    current_enemy_name = enemy_name
    # display name may be dynamic (e.g., forgotten_sanctum)
    display_name = get_enemy_display_name(region_key)
    combat_log = [f"'{display_name}' has appeared at {location_name or 'Unknown Location'}!"]

def draw_combat_ui():
    # choose ascii art based on current region (if available)
    left, right = get_ascii_for_region(current_enemy_region)
    width = 80
    # header
    display_name = get_enemy_display_name(current_enemy_region)
    print("=== ENEMY - COMBAT ===\n")
    print(f"Enemy: {display_name}\n")
    # draw ascii side-by-side: left is player art, right is enemy art
    _, enemy_right = get_ascii_for_region(current_enemy_region)
    left = PLAYER_ASCII
    gap = width - 20
    for i in range(max(len(left), len(enemy_right))):
        l = left[i] if i < len(left) else ""
        r = enemy_right[i] if i < len(enemy_right) else ""
        print(l.ljust(20) + " " * 10 + r.rjust(20))

    # hp bars
    print()
    print("Player HP: ", format_bar(player_hp, player_max_hp, 30), f"{player_hp}/{player_max_hp}")
    print("Enemy  HP: ", format_bar(enemy_hp, enemy_max_hp, 30), f"{enemy_hp}/{enemy_max_hp}")

    # combat log (last 4 messages)
    print("\n-- Combat Log --")
    for msg in combat_log[-4:]:
        print(" - " + msg)

    # action bar at bottom-ish
    print("\n" + "-" * width)
    actions = f"[A] Attack   [H] Heal ({player_heals})   [U] Ability ({player_ability_charges})"
    print(actions.center(width))

def perform_player_action(action):
    global enemy_hp, player_hp, player_heals, combat_log, player_ability_charges, combat_started, world, current_enemy_name, killed_monsters, consecutive_defeats
    if action == 'attack':
        dmg = random.randint(8, 15)
        enemy_hp -= dmg
        combat_log.append(f"You attack the enemy for {dmg} dmg.")
    elif action == 'heal':
        if player_heals <= 0:
            combat_log.append("No heals left!")
        else:
            heal = random.randint(12, 25)
            player_hp = min(player_max_hp, player_hp + heal)
            player_heals -= 1
            combat_log.append(f"You heal for {heal} HP.")
    elif action == 'ability':
        if player_ability_charges <= 0:
            combat_log.append("No ability charges!")
        else:
            dmg = random.randint(20, 35)
            enemy_hp -= dmg
            player_ability_charges -= 1
            combat_log.append(f"You use your ability for {dmg} dmg!")

    # check enemy death
    if enemy_hp <= 0:
        combat_log.append("Enemy defeated!")
        # record the killed monster (most recent first) and mark region defeated
        try:
            if current_enemy_region and current_enemy_region not in defeated_regions:
                defeated_regions.add(current_enemy_region)
                # Use display name for recording (handles dynamic names like Forgotten Sanctum)
                try:
                    canonical = region_enemy_map.get(current_enemy_region)
                except Exception:
                    canonical = None
                if canonical is None:
                    display_name = get_enemy_display_name(current_enemy_region)
                else:
                    display_name = current_enemy_name or canonical
                if display_name and display_name not in killed_monsters:
                    killed_monsters.insert(0, display_name)
                
                # Increment defeat counter
                consecutive_defeats += 1
        except Exception:
            pass
        combat_started = False
        
        # Check if Forgotten Sanctum was defeated - if so, trigger victory
        if current_enemy_region == 'forgotten_sanctum':
            # Trigger permanent glitch effect with victory message
            glitch_chars = list('#$%*^&@!~+=<>?/|')
            victory_msg = "You won"
            terminal_width = 80
            terminal_height = 30
            victory_row = terminal_height // 2
            try:
                while True:
                    print('\n' * 50)  # clear screen
                    # Generate glitch lines before victory message
                    for row in range(terminal_height):
                        if row == victory_row:
                            # Center the "You won" message on this row
                            padding = (terminal_width - len(victory_msg)) // 2
                            glitch_before = ''.join(random.choice(glitch_chars) for _ in range(padding))
                            glitch_after = ''.join(random.choice(glitch_chars) for _ in range(terminal_width - padding - len(victory_msg)))
                            print(glitch_before + victory_msg + glitch_after)
                        else:
                            # Regular glitch line
                            line_length = random.randint(40, 80)
                            glitch_line = ''.join(random.choice(glitch_chars) for _ in range(line_length))
                            print(glitch_line)
                    time.sleep(0.5)
            except KeyboardInterrupt:
                pass
            return
        
        # Switch to world 1 after defeating pairs: 2nd, 4th, 6th dungeons
        # OR immediately after defeating Obsidian Quarry (dungeon 7)
        # This means: after (Whispering+Silent), (Hollowed+Sunken),
        # (Old Res+Mirror), (Obsidian Quarry)
        total_defeated = len(defeated_regions)
        if total_defeated in [2, 4, 6] or current_enemy_region == 'obsidian_quarry':
            world = 1
            # Note: glitch transition will be shown when combat returns to main loop
        # Otherwise stay in world 2 for next dungeon
        return

    # enemy turn
    edmg = random.randint(5, 14)
    player_hp -= edmg
    combat_log.append(f"Enemy hits you for {edmg} dmg.")
    if player_hp <= 0:
        combat_log.append("You were slain...")
        combat_started = False
        # Don't set world here - let curses_combat handle death message


def curses_map_view(stdscr):
    """Draw the map using curses and wait for a mouse click on a labeled region.
    Returns the normalized region name (key in click_labels) or None if canceled."""
    init_curses_window(stdscr)
    # enable mouse reporting where available
    try:
        curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
    except Exception:
        pass

    # Determine which dungeon is currently available
    available_dungeon = get_next_available_dungeon()

    # ASCII list icon for World 4: [≡]
    list_icon = "[≡]"
    # keep header compact to avoid wrapping issues on narrow terminals
    header_line1 = f"=== WORLD 2: MAP ===   Level: {player_level}   {list_icon} Kill List"
    header_lines = [header_line1, "You seem to have transported to another world... Click on bolded text to enter dungeon.", ""]
    # prepare a full-screen line buffer and render only changed lines
    try:
        maxy, maxx = stdscr.getmaxyx()
    except Exception:
        maxy, maxx = 24, 80
    new_lines = [''] * maxy
    for i, line in enumerate(header_lines):
        if i < maxy:
            new_lines[i] = line[:maxx-1]

    map_top = len(header_lines)
    # scrolling state
    visible_height = max(0, maxy - map_top - 1)
    map_scroll = 0

    def draw_map():
        # rebuild new_lines for current scroll
        for i, line in enumerate(header_lines):
            if i < maxy:
                new_lines[i] = line[:maxx-1]
        # fill visible slice of map_art
        for vis_i in range(visible_height):
            art_idx = map_scroll + vis_i
            dest = map_top + vis_i
            if dest >= maxy:
                break
            if art_idx < len(map_art):
                new_lines[dest] = map_art[art_idx][:maxx-1]
            else:
                new_lines[dest] = ''

        # overlay debug markers for visible zones
        if SHOW_ZONE_DEBUG:
            for name, z in absolute_zones.items():
                # compute displayed row for zone (1-based to match earlier math)
                disp_row_start = z["row_start"] - map_scroll
                disp_row_idx = disp_row_start - 1
                if map_top <= disp_row_idx < map_top + visible_height:
                    try:
                        r = disp_row_idx
                        c = z["col_start"] - 1
                        new_lines[r] = _overlay(new_lines[r], c, '[')
                        new_lines[r] = _overlay(new_lines[r], c + 1, name[:18])
                    except Exception:
                        pass

    # initial draw
    draw_map()

    # compute zones in display coords using existing helper
    # pass map_top+1 (1-based row index) so calculations align with zone math
    absolute_zones = make_absolute_zones(map_art, map_top + 1)

    # draw debug boxes (optional) - we'll overlay short markers at label starts
    def _overlay(line, col, txt):
        if col < 0:
            return line
        if col >= len(line):
            line = line + ' ' * (col - len(line))
        pre = line[:col]
        post = ''
        if col + len(txt) < len(line):
            post = line[col + len(txt):]
        return (pre + txt + post)[:maxx-1]

    if SHOW_ZONE_DEBUG:
        for name, z in absolute_zones.items():
            r = z["row_start"] - 1
            c = z["col_start"] - 1
            if 0 <= r < maxy:
                try:
                    new_lines[r] = _overlay(new_lines[r], c, '[')
                    new_lines[r] = _overlay(new_lines[r], c + 1, name[:18])
                except Exception:
                    pass

    # render initial frame
    for y, ln in enumerate(new_lines):
        render_line(stdscr, y, ln)
    
    # Bold the available dungeon if it exists
    if available_dungeon:
        zone_info = absolute_zones.get(available_dungeon)
        if zone_info:
            z = zone_info
            start_idx = z["row_start"] - (map_top + 1) - map_scroll
            z_h = z["row_end"] - z["row_start"] + 1
            z_w = z["col_end"] - z["col_start"] + 1
            col0 = z["col_start"] - 1
            for i in range(z_h):
                line_idx = start_idx + i
                if line_idx < 0 or line_idx >= visible_height:
                    continue
                y_pos = map_top + line_idx
                if 0 <= y_pos < maxy:
                    try:
                        stdscr.chgat(y_pos, col0, z_w, curses.A_BOLD)
                    except Exception:
                        pass
    
    present_frame(stdscr)

    while True:
        ch = stdscr.getch()
        if ch == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bstate = curses.getmouse()
            except Exception:
                continue
            # left click
            if bstate & curses.BUTTON1_CLICKED:
                # Check if clicking on the World 4 button (top-right area of header)
                # The button "[≡] Kill List" is in row 0 (map_top)
                # It's positioned near the end of header_line1
                if my == 0:  # header row
                    # Check if click is in the area of the header button text
                    try:
                        maxy, maxx = stdscr.getmaxyx()
                        btn_text = f"{list_icon} Kill List"
                        btn_start = maxx - len(btn_text) - 2
                        if mx >= btn_start:
                            return ("world4_button", False)
                    except Exception:
                        # fallback conservative behavior
                        if mx >=  stdscr.getmaxyx()[1] - 30:
                            return ("world4_button", False)
                
                # handle mouse wheel (BUTTON4/BUTTON5) if available
                try:
                    btn4 = getattr(curses, 'BUTTON4_PRESSED')
                    btn5 = getattr(curses, 'BUTTON5_PRESSED')
                except Exception:
                    btn4 = btn5 = 0
                if btn4 and (bstate & btn4):
                    map_scroll = max(0, map_scroll - 3)
                    draw_map()
                    for y, ln in enumerate(new_lines):
                        render_line(stdscr, y, ln)
                    present_frame(stdscr)
                    continue
                if btn5 and (bstate & btn5):
                    map_scroll = min(max(0, len(map_art) - visible_height), map_scroll + 3)
                    draw_map()
                    for y, ln in enumerate(new_lines):
                        render_line(stdscr, y, ln)
                    present_frame(stdscr)
                    continue

                # find which zone contains (my+1, mx+1) taking scroll into account
                matched = None
                for name, z in absolute_zones.items():
                    disp_row_start = z["row_start"] - map_scroll
                    disp_row_end = z["row_end"] - map_scroll
                    if disp_row_start <= my+1 <= disp_row_end and z["col_start"] <= mx+1 <= z["col_end"]:
                        matched = (name, z)
                        break
                
                if matched:
                    name, z = matched
                    
                    # Check if dungeon is already cleared
                    if name in defeated_regions:
                        try:
                            maxy, maxx = stdscr.getmaxyx()
                            location_display = name.replace('_', ' ').title()
                            msg = f"{location_display} has been cleared."
                            render_line(stdscr, maxy-1, msg[:maxx-1])
                            present_frame(stdscr)
                            time.sleep(1.0)
                            # Clear message
                            render_line(stdscr, maxy-1, '')
                            present_frame(stdscr)
                        except Exception:
                            pass
                        continue
                    
                    # Check if this is the available dungeon
                    if available_dungeon and name != available_dungeon:
                        # Not the available dungeon, show locked message
                        try:
                            maxy, maxx = stdscr.getmaxyx()
                            location_display = name.replace('_', ' ').title()
                            msg = f"{location_display} has not been unlocked"
                            render_line(stdscr, maxy-1, msg[:maxx-1])
                            present_frame(stdscr)
                            time.sleep(1.0)
                            # Clear message
                            render_line(stdscr, maxy-1, '')
                            present_frame(stdscr)
                        except Exception:
                            pass
                        continue
                
                present_frame(stdscr)
                if matched:
                    name, z = matched
                    
                    # visually highlight the matched zone briefly
                    # compute 0-based map_art index for zone start, adjusted for scroll
                    start_idx = z["row_start"] - (map_top + 1) - map_scroll
                    z_h = z["row_end"] - z["row_start"] + 1
                    z_w = z["col_end"] - z["col_start"] + 1
                    col0 = z["col_start"] - 1
                    for i in range(z_h):
                        line_idx = start_idx + i
                        if line_idx < 0 or line_idx >= visible_height:
                            continue
                        y = map_top + line_idx
                        try:
                            stdscr.chgat(y, col0, z_w, curses.A_REVERSE)
                        except Exception:
                            # fallback: mark with brackets in the line buffer and render
                            try:
                                art_idx = map_scroll + line_idx
                                lbl = map_art[art_idx][0:z_w]
                                new = _overlay(new_lines[y], col0, '[' + lbl[:max(0, z_w-2)] + ']')
                                render_line(stdscr, y, new)
                            except Exception:
                                pass
                    present_frame(stdscr)
                    time.sleep(0.25)
                    # revert the temporary highlight so attributes aren't left set
                    for i in range(z_h):
                        line_idx = start_idx + i
                        y = map_top + line_idx
                        try:
                            stdscr.chgat(y, col0, z_w, curses.A_NORMAL)
                        except Exception:
                            try:
                                # redraw original text without attributes
                                stdscr.addstr(y, col0, map_art[line_idx][0:z_w])
                            except Exception:
                                pass
                    stdscr.refresh()
                    # After highlighting, enter curses combat UI directly (stay in curses)
                    did = curses_combat(stdscr, name, absolute_zones, map_top)
                    return (name, bool(did))
        if ch in (ord('q'), 27):
            return None
        elif ch in (ord('k'), ord('K')):
            return (None, False)
        elif ch == curses.KEY_UP:
            map_scroll = max(0, map_scroll - 1)
            draw_map()
            for y, ln in enumerate(new_lines):
                render_line(stdscr, y, ln)
            present_frame(stdscr)
        elif ch == curses.KEY_DOWN:
            map_scroll = min(max(0, len(map_art) - visible_height), map_scroll + 1)
            draw_map()
            for y, ln in enumerate(new_lines):
                render_line(stdscr, y, ln)
            present_frame(stdscr)
        elif ch == curses.KEY_PPAGE:
            map_scroll = max(0, map_scroll - visible_height)
            draw_map()
            for y, ln in enumerate(new_lines):
                render_line(stdscr, y, ln)
            present_frame(stdscr)
        elif ch == curses.KEY_NPAGE:
            map_scroll = min(max(0, len(map_art) - visible_height), map_scroll + visible_height)
            draw_map()
            for y, ln in enumerate(new_lines):
                render_line(stdscr, y, ln)
            present_frame(stdscr)

        # small sleep to cap redraw rate and reduce CPU usage / flicker
        try:
            time.sleep(0.03)
        except Exception:
            pass


def map_view_fallback():
    """Non-curses fallback for world map selection on platforms without curses.
    Returns (normalized_name, False) or (None, False) if cancelled."""
    print("=== WORLD 2: MAP (text mode) ===")
    print("Click not available — choose a location by number or press [Q] to cancel.")
    # print map preview
    for line in map_art:
        print(line)
    labels = locate_labels_in_map(map_art)
    keys = list(labels.keys())
    if not keys:
        print("(No labeled locations found)")
        return (None, False)
    print("\nLocations:")
    for i, k in enumerate(keys, start=1):
        print(f"[{i}] {k.replace('_',' ').title()}")
    print("[Q] Cancel")
    # simple input loop
    while True:
        try:
            choice = input("Choose: ").strip()
        except Exception:
            return (None, False)
        if not choice:
            continue
        if choice.lower() == 'q':
            return (None, False)
        try:
            n = int(choice)
            if 1 <= n <= len(keys):
                return (keys[n-1], False)
        except ValueError:
            # allow direct name
            norm = choice.lower().replace(' ', '_')
            if norm in keys:
                return (norm, False)
        print("Invalid choice.")

def curses_combat(stdscr, region, absolute_zones=None, map_top=0):
    """Run a simple combat UI inside the existing curses session."""
    init_curses_window(stdscr)
    enter_combat(location_name=region)

    while True:
        try:
            maxy, maxx = stdscr.getmaxyx()
        except Exception:
            maxy, maxx = 24, 80

        # build per-line buffer for this frame
        new_lines = [''] * maxy
        # title uses the display name (may be dynamic for some regions)
        display_name = get_enemy_display_name(region)
        title = f"Enemy: {display_name}   Level: {player_level}"
        new_lines[0] = title[:maxx-1]

        # left side is player's consistent ASCII; right is enemy art for this region
        left = PLAYER_ASCII
        _, right = get_ascii_for_region(region)
        for i in range(5):
            y = 2 + i
            if y >= maxy:
                break
            # left art
            new_lines[y] = left[i][:maxx-1]
            # right art positioned near right side
            try:
                col = maxx - 20
                if col > 0:
                    line = new_lines[y]
                    if len(line) < col:
                        line = line + ' ' * (col - len(line))
                    line = (line[:col] + right[i])[:maxx-1]
                    new_lines[y] = line
            except Exception:
                pass

        # HP bars
        if 8 < maxy:
            new_lines[8] = f"Player HP: {player_hp}/{player_max_hp} "[:maxx-1]
        if 9 < maxy:
            new_lines[9] = format_bar(player_hp, player_max_hp, min(30, maxx-20))[:maxx-1]
        try:
            if 8 < maxy:
                col = maxx - 40
                if col > 0:
                    line = new_lines[8]
                    if len(line) < col:
                        line = line + ' ' * (col - len(line))
                    line = (line[:col] + f"Enemy HP: {enemy_hp}/{enemy_max_hp}")[:maxx-1]
                    new_lines[8] = line
            if 9 < maxy:
                col = maxx - 40
                if col > 0:
                    line = new_lines[9]
                    if len(line) < col:
                        line = line + ' ' * (col - len(line))
                    line = (line[:col] + format_bar(enemy_hp, enemy_max_hp, min(30, maxx-20)))[:maxx-1]
                    new_lines[9] = line
        except Exception:
            pass

        # combat log
        if 11 < maxy:
            new_lines[11] = "-- Combat Log --"
            for i, msg in enumerate(combat_log[-(maxy-18):], start=0):
                y = 12 + i
                if y < maxy - 4:
                    new_lines[y] = msg[:maxx-1]

        # actions
        if maxy - 2 >= 0:
            new_lines[maxy-2] = "[A] Attack   [H] Heal   [U] Ability"[:maxx-1]

        # render frame
        for y, ln in enumerate(new_lines):
            render_line(stdscr, y, ln)
        present_frame(stdscr)

        ch = stdscr.getch()
        if ch in (ord('a'), ord('A')):
            perform_player_action('attack')
        elif ch in (ord('h'), ord('H')):
            perform_player_action('heal')
        elif ch in (ord('u'), ord('U')):
            perform_player_action('ability')
        # Removed k key - player cannot exit combat manually

        # small sleep to cap redraw/input polling rate
        try:
            time.sleep(0.03)
        except Exception:
            pass

        # check combat end
        if not combat_started:
            # Check if player died (HP <= 0)
            if player_hp <= 0:
                # Player died - show death message
                msg = "You have died! Press [space] to restart."
                render_line(stdscr, maxy-3, msg[:maxx-1])
                present_frame(stdscr)
                # Wait for space bar
                while True:
                    ch = stdscr.getch()
                    if ch == ord(' '):
                        break
                # Return to world 1 (city)
                world = 1
                return True
            else:
                # Player won - display victory message with enemy name
                enemy_display = get_enemy_display_name(current_enemy_region) if current_enemy_region else "Enemy"
                msg = f"You have defeated {enemy_display}! Press [space] to exit."
                render_line(stdscr, maxy-3, msg[:maxx-1])
                present_frame(stdscr)
                # Wait for space bar
                while True:
                    ch = stdscr.getch()
                    if ch == ord(' '):
                        break
                # world is already set by defeat-counting logic in perform_player_action
                return True


def curses_blackhole_view(stdscr):
    """Animated black hole (planet + ships) view using curses."""
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)
    angle_offset = 0.0
    import math

    while True:
        stdscr.erase()
        maxy, maxx = stdscr.getmaxyx()
        title = "=== BLACK HOLE - ORBITAL VIEW ==="
        safe_addstr(stdscr, 0, max(0, (maxx - len(title)) // 2), title)

        # compute planet parameters
        pr = max(1, 2 + blackhole_growth)
        pw = pr * 4 + 1
        cx = maxx // 2
        cy = maxy // 2

        # draw planet
        for dy in range(-pr, pr + 1):
            for dx in range(-pw // 2, pw // 2 + 1):
                sx = cx + dx
                sy = cy + dy
                if sx < 0 or sx >= maxx or sy < 1 or sy >= maxy - 4:
                    continue
                d = math.hypot((dx / 2.0), dy)
                if d <= pr * 0.6:
                    ch = 'O'
                elif d <= pr * 0.95:
                    ch = 'o'
                elif d <= pr * 1.15:
                    ch = '~'
                else:
                    ch = ' '
                try:
                    safe_addstr(stdscr, sy, sx, ch)
                except Exception:
                    pass

        # multiple landscape orbits (rx > ry) and animated ships
        orbit_count = max(1, min(5, 1 + (blackhole_growth // 2)))
        orbits = []
        for j in range(orbit_count):
            rx = int(pr * (3.2 + j * 1.0))
            ry = max(1, int(pr * (0.7 + j * 0.25)))
            orbits.append((rx, ry))

        # draw dotted orbits (landscape emphasis)
        for j, (orbit_rx, orbit_ry) in enumerate(orbits):
            step = 10
            for a in range(0, 360, step):
                ang = math.radians(a + int(angle_offset * (0.5 + j * 0.3)))
                ox = int(cx + (orbit_rx * math.cos(ang)))
                oy = int(cy + (orbit_ry * math.sin(ang)))
                if 1 <= oy < maxy - 4 and 0 <= ox < maxx:
                    try:
                        safe_addstr(stdscr, oy, ox, '.')
                    except Exception:
                        pass

        # distribute ships across orbits proportional to orbit size
        ship_glyphs = ['▲', '◆', '✦', '✸', '✺', '✶', '✹']
        if ships_count > 0:
            weights = [(rx + ry) for (rx, ry) in orbits]
            total_w = max(1, sum(weights))
            per_orbit = [max(0, (ships_count * w) // total_w) for w in weights]
            rem = ships_count - sum(per_orbit)
            jj = 0
            while rem > 0:
                per_orbit[jj % orbit_count] += 1
                rem -= 1
                jj += 1

            idx = 0
            for j, (orbit_rx, orbit_ry) in enumerate(orbits):
                cnt = per_orbit[j]
                if cnt <= 0:
                    continue
                phase = j * 0.7
                for k in range(cnt):
                    ang = 2 * math.pi * k / max(1, cnt) + (angle_offset / (6.0 + j)) + phase
                    sx = int(cx + (orbit_rx * math.cos(ang)))
                    sy = int(cy + (orbit_ry * math.sin(ang)))
                    glyph = ship_glyphs[idx % len(ship_glyphs)]
                    try:
                        if 1 <= sy < maxy - 4 and 0 <= sx < maxx:
                            safe_addstr(stdscr, sy, sx, glyph)
                    except Exception:
                        pass
                    idx += 1

        # Right column: upgrades and info
        col = maxx - 38
        if col < pw + 5:
            col = pw + 6
        try:
            safe_addstr(stdscr, 2, col, f"Money: ${money:.2f}")
            safe_addstr(stdscr, 3, col, f"Ships: {ships_count}  (mult x{ships_money_multiplier():.2f})")
            safe_addstr(stdscr, 4, col, f"Planet Size: {blackhole_growth}")
            safe_addstr(stdscr, 6, col, "=== BLACK HOLE UPGRADES ===")
            ry = 7
            for upg in blackhole_upgrades:
                seen = upg.get('seen', False) or (money >= upg['cost'] * 0.1)
                if seen:
                    # if this upgrade has max==1, avoid showing "/1"
                    if upg['max'] == 1:
                        cnt_str = f"({upg['count']})"
                    else:
                        cnt_str = f"({upg['count']}/{upg['max']})"
                    status = f"${upg['cost']} {cnt_str}"
                    safe_addstr(stdscr, ry, col, f"[{upg['key'].upper()}] {upg['name']}")
                    safe_addstr(stdscr, ry + 1, col, f"   {upg['desc']} - {status}")
                    ry += 2
            # draw sanity bar at bottom centered
            try:
                bar_len = min(40, max(10, maxx - 8))
                filled_w = 0
                try:
                    if SANITY_TARGET > 0:
                        filled_w = int((sanity_points / float(SANITY_TARGET)) * bar_len)
                except Exception:
                    filled_w = int(sanity_points)
                filled_w = max(0, min(bar_len, filled_w))
                bar = "[" + "#" * filled_w + " " * (bar_len - filled_w) + "]"
                bar_full = f"SANITY: {bar}"
                bx = max(2, (maxx - len(bar_full)) // 2)
                safe_addstr(stdscr, maxy - 2, bx, bar_full)
            except Exception:
                pass
            safe_addstr(stdscr, maxy - 3, col, "[K] Back   [Q] Quit")
        except Exception:
            pass

        stdscr.refresh()

        # handle input
        try:
            ch = stdscr.getch()
        except Exception:
            ch = -1

        if ch != -1:
            try:
                c = chr(ch).lower()
            except Exception:
                c = ''
            if c in ('k', 'r'):
                return
            if c in ('q', '\x1b'):
                return
            for upg in blackhole_upgrades:
                if c == upg['key']:
                    buy_blackhole_upgrade(upg)
                    break
            # If player pressed the final upgrade key while viewing the curses
            # black hole, exit the view so the outer loop can process the
            # world transition triggered by the purchase.
            try:
                if c == 'n':
                    return
            except Exception:
                pass

        angle_offset += 6.0
        time.sleep(0.08)

def main():
    global world, money, timea, page, w1upgrades, depth, max_depth, ore_hp, ore_max_hp, ore_damage, auto_mine_damage, current_ore, ore_inventory, auto_miner_count, mining_page_unlocked, blackhole_page_unlocked, blackhole_growth, ships_count, blackhole_unlock_cost, admin_ore_granted_msg
    generate_city_layout()
    spawn_new_ore()  # Add this line
    # Configure terminal modes on POSIX only; Windows doesn't have termios/tty
    if not USING_WINDOWS:
        try:
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty.setcbreak(fd)
            except Exception:
                pass
        except Exception:
            fd = None
            old_settings = None
    else:
        fd = None
        old_settings = None

    enable_mouse()

    try:
        while True:
            key = get_key()
            clear()
            
            # Display admin message if set
            if admin_ore_granted_msg:
                print(f"\n{admin_ore_granted_msg}\n")
                admin_ore_granted_msg = ""
            
            # global quit: pressing 'q' anywhere used to quit the main loop
            # User requested 'q' to do nothing special; ignore here.
            try:
                if key and key.lower() == 'q':
                    pass
            except Exception:
                pass

            # If we returned from world 2 after being sent there by sanity, rotate the active sanity stage
            try:
                global awaiting_cycle_return, cycle_return_applied, sanity_stage, SANITY_WEIGHTS, sanity_points
                if awaiting_cycle_return and world == 1 and not cycle_return_applied:
                    # If the send was caused by mining progress, make Black Hole
                    # the next active sanity contributor so the player can pursue
                    # unlocking it as the next major milestone.
                    try:
                        global last_send_cause
                        if last_send_cause == 'mining':
                            sanity_stage = 3
                        else:
                            sanity_stage = (sanity_stage + 1) % len(SANITY_WEIGHTS)
                        # clear the remembered cause
                        last_send_cause = None
                    except Exception:
                        try:
                            sanity_stage = (sanity_stage + 1) % len(SANITY_WEIGHTS)
                        except Exception:
                            pass
                    cycle_return_applied = True
                    awaiting_cycle_return = False
                    sanity_points = 0
                    print("You feel your focus shift... new challenges matter more now.")
                    time.sleep(1.0)
                    # reset per-cycle one-time sanity event flags so milestones
                    # can be awarded again on the next cycle
                    try:
                        for k in list(sanity_awarded.keys()):
                            sanity_awarded[k] = False
                    except Exception:
                        pass
            except Exception:
                pass

            # (Sanity bar will be rendered at the bottom of each page)

            # --- WORLD 1 RESEARCH PAGE ---
            if world == 1 and page == 1:
                if not research_page_unlocked: print("Research not unlocked yet.")
                else:
                    print(f"Money: {money:.2f}\n")
                    timea += 0.1
                    if timea >= 1:
                        money += (
                            rate * adminmultiplier * othermultiplier * ships_money_multiplier()
                        )
                        timea = 0.0
                    print("=== RESEARCH ===\n")
                    draw_research_tree()
                    for res in research:
                        st = "— COMPLETED" if res["purchased"] else f"| Cost: ${res['cost']}"
                        print(f"[{res['key']}] {res['name']} {st}")
                if research_page_unlocked: print("\nPress [R] to switch pages.")
                # render sanity bar at bottom of this page
                try:
                    render_sanity_bar_console()
                except Exception:
                    pass
                if key:
                    k = key.lower()
                    if k == 'k':
                        if world == 1:
                            glitch_transition()
                            world = 2
                    elif k == 'q':
                        # ignore 'q' in main loop input handling
                        pass
                    elif k == 'r' and research_page_unlocked: page = 0
                    else:
                        for r in research:
                            if k == r["key"]:
                                buy_research(r)
                                break
                time.sleep(0.1)
                continue
            if world == 1 and page == 2:
                if not technology_page_unlocked: 
                    print("Mining not unlocked yet.")
                    print("\nPress [R] to return to City")
                else:
                    # Time and auto-mining
                    timea += 0.1
                    if timea >= 1:
                        money += (
                            rate * adminmultiplier * othermultiplier * ships_money_multiplier()
                        )
                        auto_mine_tick()
                        timea = 0.0
                    
                    # Get terminal width for layout
                    import shutil
                    term_width = shutil.get_terminal_size().columns
                    
                    # Left column content
                    left_content = []
                    left_content.append(f"Money: ${money:.2f}")
                    left_content.append("")
                    
                    # Mine shaft visualization (compact)
                    if current_ore is None:
                        spawn_new_ore()
                    
                    ore_name = current_ore["name"].upper()
                    ore_symbol = current_ore["color"]
                    hp_percent = ore_hp / ore_max_hp if ore_max_hp > 0 else 0
                    bar_width = 25
                    filled = int(hp_percent * bar_width)
                    hp_bar = "[" + "#" * filled + " " * (bar_width - filled) + "]"
                    
                    left_content.append("╔══════════════════════════════╗")
                    left_content.append(f"║   MINING SHAFT - DEPTH {depth}    ║")
                    left_content.append("╚══════════════════════════════╝")
                    left_content.append("       |           |")
                    left_content.append("      _|___________|_")
                    left_content.append(f"     /  {ore_symbol * 9}  \\")
                    left_content.append(f"    /  {ore_symbol * 11}  \\")
                    left_content.append(f"   /  {ore_symbol * 13}  \\")
                    left_content.append("  /___________________\\")
                    left_content.append("")
                    left_content.append(f"Ore: {ore_name}")
                    left_content.append(f"HP: {hp_bar}")
                    left_content.append(f"{ore_hp}/{ore_max_hp}")
                    left_content.append(f"Value: ${current_ore['value']}")
                    left_content.append(f"Click: {ore_damage} dmg")
                    left_content.append(f"Auto: {auto_mine_damage} DPS")
                    left_content.append("")
                    
                    # Ore Inventory (compact)
                    left_content.append("=== ORE INVENTORY ===")
                    for ore_name_inv, amount in ore_inventory.items():
                        if amount > 0:
                            left_content.append(f"{ore_name_inv.capitalize()}: {amount}")
                    if not any(ore_inventory.values()):
                        left_content.append("(None yet)")
                    left_content.append("")
                    
                    # Depth selector
                    left_content.append("=== DEPTH ===")
                    left_content.append(f"Current: {depth} | Max: {max_depth}")
                    depth_line = ""
                    for d in range(1, min(max_depth + 1, 6)):
                        marker = f"[{d}]" if d == depth else f" {d} "
                        depth_line += marker + " "
                    left_content.append(depth_line)
                    left_content.append("")
                    left_content.append(f"Auto-Miners: {auto_miner_count}")
                    left_content.append("")
                    left_content.append("[SPACE] Mine")
                    left_content.append("[R] Return to City")
                    left_content.append("[1-5] Change Depth")
                    # Offer Black Hole unlock when player has reached end of mining (depth 5)
                    if max_depth >= 5 and not blackhole_page_unlocked:
                        left_content.append("")
                        left_content.append("=== BLACK HOLE ===")
                        left_content.append(f"[U] Unlock Black Hole - Cost: ${blackhole_unlock_cost}")
                        left_content.append("(Requires Depth 5)")
                    
                    # Right column content - Tech Tree
                    right_content = []
                    right_content.append("=== MINING TECH TREE ===")
                    right_content.append("")
                    
                    # Draw compact tech tree
                    nodes = []
                    for tech in technology:
                        mark = "X" if tech["purchased"] else " "
                        nodes.append(f"[{tech['key'].upper()}:{mark}]")
                    
                    while len(nodes) < 20:
                        nodes.append("[  : ]")
                    
                    tree_lines = [
                        f"        {nodes[0]}",
                        "           |",
                        "     ┌─────┴─────┐",
                        f"  {nodes[1]}       {nodes[2]}",
                        "     |           |",
                        " ┌───┴───┐       |",
                        f"{nodes[3]} {nodes[4]} {nodes[5]}",
                        " |       |       |",
                        f"{nodes[6]} {nodes[7]} {nodes[8]} {nodes[9]}",
                        " └───┬───┴───────┘",
                        "     |",
                        f" {nodes[10]} {nodes[11]}",
                        " └───┴───┬───┐",
                        f"      {nodes[12]} {nodes[13]}",
                        "  ┌───┴───┐   |",
                        f"{nodes[14]} {nodes[15]} {nodes[16]}",
                        "  └───┬───┴───┘",
                        "      |",
                        f"  {nodes[17]} {nodes[18]}",
                        "  └───┬───┘",
                        "      |",
                        f"   {nodes[19]}",
                    ]
                    
                    right_content.extend(tree_lines)
                    right_content.append("")
                    right_content.append("=== AVAILABLE TECHS ===")
                    
                    # Available upgrades (compact)
                    available_count = 0
                    for tech in technology:
                        if tech["purchased"]:
                            continue
                        
                        # Check if unlocked
                        is_unlocked = False
                        if tech["key"] == "1":
                            is_unlocked = True
                        else:
                            for prev_tech in technology:
                                if prev_tech["purchased"] and tech["key"] in prev_tech.get("unlocks", []):
                                    is_unlocked = True
                                    break
                        
                        if is_unlocked:
                            available_count += 1
                            
                            # Format ore costs (compact)
                            ore_cost_str = ""
                            for ore_name_cost, amount in tech["ore_costs"].items():
                                ore_cost_str += f"{ore_name_cost[:3]}:{amount} "
                            ore_cost_str = ore_cost_str.strip() if ore_cost_str else "Free"
                            
                            money_str = f"${tech['money_cost']}"
                            
                            # Shorten long names
                            tech_name = tech['name']
                            if len(tech_name) > 18:
                                tech_name = tech_name[:15] + "..."
                            
                            right_content.append(f"[{tech['key'].upper()}] {tech_name}")
                            right_content.append(f"    {ore_cost_str} | {money_str}")
                            right_content.append(f"    {tech['desc']}")
                    
                    if available_count == 0:
                        right_content.append("(None available)")
                    
                    # Print two columns side by side
                    left_width = 35
                    max_lines = max(len(left_content), len(right_content))
                    
                    for i in range(max_lines):
                        left_line = left_content[i] if i < len(left_content) else ""
                        right_line = right_content[i] if i < len(right_content) else ""
                        
                        # Pad left column to fixed width
                        left_line = left_line[:left_width].ljust(left_width)
                        
                        print(f"{left_line}  {right_line}")

                # render sanity bar at bottom of this page
                try:
                    render_sanity_bar_console()
                except Exception:
                    pass

                if key:
                    k = key.lower()
                    if k == ' ':
                        mine_ore()
                    elif k == 'k':
                        glitch_transition()
                        world = 2
                    elif k == 'q':
                        # ignore 'q' — do not quit
                        pass
                    elif k == 'r': 
                        page = 0
                    elif k == 'u' and max_depth >= 5 and not blackhole_page_unlocked:
                        # Unlock black hole from mining end
                        # Requires: 1 orichalcum_shard (depth 5 only ore) + money cost
                        shard_count = ore_inventory.get('orichalcum_shard', 0)
                        if shard_count >= 1 and money >= blackhole_unlock_cost:
                            money -= blackhole_unlock_cost
                            ore_inventory['orichalcum_shard'] -= 1
                            blackhole_page_unlocked = True
                            try:
                                award_sanity_event('bh_unlock')
                            except Exception:
                                pass
                            try:
                                # also send player to world 2 on BH unlock
                                trigger_send_to_world2('blackhole')
                            except Exception:
                                pass
                        else:
                            # not enough ore or money; ignore
                            pass
                    elif k in '12345':
                        # First check if this key is a technology key
                        is_tech_key = False
                        for tech in technology:
                            if k == tech["key"]:
                                # Check if this tech is available to purchase
                                is_unlocked = False
                                if tech["key"] == "1":
                                    is_unlocked = True
                                else:
                                    for prev_tech in technology:
                                        if prev_tech["purchased"] and tech["key"] in prev_tech.get("unlocks", []):
                                            is_unlocked = True
                                            break
                                
                                if is_unlocked and not tech["purchased"]:
                                    buy_technology(tech)
                                    is_tech_key = True
                                    break
                        
                        # If not a tech key, treat as depth change
                        if not is_tech_key:
                            new_depth = int(k)
                            if new_depth <= max_depth:
                                depth = new_depth
                                spawn_new_ore()
                                # award half-mining milestone when first reaching halfway depth
                                try:
                                    half_th = (max_depth + 1) // 2
                                    if depth >= half_th:
                                        try:
                                            award_sanity_event('mine_half')
                                        except Exception:
                                            pass
                                except Exception:
                                    pass
                    else:
                        # Handle other technology keys (q, w, e, r, t, y, u, i, o, p, 0)
                        for tech in technology:
                            if k == tech["key"]: 
                                buy_technology(tech)
                                break
                
                time.sleep(0.1)
                continue
            if world == 1 and page == 0:
                timea += 0.1
                if timea >= 1:
                    money += (
                        rate * adminmultiplier * othermultiplier * ships_money_multiplier()
                    )
                    timea = 0.0

                print(f"Money: {money:.2f}\n")
                update_building_heights(w1upgrades)
                draw_city()

                print("\n=== UPGRADES ===")
                any_seen = False
                for upg in upgrades:
                    if money >= upg["cost"] * 0.1: upg["seen"] = True
                    if upg["seen"]:
                        any_seen = True
                        status = f"+{upg['rate_inc']}/sec | Cost: ${upg['cost']}" if upg["count"] < upg["max"] else "MAXED"
                        if upg['max'] == 1:
                            cnt_str = f"({upg['count']})"
                        else:
                            cnt_str = f"({upg['count']}/{upg['max']})"
                        print(f"[{upg['key'].upper()}] {upg['name']} {cnt_str} {status}")
                if not any_seen: print("(No upgrades available yet...)")
                if research_page_unlocked: print("\nPress [R] to go to Research.")
                if technology_page_unlocked: print("Press [T] to go to Technology.")
                # Black hole page access
                if blackhole_page_unlocked:
                    print("Press [B] to open the Black Hole page.")
                # (Orichalcum shards are intentionally hidden from main page display)
                print("Press [M] to Admin-Unlock Black Hole (debug)")
                try:
                    render_sanity_bar_console()
                except Exception:
                    pass

            # --- WORLD 1: BLACK HOLE PAGE ---
            if world == 1 and page == 3:
                # FIRST BH PAGE VISIT: Award sanity if first time entering
                try:
                    global blackhole_page_first_visit
                    if not blackhole_page_first_visit:
                        award_sanity_event('bh_first_visit')
                        blackhole_page_first_visit = True
                except Exception:
                    pass
                
                # income and auto effects
                timea += 0.1
                if timea >= 1:
                    money += (
                        rate * adminmultiplier * othermultiplier *
                        ships_money_multiplier()
                    )
                    timea = 0.0

                # render black hole (animated curses view)
                disable_mouse()
                try:
                    curses.wrapper(curses_blackhole_view)
                except Exception:
                    # fallback to static render if curses fails
                    print(f"Money: {money:.2f}\n")
                    draw_blackhole_page()
                    time.sleep(0.5)
                flush_stdin()
                enable_mouse()
                # return to city after viewing
                page = 0
                print("\nPress [R] to return to City.")

                if key:
                    k = key.lower()
                    if k == 'r':
                        page = 0
                    elif k == 'k':
                        glitch_transition()
                        world = 2
                    elif k == 'q':
                        # ignore 'q' — do not quit
                        pass
                    else:
                        for upg in blackhole_upgrades:
                            if k == upg["key"]:
                                buy_blackhole_upgrade(upg)
                                break

                time.sleep(0.1)
                continue

            # --- WORLD 2 MAP VIEW (curses) ---
            if world == 2:
                # open a curses-based full-screen map and wait for click
                # disable raw mouse reporting from the outer code while curses runs
                disable_mouse()
                if HAVE_CURSES:
                    try:
                        region_res = curses.wrapper(curses_map_view)
                    except Exception:
                        region_res = (None, False)
                else:
                    region_res = map_view_fallback()
                # flush any leftover bytes (escape sequences) so outer loop doesn't misinterpret
                flush_stdin()
                # re-enable outer mouse reporting
                enable_mouse()
                # region_res is (region_name, did_combat) or (None, False)
                try:
                    region, did_combat = region_res if isinstance(region_res, tuple) else (region_res, False)
                except Exception:
                    region, did_combat = (None, False)

                if region:
                    if region == "world4_button":
                        # Clicked on World 4 button
                        world = 4
                    elif did_combat:
                        # curses already ran combat and returned — check if should return to world 1
                        # (perform_player_action already set world = 1 if needed)
                        if world == 1:
                            glitch_transition()
                    else:
                        # enter non-curses dungeon (fallback)
                        world = 3
                        region_name = region.replace("_", " ").upper()
                        print(f"\nYou clicked {region_name}. Entering Dungeon...")
                        time.sleep(0.3)
                # If map was canceled (returned None), stay in world 2
                # Player can only return to world 1 through dungeon progression

            # --- DUNGEON / COMBAT VIEW ---
            if world == 3:
                # initialize combat on first entry
                if not combat_started:
                    enter_combat()
                draw_combat_ui()

            # --- WORLD 4 KILL LIST ---
            if world == 4:
                kill_list_view()

            # --- INPUT HANDLING ---

            if key == '\x1b':
                rest = read_mouse_sequence()
                if rest and rest.startswith("[<"):
                    try:
                        core = rest[2:-1]
                        parts = core.split(";")
                        if len(parts) >= 3:
                            b_str = parts[0]
                            x_str = parts[1]
                            y_str = parts[2].rstrip('Mm')  # Remove trailing M or m
                            b, x, y = int(b_str), int(x_str), int(y_str)
                            
                            # Only handle left click (button 0) press
                            if b == 0:
                                # Check if we're on the mining page and clicked on the ore area
                                if world == 1 and page == 2 and mining_page_unlocked:
                                    # Ore shaft is at rows 6-14 (the visual part with ore symbols)
                                    # and columns 1-32 in the left column
                                    if 6 <= y <= 14 and 1 <= x <= 32:
                                        mine_ore()  # Mine when clicking on ore visual
                                # If we're on the Black Hole page, allow clicking to "Break The Reality"
                                # by clicking anywhere on the right column where upgrades are shown.
                                elif world == 1 and page == 3:
                                    try:
                                        # find the blackhole upgrade with key 'n' and attempt to buy it
                                        for upg in blackhole_upgrades:
                                            if upg.get('key') == 'n':
                                                # attempt purchase; buy_blackhole_upgrade will handle cost and effects
                                                buy_blackhole_upgrade(upg)
                                                break
                                    except Exception:
                                        pass
                                
                    except Exception:
                        pass  # Ignore mouse parsing errors
                # Don't process this as keyboard input
                key = None
            
            # Handle keyboard input
            if key and key != '\x1b':
                k = key.lower()
                if k == 'z':
                    # Global admin shortcut: give 50 of each ore regardless of page
                    try:
                        for ore_name in ore_inventory:
                            ore_inventory[ore_name] += 50
                        admin_ore_granted_msg = "[ADMIN] +50 ore granted!"
                    except Exception:
                        pass
                    continue
                if k == 'q': 
                    pass
                elif k == 'k':
                    if world == 1:
                        glitch_transition()
                        world = 2
                elif k == 'r' and research_page_unlocked and world == 1: 
                    page = 1
                elif k == 't' and technology_page_unlocked and world == 1:
                    page = 2
                    # If we were sent to World 2 from mining at depth 3, award
                    # a one-shot sanity bump when the player visits Technology
                    try:
                        if last_send_depth == 3 and not sanity_awarded.get('post_depth3_return', False):
                            add_sanity(SANITY_INCREMENTS.get('technology', 1))
                            sanity_awarded['post_depth3_return'] = True
                    except Exception:
                        pass
                elif world == 3:
                    # combat action keys
                    if k == 'a':
                        perform_player_action('attack')
                    elif k == 'h':
                        perform_player_action('heal')
                    elif k == 'u':
                        perform_player_action('ability')
                elif world == 1 and page == 0:
                    if k == 'b':
                        if blackhole_page_unlocked:
                            page = 3
                        else:
                            # not unlocked yet
                            pass
                    elif k == 'm':
                        # admin unlock (debug)
                        blackhole_page_unlocked = True
                    else:
                        for upg in upgrades:
                            if k == upg["key"]:
                                buy_upgrade(upg)
                                break
                elif world == 1 and page == 1:
                    for r in research:
                        if k == r["key"]: 
                            buy_research(r)
                            break
                elif world == 1 and page == 2:
                    if k == ' ':
                        mine_ore()
                    elif k in '12345':
                        new_depth = int(k)
                        if new_depth <= max_depth:
                            depth = new_depth
                            spawn_new_ore()
                    elif k == 'z':
                        # ADMIN BUTTON: give 50 of each ore when pressed in Mining
                        print("key z pressed: granting admin ore...")
                        try:
                            for ore_name in ore_inventory:
                                ore_inventory[ore_name] += 50
                            admin_ore_granted_msg = "[ADMIN] +50 ore granted!"
                        except Exception:
                            print("Failed to grant admin ore.")
                    else:
                        for tech in technology:
                            if k == tech["key"]: 
                                buy_technology(tech)
                                break
            
            time.sleep(0.1)

    finally:
        # disable mouse
        try:
            disable_mouse()
        except Exception:
            pass

        # hot garbage
        if not USING_WINDOWS and fd is not None and old_settings is not None:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            except Exception:
                pass

        clear()
        print("Exited cleanly.")

if __name__ == "__main__":
    main()
