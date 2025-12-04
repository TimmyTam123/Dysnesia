import os
import sys
import termios
import time
import select
import tty
import random
import unicodedata
import curses
import locale
locale.setlocale(locale.LC_ALL, '')

def flush_stdin(timeout=0.01):
    """Drain any pending bytes from stdin to avoid leftover escape sequences."""
    try:
        while True:
            dr, _, _ = select.select([sys.stdin], [], [], timeout)
            if not dr:
                break
            # read and discard
            sys.stdin.read(1024)
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

# --- GAME STATE ---
world = 1
timea = 0.0
money = 0
rate = 1
adminmultiplier = 10000
othermultiplier = 1.0
page = 0
research_page_unlocked = False
technology_page_unlocked = False
w1upgrades = 0
length = 40

# --- MINING STATE ---
current_ore = None
ore_hp = 100
ore_max_hp = 100
ore_damage = 10
auto_mine_damage = 0
depth = 1
max_depth = 1

# Ore inventory
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
}

mining_page_unlocked = False
auto_miner_count = 0

# --- COMBAT STATE ---
combat_started = False
player_hp = 100
player_max_hp = 100
enemy_hp = 80
enemy_max_hp = 80
player_heals = 3
combat_log = []
player_ability_charges = 1

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
     "cost": 1125000000, "purchased": False,
     "effect": "othermultiplier *= 5"},
    {"key": "7", "name": "Interlinked Drone Swarms",
     "cost": 20000000000, "purchased": False,
     "effect": "othermultiplier *= 10"},
    {"key": "8", "name": "Neural Cloud Integration",
     "cost": 400000000000, "purchased": False,
     "effect": "othermultiplier *= 15"},
    {"key": "9", "name": "Cryogenic Superconductors",
     "cost": 1200000000000, "purchased": False,
     "effect": "othermultiplier *= 20"},
    {"key": "0", "name": "Unlock Mining",
    "cost": 10000000000000, "purchased": False,
    "effect": "mining_page_unlocked = True"},
]

