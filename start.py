import os
import sys
import termios
import time
import select
import tty
import random

# --- GAME STATE ---
world = 1
timea = 0.0
money = 0
rate = 1
adminmultiplier = 10000
othermultiplier = 1.0
page = 0
research_page_unlocked = False
w1upgrades = 0
length = 40

map_art = r"""
                 N
                 ^
                 |
         ~ ~ ~ ~ | ~ ~ ~ ~ ~ ~ ~ ~
 River Bend ---> |                   /\
             ~ ~ | ~ ~ ~   /\  /\   /  \         /\    /\ 
                 |        /  \/  \_/    \  /\   /  \  /  \
  ~ ~ ~ ~ ~ ~ ~  |  ~ ~  /                \/  \_/    \/    \
  ~    Fisher's  |      /   HILLS &                     MOUNTAIN
        Dock     |     /     RIDGES                         ^
                 |    /                                        \
   ~ ~ ~ ~ ~ ~ ~  |   /                                          \
                 _|__/____    ________   ____   ____   ____   ____\__
                /       /|  /  FARM  /| /CAST/ /MARK/ /RUIN/ /TOWN/ / |
               / Field / | /-------/ |/_____/ /____/ /____/ /____/ /  |
              /_______/  | | Barn |  |  ____  ____  ____  ____  |   | |
              |  Orchard|/  |______| /| /____/ /____/ /____/ /____|   | |
              |  (apple)    ________ /                           |   | |
              |            /  MILL  /        ROAD -->====>======/___|_|
              |___________/_______ /   BRIDGE                     |
                     |        ||                                   |
                     |   ~~~~~||~~~~~        Main Street           |
                     |   ~~~~~||~~~~~  [Town Square] (market)      |
                     |        ||                                   |
     FOREST  /\  /\  |  /\    ||     /\    /\    /\   /\    /\     |
           /  \/  \  | /  \   ||    /  \  /  \  /  \ /  \  /  \    |
          /        \ |/    \  ||   /    \/    \/    \/    \/    \   |
         /  WILD WOODS\     \ ||  /   Woodland Path (to ruins) \  |
        /  (deer, owls) \    \|| /                                \ |
       /________________\    \|/      ╔══════════════════════════╗\|
                             \        ║      GRAVEYARD          ║ \
                              \       ║  XXXX  X  XX   X  XX   X ║  \
                               \      ║  X  X  XXXX   X  XX   X  ║   \
                                \     ║  XX   X X    XX   X  XXX ║    \
                                 \    ║  Old stones, willow     ║     \
                                  \   ║  lantern, broken gate   ║      \
                                   \  ╚════════════════════════╝       \
                                    \                                 \
                                     \           +----+                 \
                                      \          |CAVE| <- entrance      \
                                       \         +----+                  \
                                        \                                \
                                         \        MARSHLAND  ~ ~ ~ ~      \
                                          \      ~ ~ ~ ~ ~ ~ ~ ~ ~ ~       \
                                           \                            /
                                            \                          /
                                             \________________________/

"""

# --- UPGRADE DATA ---
upgrades = [
    {"key": "a", "name": "Hire Worker", "rate_inc": 1, "base_cost": 10,
     "cost": 10, "multiplier": 1.15, "count": 0, "max": 100, "seen": False},
    {"key": "s", "name": "Hire Manager", "rate_inc": 10, "base_cost": 100,
     "cost": 100, "multiplier": 1.15, "count": 0, "max": 75, "seen": False},
    {"key": "d", "name": "Hire Senior Manager", "rate_inc": 100,
     "base_cost": 1000, "cost": 1000, "multiplier": 1.15, "count": 0,
     "max": 50, "seen": False},
    {"key": "f", "name": "Upgrade Hardware", "rate_inc": 10000,
     "base_cost": 10000, "cost": 10000, "multiplier": 1.15, "count": 0,
     "max": 30, "seen": False},
    {"key": "g", "name": "Unlock Research", "rate_inc": 0,
     "base_cost": 1000000, "cost": 1000000, "multiplier": 0, "count": 0, "seen": False, "max": 1},
]

# --- RESEARCH DATA ---
research = [
    {"key": "1", "name": "Boost Admin Systems",
     "cost": 500000, "purchased": False,
     "effect": "adminmultiplier *= 1.5"},
    {"key": "2", "name": "Machine Learning Boost",
     "cost": 2000000, "purchased": False,
     "effect": "othermultiplier *= 2"},
]

# --- CITY DATA ---
city_buildings = []

