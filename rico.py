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

# --- MAP ART ---
map_art = [
"                 N",
"                 ^",
"                 |",
"         ~ ~ ~ ~ | ~ ~ ~ ~ ~ ~ ~ ~",
" River Bend ---> |                   /\\",
"             ~ ~ | ~ ~ ~   /\\  /\\   /  \\         /\\    /\\ ",
"                 |        /  \\/  \\_/    \\  /\\   /  \\  /  \\",
"  ~ ~ ~ ~ ~ ~ ~  |  ~ ~  /                \\/  \\_/    \\/    \\",
"  ~    Fisher's  |      /   HILLS &                     MOUNTAIN",
"        Dock     |     /     RIDGES                         ^",
"                 |    /                                        \\",
"   ~ ~ ~ ~ ~ ~ ~  |   /                                          \\",
"                 _|__/____    ________   ____   ____   ____   ____\\__",
"                /       /|  /  FARM  /| /CAST/ /MARK/ /RUIN/ /TOWN/ / |",
"               / Field / | /-------/ |/_____/ /____/ /____/ /____/ /  |",
"              /_______/  | | Barn |  |  ____  ____  ____  ____  |   | |",
"              |  Orchard|/  |______| /| /____/ /____/ /____/ /____|   | |",
"              |  (apple)    ________ /                           |   | |",
"              |            /  MILL  /        ROAD -->====>======/___|_|",
"              |___________/_______ /   BRIDGE                     |",
"                     |        ||                                   |",
"                     |   ~~~~~||~~~~~        Main Street           |",
"                     |   ~~~~~||~~~~~  [Town Square] (market)      |",
"                     |        ||                                   |",
"     FOREST  /\\  /\\  |  /\\    ||     /\\    /\\    /\\   /\\    /\\     |",
"           /  \\/  \\  | /  \\   ||    /  \\  /  \\  /  \\ /  \\  /  \\    |",
"          /        \\ |/    \\  ||   /    \\/    \\/    \\/    \\/    \\   |",
"         /  WILD WOODS\\     \\ ||  /   Woodland Path (to ruins) \\  |",
"        /  (deer, owls) \\    \\|| /                                \\ |",
"       /________________\\    \\|/      ╔══════════════════════════╗\\|",
"                             \\        ║      GRAVEYARD          ║ \\",
"                              \\       ║  XXXX  X  XX   X  XX   X ║  \\",
"                               \\      ║  X  X  XXXX   X  XX   X  ║   \\",
"                                \\     ║  XX   X X    XX   X  XXX ║    \\",
"                                 \\    ║  Old stones, willow     ║     \\",
"                                  \\   ║  lantern, broken gate   ║      \\",
"                                   \\  ╚════════════════════════╝       \\",
"                                    \\                                 \\",
"                                     \\           +----+                 \\",
"                                      \\          |CAVE| <- entrance      \\",
"                                       \\         +----+                  \\",
"                                        \\                                \\",
"                                         \\        MARSHLAND  ~ ~ ~ ~      \\",
"                                          \\      ~ ~ ~ ~ ~ ~ ~ ~ ~ ~       \\",
"                                           \\                            /",
"                                            \\                          /",
"                                             \\________________________/"
]

# clickable labels
click_labels = {"GRAVEYARD": [], "CAVE": []}
def preprocess_map_labels():
    for row_i, row in enumerate(map_art):
        for label in click_labels.keys():
            idx = row.find(label)
            if idx != -1:
                for x in range(idx, idx + len(label)):
                    click_labels[label].append((row_i, x))
preprocess_map_labels()

def locate_labels_in_map(map_lines):
    labels = {}
    for i, line in enumerate(map_lines, start=1):
        if "GRAVEYARD" in line:
            labels["graveyard"] = (i, line.index("GRAVEYARD") + 1)
        if "CAVE" in line:
            labels["cave"] = (i, line.index("CAVE") + 1)
    return labels