# --- ORE TYPES BY DEPTH ---
ore_types = {
    1: [  # Depth 1
        {"name": "stone", "color": "░", "hp": 50, "value": 1, "weight": 50},
        {"name": "coal", "color": "▓", "hp": 75, "value": 3, "weight": 30},
        {"name": "copper", "color": "▒", "hp": 100, "value": 5, "weight": 20},
    ],
    2: [  # Depth 2
        {"name": "coal", "color": "▓", "hp": 75, "value": 3, "weight": 30},
        {"name": "copper", "color": "▒", "hp": 100, "value": 5, "weight": 25},
        {"name": "iron", "color": "▓", "hp": 150, "value": 10, "weight": 25},
        {"name": "silver", "color": "░", "hp": 200, "value": 20, "weight": 20},
    ],
    3: [  # Depth 3
        {"name": "iron", "color": "▓", "hp": 150, "value": 10, "weight": 30},
        {"name": "silver", "color": "░", "hp": 200, "value": 20, "weight": 25},
        {"name": "gold", "color": "█", "hp": 300, "value": 50, "weight": 25},
        {"name": "emerald", "color": "◆", "hp": 400, "value": 100, "weight": 20},
    ],
    4: [  # Depth 4
        {"name": "gold", "color": "█", "hp": 300, "value": 50, "weight": 30},
        {"name": "emerald", "color": "◆", "hp": 400, "value": 100, "weight": 25},
        {"name": "ruby", "color": "♦", "hp": 500, "value": 200, "weight": 25},
        {"name": "diamond", "color": "◊", "hp": 750, "value": 500, "weight": 20},
    ],
    5: [  # Depth 5
        {"name": "diamond", "color": "◊", "hp": 750, "value": 500, "weight": 35},
        {"name": "mythril", "color": "▲", "hp": 1000, "value": 1000, "weight": 30},
        {"name": "adamantite", "color": "■", "hp": 1500, "value": 2000, "weight": 20},
        {"name": "orichalcum", "color": "★", "hp": 2500, "value": 5000, "weight": 15},
    ],
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
# --- TECHNOLOGY/MINING DATA ---
technology = [
    # Tier 1 - Basic tools
    {"key": "1", "name": "Stone Pickaxe", "ore_costs": {}, "money_cost": 0, 
     "damage": 15, "auto_damage": 0, "depth_unlock": 0, "purchased": False,
     "effect": "ore_damage += 15", "unlocks": ["2", "3"], "desc": "+15 damage"},
    
    {"key": "2", "name": "Iron Pickaxe", "ore_costs": {"stone": 10}, "money_cost": 100000, 
     "damage": 25, "auto_damage": 0, "depth_unlock": 0, "purchased": False,
     "effect": "ore_damage += 25", "unlocks": ["4", "5"], "desc": "+25 damage"},
    
    {"key": "3", "name": "Hire First Miner", "ore_costs": {"stone": 5, "coal": 3}, "money_cost": 50000, 
     "damage": 0, "auto_damage": 5, "depth_unlock": 0, "purchased": False,
     "effect": "auto_mine_damage += 5; auto_miner_count += 1", "unlocks": ["6"], "desc": "+5 auto damage"},
    
    # Tier 2 - Unlock Depth 2
    {"key": "4", "name": "Deeper Shaft", "ore_costs": {"coal": 10, "copper": 5}, "money_cost": 500000, 
     "damage": 0, "auto_damage": 0, "depth_unlock": 2, "purchased": False,
     "effect": "max_depth = max(max_depth, 2)", "unlocks": ["7", "8"], "desc": "Unlock Depth 2"},
    
    {"key": "5", "name": "Steel Pickaxe", "ore_costs": {"copper": 10, "iron": 5}, "money_cost": 750000, 
     "damage": 50, "auto_damage": 0, "depth_unlock": 0, "purchased": False,
     "effect": "ore_damage += 50", "unlocks": ["9"], "desc": "+50 damage"},
    
    {"key": "6", "name": "Mining Team", "ore_costs": {"coal": 15, "copper": 10}, "money_cost": 1000000, 
     "damage": 0, "auto_damage": 15, "depth_unlock": 0, "purchased": False,
     "effect": "auto_mine_damage += 15; auto_miner_count += 3", "unlocks": ["10"], "desc": "+15 auto damage"},
    
    # Tier 3 - Unlock Depth 3
    {"key": "7", "name": "Reinforced Shaft", "ore_costs": {"iron": 20, "silver": 10}, "money_cost": 5000000, 
     "damage": 0, "auto_damage": 0, "depth_unlock": 3, "purchased": False,
     "effect": "max_depth = max(max_depth, 3)", "unlocks": ["q", "w"], "desc": "Unlock Depth 3"},
    
    {"key": "8", "name": "Diamond Drill", "ore_costs": {"iron": 25, "silver": 15}, "money_cost": 10000000, 
     "damage": 100, "auto_damage": 0, "depth_unlock": 0, "purchased": False,
     "effect": "ore_damage += 100", "unlocks": ["e"], "desc": "+100 damage"},
    
    {"key": "9", "name": "Titanium Pickaxe", "ore_costs": {"silver": 20}, "money_cost": 7500000, 
     "damage": 75, "auto_damage": 0, "depth_unlock": 0, "purchased": False,
     "effect": "ore_damage += 75", "unlocks": ["e"], "desc": "+75 damage"},
    
    {"key": "0", "name": "Mining Crew", "ore_costs": {"iron": 30, "silver": 20}, "money_cost": 15000000, 
     "damage": 0, "auto_damage": 30, "depth_unlock": 0, "purchased": False,
     "effect": "auto_mine_damage += 30; auto_miner_count += 5", "unlocks": ["r"], "desc": "+30 auto damage"},
    
    # Tier 4 - Unlock Depth 4
    {"key": "q", "name": "Deep Mining Shaft", "ore_costs": {"gold": 15, "emerald": 10}, "money_cost": 50000000, 
     "damage": 0, "auto_damage": 0, "depth_unlock": 4, "purchased": False,
     "effect": "max_depth = max(max_depth, 4)", "unlocks": ["t", "y"], "desc": "Unlock Depth 4"},
    
    {"key": "w", "name": "Laser Drill", "ore_costs": {"gold": 20, "emerald": 12}, "money_cost": 75000000, 
     "damage": 200, "auto_damage": 0, "depth_unlock": 0, "purchased": False,
     "effect": "ore_damage += 200", "unlocks": ["u"], "desc": "+200 damage"},
    
    {"key": "e", "name": "Mithril Pickaxe", "ore_costs": {"gold": 25, "emerald": 15}, "money_cost": 100000000, 
     "damage": 150, "auto_damage": 0, "depth_unlock": 0, "purchased": False,
     "effect": "ore_damage += 150", "unlocks": ["u"], "desc": "+150 damage"},
    
    {"key": "r", "name": "Mining Operation", "ore_costs": {"gold": 30, "emerald": 20}, "money_cost": 125000000, 
     "damage": 0, "auto_damage": 50, "depth_unlock": 0, "purchased": False,
     "effect": "auto_mine_damage += 50; auto_miner_count += 10", "unlocks": ["i"], "desc": "+50 auto damage"},
    
    # Tier 5 - Unlock Depth 5
    {"key": "t", "name": "Ancient Depths", "ore_costs": {"ruby": 20, "diamond": 15}, "money_cost": 500000000, 
     "damage": 0, "auto_damage": 0, "depth_unlock": 5, "purchased": False,
     "effect": "max_depth = max(max_depth, 5)", "unlocks": ["o", "p"], "desc": "Unlock Depth 5"},
    
    {"key": "y", "name": "Plasma Cutter", "ore_costs": {"ruby": 25, "diamond": 20}, "money_cost": 750000000, 
     "damage": 400, "auto_damage": 0, "depth_unlock": 0, "purchased": False,
     "effect": "ore_damage += 400", "unlocks": ["o"], "desc": "+400 damage"},
    
    {"key": "u", "name": "Quantum Drill", "ore_costs": {"diamond": 30}, "money_cost": 1000000000, 
     "damage": 300, "auto_damage": 0, "depth_unlock": 0, "purchased": False,
     "effect": "ore_damage += 300", "unlocks": ["o"], "desc": "+300 damage"},
    
    {"key": "i", "name": "Industrial Complex", "ore_costs": {"ruby": 40, "diamond": 25}, "money_cost": 2000000000, 
     "damage": 0, "auto_damage": 100, "depth_unlock": 0, "purchased": False,
     "effect": "auto_mine_damage += 100; auto_miner_count += 20", "unlocks": ["p"], "desc": "+100 auto damage"},
    
    # Final upgrades
    {"key": "o", "name": "Nano-Excavator", "ore_costs": {"mythril": 50, "adamantite": 30}, "money_cost": 5000000000, 
     "damage": 1000, "auto_damage": 0, "depth_unlock": 0, "purchased": False,
     "effect": "ore_damage += 1000", "unlocks": [], "desc": "+1000 damage"},
    
    {"key": "p", "name": "Unlock Next World", "ore_costs": {"mythril": 100, "adamantite": 75, "orichalcum": 50}, "money_cost": 25000000000, 
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

def enter_combat(location_name=None):
    global combat_started, player_hp, player_max_hp, enemy_hp, enemy_max_hp, player_heals, player_ability_charges, combat_log
    combat_started = True
    player_max_hp = 100
    player_hp = player_max_hp
    enemy_max_hp = 80
    enemy_hp = enemy_max_hp
    player_heals = 3
    player_ability_charges = 1
    combat_log = [f"A wild foe appears at {location_name or 'Unknown Location'}!"]

def draw_combat_ui():
    # simple ascii characters
    left = [
        "  (\\_/)",
        "  (•_•)",
        " <( : ) ",
        "  /   \\",
        "  /___\\"
    ]
    right = [
        "  /\\_/\\",
        " ( o.o )",
        "  ( : )> ",
        "  /   \\",
        "  /___\\"
    ]
    width = 80
    # header
    print("=== DUNGEON - COMBAT ===\n")
    # draw ascii side-by-side
    gap = width - 20
    for i in range(max(len(left), len(right))):
        l = left[i] if i < len(left) else ""
        r = right[i] if i < len(right) else ""
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
    actions = f"[A] Attack   [H] Heal ({player_heals})   [U] Ability ({player_ability_charges})   [K] Back"
    print(actions.center(width))

def perform_player_action(action):
    global enemy_hp, player_hp, player_heals, combat_log, player_ability_charges, combat_started, world
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
        combat_started = False
        world = 1
        return

    # enemy turn
    edmg = random.randint(5, 14)
    player_hp -= edmg
    combat_log.append(f"Enemy hits you for {edmg} dmg.")
    if player_hp <= 0:
        combat_log.append("You were slain...")
        combat_started = False
        world = 1


def curses_map_view(stdscr):
    """Draw the map using curses and wait for a mouse click on a labeled region.
    Returns the normalized region name (key in click_labels) or None if canceled."""
    curses.curs_set(0)
    stdscr.clear()
    stdscr.keypad(True)
    curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)

    header_lines = ["=== WORLD 2: MAP ===","Click on locations to enter the dungeon.",""]
    # draw header
    for i, line in enumerate(header_lines):
        stdscr.addstr(i, 0, line)

    map_top = len(header_lines)
    # draw map lines
    for i, line in enumerate(map_art):
        try:
            stdscr.addstr(map_top + i, 0, line)
        except Exception:
            # if terminal too small, truncate
            try:
                stdscr.addstr(map_top + i, 0, line[:stdscr.getmaxyx()[1]-1])
            except Exception:
                pass

    # compute zones in display coords using existing helper
    # pass map_top+1 (1-based row index) so calculations align with zone math
    absolute_zones = make_absolute_zones(map_art, map_top + 1)

    # draw debug boxes (optional) - we'll draw short markers at label starts
    if SHOW_ZONE_DEBUG:
        for name, z in absolute_zones.items():
            r = z["row_start"] - 1
            c = z["col_start"] - 1
            try:
                stdscr.addstr(r, c, "[", curses.A_DIM)
                # show short name for debugging
                try:
                    stdscr.addstr(r, c + 1, name[:18], curses.A_DIM)
                except Exception:
                    pass
            except Exception:
                pass

    stdscr.refresh()

    while True:
        ch = stdscr.getch()
        if ch == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bstate = curses.getmouse()
            except Exception:
                continue
            # left click
            if bstate & curses.BUTTON1_CLICKED:
                # find which zone contains (my+1, mx+1)
                matched = None
                for name, z in absolute_zones.items():
                    if z["row_start"] <= my+1 <= z["row_end"] and z["col_start"] <= mx+1 <= z["col_end"]:
                        matched = (name, z)
                        break
                # debug: show click coords and matched zone at bottom
                try:
                    maxy, maxx = stdscr.getmaxyx()
                    dbg = f"Click at {mx},{my} -> {matched[0] if matched else 'NONE'}"
                    stdscr.addstr(maxy-1, 0, dbg[:maxx-1])
                except Exception:
                    pass
                stdscr.refresh()
                if matched:
                    # visually highlight the matched zone briefly
                    name, z = matched
                    # compute 0-based map_art index for zone start
                    start_idx = z["row_start"] - (map_top + 1)
                    z_h = z["row_end"] - z["row_start"] + 1
                    z_w = z["col_end"] - z["col_start"] + 1
                    col0 = z["col_start"] - 1
                    for i in range(z_h):
                        line_idx = start_idx + i
                        y = map_top + line_idx
                        try:
                            stdscr.chgat(y, col0, z_w, curses.A_REVERSE)
                        except Exception:
                            # fallback: overwrite with reversed slice
                            try:
                                stdscr.addstr(y, col0, map_art[line_idx][0:z_w], curses.A_REVERSE)
                            except Exception:
                                pass
                    stdscr.refresh()
                    time.sleep(0.25)
                    # After highlighting, enter curses combat UI directly (stay in curses)
                    did = curses_combat(stdscr, name, absolute_zones, map_top)
                    return (name, bool(did))
        elif ch in (ord('q'), 27):
            return None
        elif ch in (ord('k'), ord('K')):
            return (None, False)

def curses_combat(stdscr, region, absolute_zones=None, map_top=0):
    """Run a simple combat UI inside the existing curses session."""
    curses.curs_set(0)
    stdscr.clear()
    stdscr.keypad(True)
    maxy, maxx = stdscr.getmaxyx()
    enter_combat(location_name=region)

    while True:
        stdscr.erase()
        title = f"DUNGEON: {region.replace('_',' ').title()}"
        stdscr.addstr(0, 0, title)
        # draw ascii
        left = ["  (\\_/)", "  (•_•)", " <( : ) ", "  /   \\", "  /___\\\\"]
        right = ["  /\\_/\\"," ( o.o )","  ( : )> ", "  /   \\", "  /___\\\\"]
        for i in range(5):
            stdscr.addstr(2 + i, 0, left[i])
            try:
                stdscr.addstr(2 + i, maxx - 20, right[i])
            except Exception:
                pass

        # HP bars
        stdscr.addstr(8, 0, f"Player HP: {player_hp}/{player_max_hp} ")
        stdscr.addstr(9, 0, format_bar(player_hp, player_max_hp, min(30, maxx-20)))
        stdscr.addstr(8, maxx - 40, f"Enemy HP: {enemy_hp}/{enemy_max_hp}")
        stdscr.addstr(9, maxx - 40, format_bar(enemy_hp, enemy_max_hp, min(30, maxx-20)))

        # combat log
        stdscr.addstr(11, 0, "-- Combat Log --")
        for i, msg in enumerate(combat_log[-(maxy-18):], start=0):
            if 12 + i < maxy - 4:
                stdscr.addstr(12 + i, 0, msg[:maxx-1])

        # actions
        actions = "[A] Attack   [H] Heal   [U] Ability   [K] Back"
        stdscr.addstr(maxy-2, 0, actions[:maxx-1])

        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (ord('a'), ord('A')):
            perform_player_action('attack')
        elif ch in (ord('h'), ord('H')):
            perform_player_action('heal')
        elif ch in (ord('u'), ord('U')):
            perform_player_action('ability')
        elif ch in (ord('k'), ord('K')):
            # back to map/world 1
            try:
                globals()['world'] = 1
            except Exception:
                pass
            return True
        elif ch in (ord('q'), 27):
            try:
                globals()['world'] = 1
            except Exception:
                pass
            return True
        # check combat end
        if not combat_started:
            # display final messages until keypress
            stdscr.addstr(maxy-3, 0, "Combat ended. Press any key to continue...")
            stdscr.refresh()
            stdscr.getch()
            try:
                globals()['world'] = 1
            except Exception:
                pass
            return True


# --- MAIN LOOP ---
def main():
    global world, money, timea, page, w1upgrades, depth, max_depth, ore_hp, ore_max_hp, ore_damage, auto_mine_damage, current_ore, ore_inventory, auto_miner_count, mining_page_unlocked
    generate_city_layout()
    spawn_new_ore()  # Add this line
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
                    print(f"Money: {money:.2f}\n")
                    timea += 0.1
                    if timea >= 1:
                        money += rate * adminmultiplier * othermultiplier
                        timea = 0.0
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
        # --- WORLD 1 TECHNOLOGY PAGE ---   
           # --- WORLD 1 TECHNOLOGY PAGE ---   
            # --- WORLD 1 TECHNOLOGY PAGE ---   
            if world == 1 and page == 2:
                if not mining_page_unlocked: 
                    print("Mining not unlocked yet.")
                    print("\nPress [R] to return to City")
                else:
                    # Time and auto-mining
                    timea += 0.1
                    if timea >= 1:
                        money += rate * adminmultiplier * othermultiplier
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

                if key:
                    k = key.lower()
                    if k == ' ':  # Mine
                        mine_ore()
                    elif k == 'k':
                        world = 2
                    elif k == 'q': 
                        break
                    elif k == 'r': 
                        page = 0
                    elif k in '12345':
                        # Change depth
                        new_depth = int(k)
                        if new_depth <= max_depth:
                            depth = new_depth
                            spawn_new_ore()  # Spawn new ore at new depth
                    else:
                        for tech in technology:
                            if k == tech["key"]: 
                                buy_technology(tech)
                                break
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
                if research_page_unlocked: print("\nPress [R] to go to Research.")
                if mining_page_unlocked: print("Press [T] to go to Technology.")
                sanity = 20 - w1upgrades
                bar = int((sanity / 20) * length)
                print("\n[" + "#" * bar + " " * (length - bar) + "]\n")

            # --- WORLD 2 MAP VIEW (curses) ---
            if world == 2:
                # open a curses-based full-screen map and wait for click
                # disable raw mouse reporting from the outer code while curses runs
                disable_mouse()
                try:
                    region_res = curses.wrapper(curses_map_view)
                except Exception:
                    region_res = (None, False)
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
                    if did_combat:
                        # curses already ran combat and returned — go back to world 1
                        world = 1
                    else:
                        # enter non-curses dungeon (fallback)
                        world = 3
                        region_name = region.replace("_", " ").upper()
                        print(f"\nYou clicked {region_name}. Entering Dungeon...")
                        time.sleep(0.3)
                else:
                    # canceled or closed map
                    world = 1

            # --- DUNGEON / COMBAT VIEW ---
            if world == 3:
                # initialize combat on first entry
                if not combat_started:
                    enter_combat()
                draw_combat_ui()

            # --- INPUT HANDLING ---
# --- INPUT HANDLING ---
       # --- INPUT HANDLING ---
            if key:
                if key == '\x1b':
                    rest = read_mouse_sequence()
                    if rest and rest.startswith("[<"):
                        try:
                            core = rest[2:-1]
                            b_str, x_str, y_str = core.split(";")
                            b, x, y = int(b_str), int(x_str), int(y_str)
                            
                            # Check if we're on the mining page and clicked on the ore area
                            if world == 1 and page == 2 and mining_page_unlocked:
                                # Ore display is roughly at rows 7-16, columns 5-30 (left column)
                                if 7 <= y <= 16 and 5 <= x <= 30:
                                    mine_ore()  # Mine when clicking on ore visual
                                    
                        except Exception:
                            pass
                else:
                    k = key.lower()
                    if k == 'q': 
                        break
                    elif k == 'k':
                        if world == 1:
                            world = 2
                        elif world == 2:
                            world = 1
                        elif world == 3:
                            world = 1
                    elif k == 'r' and research_page_unlocked and world == 1: 
                        page = 1
                    elif k == 't' and mining_page_unlocked and world == 1: 
                        page = 2
                    elif world == 3:
                        # combat action keys
                        if k == 'a':
                            perform_player_action('attack')
                        elif k == 'h':
                            perform_player_action('heal')
                        elif k == 'u':
                            perform_player_action('ability')
                    elif world == 1 and page == 0:
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
                        else:
                            for tech in technology:
                                if k == tech["key"]: 
                                    buy_technology(tech)
                                    break
            time.sleep(0.1)
    finally:
        disable_mouse()
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

if __name__ == "__main__":
    main()