def generate_city_layout():
    """Generate static city layout with more designs and random offsets."""
    global city_buildings
    num_buildings = 25
    types = [
        {"name": "house", "roof": "▲", "body": "█"},
        {"name": "factory", "roof": "■", "body": "▒"},
        {"name": "tower", "roof": "▲", "body": "▌"},
        {"name": "skyscraper", "roof": "■", "body": "█"},
        {"name": "dome", "roof": "◯", "body": "█"},
        {"name": "antenna", "roof": "│", "body": "█"},
        {"name": "villa", "roof": "♢", "body": "▓"},
        {"name": "castle", "roof": "♜", "body": "█"},
        {"name": "tent", "roof": "△", "body": "▒"}
    ]
    mid = num_buildings // 2

    city_buildings = []
    for i in range(num_buildings):
        width = 1 + (mid - abs(i - mid)) // 2  # wider toward center
        b_type = random.choice(types)
        offset = random.randint(0, 2)
        city_buildings.append({
            "width": width,
            "type": b_type,
            "base": 1,
            "height": 1,
            "pos": i,
            "mid_offset": abs(i - mid),
            "rand_offset": offset
        })


def update_building_heights(upgrades_count):
    """Grow building heights toward the middle based on total upgrades, preserving random offsets."""
    max_height = 15
    for b in city_buildings:
        pyramid_height = int(upgrades_count / 2 / (b["mid_offset"] + 1)) + 1
        b["height"] = min(max_height, pyramid_height + b["rand_offset"])


def draw_city():
    width = 100
    max_height = 15
    spacing = 1

    # Clouds
    cloud_line = "".join("☁" if random.random() > 0.85 else " " for _ in range(width))
    print(cloud_line)
    print("")

    for y in reversed(range(max_height)):
        line = ""
        for b in city_buildings:
            b_height = b["height"]
            b_width = b["width"]
            b_type = b["type"]

            if y < b_height:
                if y == b_height - 1:
                    # Roof
                    line += b_type["roof"] * b_width
                else:
                    # Body
                    line += b_type["body"] * b_width
            else:
                line += " " * b_width
            line += " " * spacing
        print(line.center(width))

    print("_" * width)

# --- INPUT / CLEAR ---
def clear():
    os.system("cls" if os.name == "nt" else "clear")

def get_key():
    dr, _, _ = select.select([sys.stdin], [], [], 0)
    if dr:
        return sys.stdin.read(1)
    return None

# --- BUY FUNCTIONS ---
def buy_upgrade(upg):
    global money, rate, w1upgrades, research_page_unlocked
    if upg["count"] >= upg["max"]: return
    if money < upg["cost"]: return
    money -= upg["cost"]
    rate += upg["rate_inc"]
    upg["count"] += 1
    w1upgrades += 1
    if upg["name"] == "Unlock Research":
        research_page_unlocked = True
    if upg["count"] < upg["max"]:
        upg["cost"] = int(upg["cost"] * upg["multiplier"])

def buy_research(res):
    global money, adminmultiplier, othermultiplier
    if res["purchased"]: return
    if money < res["cost"]: return
    money -= res["cost"]
    res["purchased"] = True
    exec(res["effect"], globals())

# --- MOUSE SUPPORT (xterm) ---
def enable_mouse():
    sys.stdout.write("\033[?1003h")  # high motion tracking (press & release)
    sys.stdout.flush()

def disable_mouse():
    sys.stdout.write("\033[?1003l")
    sys.stdout.flush()

def read_mouse_sequence():
    """Read rest of mouse escape sequence after '\x1b' was consumed.
       Returns the full sequence string (including the leading '[') or None."""
    # We expect sequences like: [<b;x;yM  or [<b;x;ym
    seq = ""
    # read until final char 'M' or 'm' (terminator)
    while True:
        c = sys.stdin.read(1)
        if not c:
            return None
        seq += c
        if c in ("M", "m"):
            break
    return seq

# --- CLICK ZONE UTILITIES ---
def locate_labels_in_map(map_text):
    """Return a dict of label positions (row_index (1-based), col_start (1-based)) for labels we care about."""
    lines = map_text.strip("\n").split("\n")
    labels = {}
    for i, line in enumerate(lines, start=1):
        if "GRAVEYARD" in line:
            col = line.index("GRAVEYARD") + 1
            labels["graveyard"] = (i, col)
        if "CAVE" in line:
            col = line.index("CAVE") + 1
            labels["cave"] = (i, col)
    return labels, lines

def make_absolute_zones(map_lines, map_top_row):
    """Given map_lines and top row where the map starts on the terminal, produce absolute click zones."""
    labels, lines = locate_labels_in_map("\n".join(map_lines))
    zones = {}
    pad_cols = 4
    pad_rows_above = 0
    pad_rows_below = 1
    for name, (r, c) in labels.items():
        label_len = len(name.upper())
        row_start = map_top_row + r - 1 - pad_rows_above
        row_end = map_top_row + r - 1 + pad_rows_below
        col_start = max(1, c - pad_cols)
        col_end = c + label_len - 1 + pad_cols
        zones[name] = {
            "row_start": row_start,
            "row_end": row_end,
            "col_start": col_start,
            "col_end": col_end
        }
    return zones