def make_absolute_zones(map_lines, map_top_row):
    labels = locate_labels_in_map(map_lines)
    zones = {}
    pad_col = 4
    pad_row_top = 0
    pad_row_bottom = 1
    for name, (r, c) in labels.items():
        label_len = len(name.upper())
        zones[name] = {
            "row_start": map_top_row + r - 1 - pad_row_top,
            "row_end":   map_top_row + r - 1 + pad_row_bottom,
            "col_start": max(1, c - pad_col),
            "col_end":   c + label_len - 1 + pad_col,
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

# --- RESEARCH DATA ---
research = [
    {"key": "1", "name": "AAAAA",
     "cost": 500000, "purchased": False,
     "effect": "adminmultiplier *= 1.5", "req": "none"},
    {"key": "2", "name": "BBBBB",
     "cost": 2000000, "purchased": False,
     "effect": "othermultiplier *= 2", "req": "1"},
     {"key": "3", "name": "CCCCC",
     "cost": 2000000, "purchased": False,
     "effect": "othermultiplier *= 2", "req": "1"},
    {"key": "4", "name": "DDDDD",
     "cost": 2000000, "purchased": False,
     "effect": "othermultiplier *= 2", "req": "2"},
    {"key": "5", "name": "EEEEE",
     "cost": 2000000, "purchased": False,
     "effect": "othermultiplier *= 2", "req": "2, 3"},
    {"key": "6", "name": "FFFFF",
     "cost": 2000000, "purchased": False,
     "effect": "othermultiplier *= 2", "req": "3"},
    {"key": "7", "name": "GGGGG",
     "cost": 2000000, "purchased": False,
     "effect": "othermultiplier *= 2", "req": "4, 5"},
    {"key": "8", "name": "IIIII",
     "cost": 2000000, "purchased": False,
     "effect": "othermultiplier *= 2", "req": "6"},
    {"key": "9", "name": "JJJJJ",
     "cost": 2000000, "purchased": False,
     "effect": "othermultiplier *= 2", "req": "7, 8"},
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

# --- INPUT / CLEAR ---
def clear(): os.system("cls" if os.name == "nt" else "clear")
def get_key():
    dr, _, _ = select.select([sys.stdin], [], [], 0)
    if dr: return sys.stdin.read(1)
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
                     ||                        ||
          ┌────────{nodes[1]}────────┐   ┌────────{nodes[2]}────────┐
          ||                      ||   ||                        ||
          {nodes[3]}────┐   ┌────{nodes[4]}               {nodes[5]}─  
                       ||   ||                               || 
                       {nodes[7]}────┐                 ┌──{nodes[8]}
                                      ---{nodes[9]}────

    """
    print(tree)

# --- MAIN LOOP ---
def main():
    global world, money, timea, page, w1upgrades
    generate_city_layout()
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    enable_mouse()

    try:
        while True:
            key = get_key()
            clear()

            # --- WORLD 1 RESEARCH PAGE ---
            if world == 1 and page == 1:
                if not research_page_unlocked: print("Research not unlocked yet.")
                else:
                    print("=== RESEARCH ===\n")
                    draw_research_tree()
                    for res in research:
                        st = "— COMPLETED" if res["purchased"] else f"| Cost: ${res['cost']}"
                        print(f"[{res['key']}] {res['name']} {st}")
                if research_page_unlocked: print("\nPress [R] to switch pages.")
                if key:
                    k = key.lower()
                    if k == 'k':
                        if world == 1:
                            world = 2
                        elif world == 2:
                            world = 1
                        elif world == 3:
                            world = 1
                    elif k == 'q': break
                    elif k == 'r' and research_page_unlocked: page = 0
                    else:
                        for r in research:
                            if k == r["key"]: buy_research(r); break
                time.sleep(0.1)
                continue

            # --- WORLD 1 NORMAL PAGE ---
            if world == 1:
                timea += 0.1
                if timea >= 1:
                    money += rate * adminmultiplier * othermultiplier
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
                        print(f"[{upg['key'].upper()}] {upg['name']} ({upg['count']}/{upg['max']}) {status}")
                if not any_seen: print("(No upgrades available yet...)")
                if research_page_unlocked: print("\nPress [R] to switch pages.")
                sanity = 20 - w1upgrades
                bar = int((sanity / 20) * length)
                print("\n[" + "#" * bar + " " * (length - bar) + "]\n")

            # --- WORLD 2 MAP VIEW ---
            if world == 2:
                header_lines = ["=== WORLD 2: MAP ===","Click on GRAVEYARD or CAVE to return to World 1.",""]
                for line in header_lines: print(line)
                map_top_row = len(header_lines) + 1
                absolute_zones = make_absolute_zones(map_art, map_top_row)
                for line in map_art: print(line)
                # Debug clickable zones
                print("\nClickable zones (for debug):")
                for name, z in absolute_zones.items():
                    print(f" - {name}: rows {z['row_start']}-{z['row_end']}, cols {z['col_start']}-{z['col_end']}")

            # --- DUNGEON VIEW ---
            if world == 3:
                print("=== DUNGEON ===\n")
                print("This is a dungeon\n")
                print("Press [K] to return to World 1 or [Q] to quit.")

            # --- INPUT HANDLING ---
            if key:
                if key == '\x1b':
                    rest = read_mouse_sequence()
                    if rest and rest.startswith("[<"):
                        try:
                            core = rest[2:-1]
                            b_str, x_str, y_str = core.split(";")
                            b, x, y = int(b_str), int(x_str), int(y_str)
                            if world == 2:
                                absolute_zones = make_absolute_zones(map_art, len(header_lines)+1)
                                for name, z in absolute_zones.items():
                                    if z["row_start"] <= y <= z["row_end"] and z["col_start"] <= x <= z["col_end"]:
                                        world = 3
                                        print(f"\nYou clicked {name}. Entering Dungeon...")
                                        time.sleep(0.3)
                                        break
                        except: pass
                else:
                    k = key.lower()
                    if k == 'q': break
                    elif k == 'k':
                        if world == 1:
                            world = 2
                        elif world == 2:
                            world = 1
                        elif world == 3:
                            world = 1
                    elif k == 'r' and research_page_unlocked and world == 1: page = 1
                    elif world == 1 and page == 0:
                        for upg in upgrades:
                            if k == upg["key"]: buy_upgrade(upg); break
                    elif world == 1 and page == 1:
                        for r in research:
                            if k == r["key"]: buy_research(r); break

            time.sleep(0.1)

    finally:
        disable_mouse()
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        clear()
        print("Exited cleanly.")

if __name__ == "__main__":
    main()