# --- MAIN LOOP ---
def main():
    global world, timea, money, page, w1upgrades

    generate_city_layout()

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    enable_mouse()

    try:
        while True:
            key = get_key()
            clear()

            # WORLD 1: city / upgrades
            if world == 1:
                timea += 0.1
                if timea >= 1:
                    money += rate * adminmultiplier * othermultiplier
                    timea = 0.0

                print(f"Money: {money:.2f}\n")

                update_building_heights(w1upgrades)
                draw_city()

                print("\n=== UPGRADES ===" if page == 0 else "\n=== RESEARCH ===")

                if page == 0:
                    any_seen = False
                    for upg in upgrades:
                        if money >= upg.get("cost", 0) * 0.1:
                            upg["seen"] = True
                        if upg.get("seen", False):
                            any_seen = True
                            status = f"+{upg.get('rate_inc',0)}/sec | Cost: ${upg.get('cost',0)}" \
                                if upg.get('count',0) < upg.get('max',100) else "MAXED"
                            print(f"[{upg.get('key','?').upper()}] {upg.get('name','Unknown')} "
                                f"({upg.get('count',0)}/{upg.get('max',100)}) {status}")
                    if not any_seen:
                        print("(No upgrades available yet...)")

                elif page == 1:
                    if not research_page_unlocked:
                        print("Research not unlocked yet.")
                    else:
                        for res in research:
                            status = "— COMPLETED" if res["purchased"] else f"| Cost: ${res['cost']}"
                            print(f"[{res['key']}] {res['name']} {status}")

                if research_page_unlocked:
                    print("\nPress [R] to switch pages.")

                sanity = 20 - w1upgrades
                bar = int((sanity / 20) * length)
                empty = length - bar
                print("\n[" + "#" * bar + " " * empty + "]\n")

            # WORLD 2: map (clickable)
            elif world == 2:
                header_lines = [
                    "=== WORLD 2: MAP ===",
                    "Click on GRAVEYARD or CAVE to return to World 1.",
                    ""
                ]
                # Print header and then the map; because we clear screen before printing,
                # row 1 of terminal corresponds to the first printed line.
                for line in header_lines:
                    print(line)
                map_lines = map_art.strip("\n").split("\n")
                # top row where the map content starts (1-based)
                map_top_row = len(header_lines) + 1
                # compute click zones based on labels found in the map
                absolute_zones = make_absolute_zones(map_lines, map_top_row)

                # Print the map
                for line in map_lines:
                    print(line)

                # Provide a small guide showing absolute zone coords (optional - helpful for debugging)
                # comment this out in production if you don't want it shown:
                print("\nClickable zones (for debug):")
                for name, z in absolute_zones.items():
                    print(f" - {name}: rows {z['row_start']}-{z['row_end']}, cols {z['col_start']}-{z['col_end']}")

            # ---------- INPUT handling ----------
            if key:
                # Mouse event sequence begins with ESC
                if key == '\x1b':
                    rest = read_mouse_sequence()
                    if rest and rest.startswith("[<"):
                        # parts like "<b;x;yM"
                        try:
                            core = rest[2:-1]  # remove leading '<' and trailing 'M'/'m'
                            b_str, x_str, y_str = core.split(";")
                            b = int(b_str)
                            x = int(x_str)
                            y = int(y_str)
                            # Only check clicks if in world 2 (map)
                            if world == 2:
                                # recompute map zones (we compute earlier during print as absolute_zones)
                                # So regenerate them here (same logic).
                                map_lines = map_art.strip("\n").split("\n")
                                map_top_row = 3 + 1  # header_lines length (3) + 1
                                absolute_zones = make_absolute_zones(map_lines, map_top_row)

                                # if left-button press (b & 0b11 == 0) or (b & 0b3 == 0) in some terminals
                                # Many terminals encode button in b; treat any click as trigger
                                for name, z in absolute_zones.items():
                                    if (z["row_start"] <= y <= z["row_end"]
                                            and z["col_start"] <= x <= z["col_end"]):
                                        # zone hit: perform action (return to world 1)
                                        world = 1
                                        # optional: small feedback
                                        print(f"\nYou clicked {name}. Returning to World 1...")
                                        time.sleep(0.3)
                                        break
                        except Exception:
                            # ignore parse errors
                            pass
                    # drain any remaining input to avoid stuck sequences
                    # continue to next loop iteration
                else:
                    k = key.lower()
                    if k == 'k':
                        world = 2 if world == 1 else 1
                    elif k == 'q':
                        break
                    elif k == 'r' and world == 1 and research_page_unlocked:
                        page = (page + 1) % 2
                    elif world == 1:
                        if page == 0:
                            for upg in upgrades:
                                if k == upg["key"]:
                                    buy_upgrade(upg)
                                    break
                        elif page == 1:
                            for res in research:
                                if k == res["key"]:
                                    buy_research(res)
                                    break

            time.sleep(0.1)

    finally:
        disable_mouse()
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        clear()
        print("Exited cleanly.")

if __name__ == "__main__":
    main()
