import curses
import time
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

# --- UPGRADE DATA ---
upgrades = [
    {"key": "a", "name": "Hire Worker", "rate_inc": 1, "base_cost": 10, "cost": 10, "multiplier": 1.15, "count": 0, "max": 100, "seen": False},
    {"key": "s", "name": "Hire Manager", "rate_inc": 10, "base_cost": 100, "cost": 100, "multiplier": 1.15, "count": 0, "max": 75, "seen": False},
    {"key": "d", "name": "Hire Senior Manager", "rate_inc": 100, "base_cost": 1000, "cost": 1000, "multiplier": 1.15, "count": 0, "max": 50, "seen": False},
    {"key": "f", "name": "Upgrade Hardware", "rate_inc": 10000, "base_cost": 10000, "cost": 10000, "multiplier": 1.15, "count": 0, "max": 30, "seen": False},
    {"key": "g", "name": "Unlock Research", "rate_inc": 0, "base_cost": 1000000, "cost": 1000000, "multiplier": 0, "count": 0, "seen": False, "max": 1}
]

# --- RESEARCH DATA ---
research = [
    {"key": "1", "name": "Boost Admin Systems", "cost": 500000, "purchased": False, "effect": lambda: boost_admin()},
    {"key": "2", "name": "Machine Learning Boost", "cost": 2000000, "purchased": False, "effect": lambda: boost_ml()}
]

# --- GLOBALS ---
city_buildings = []

# --- EFFECT FUNCTIONS ---
def boost_admin():
    global adminmultiplier
    adminmultiplier *= 1.5

def boost_ml():
    global othermultiplier
    othermultiplier *= 2

# --- CITY FUNCTIONS ---
def generate_city_layout():
    global city_buildings
    num_buildings = 25
    types = [
        {"roof": "▲", "body": "▓"},
        {"roof": "■", "body": "▒"},
        {"roof": "▲", "body": "▌"},
        {"roof": "■", "body": "█"},
        {"roof": "◯", "body": "░"},
        {"roof": "│", "body": "┃"},
        {"roof": "♢", "body": "▒"},
        {"roof": "♜", "body": "█"},
        {"roof": "△", "body": "┼"},
        {"roof": "⌂", "body": "♦"},
        {"roof": "†", "body": "▚"},
        {"roof": "▀", "body": "▤"}
    ]
    mid = num_buildings // 2
    city_buildings.clear()
    for i in range(num_buildings):
        width = 1 + (mid - abs(i - mid)) // 2
        b_type = random.choice(types)
        offset = random.randint(0, 2)
        city_buildings.append({
            "width": width,
            "type": b_type,
            "height": 1,
            "pos": i,
            "mid_offset": abs(i - mid),
            "rand_offset": offset
        })

def update_building_heights(upgrades_count):
    max_height = 15
    for b in city_buildings:
        pyramid_height = int(upgrades_count / 2 / (b["mid_offset"] + 1)) + 1
        b["height"] = min(max_height, pyramid_height + b["rand_offset"])

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
    global money
    if res["purchased"]: return
    if money < res["cost"]: return
    money -= res["cost"]
    res["purchased"] = True
    res["effect"]()

# --- DRAW FUNCTIONS ---
def draw_city(stdscr, start_y=10):
    for idx, b in enumerate(city_buildings):
        x = idx * 3 + 2
        for y in range(b["height"]):
            char = b["type"]["roof"] if y == b["height"]-1 else b["type"]["body"]
            try:
                stdscr.addstr(start_y - y, x, char)
            except:
                pass  # ignore drawing errors at screen edges

def draw_ui(stdscr):
    stdscr.addstr(0, 0, f"Money: ${money:.2f}")
    y_offset = 2
    for upg in upgrades:
        if upg["seen"] or money >= upg["cost"] * 0.1:
            upg["seen"] = True
            status = f"+{upg['rate_inc']}/sec | Cost: ${upg['cost']}" if upg["count"] < upg['max'] else "MAXED"
            stdscr.addstr(y_offset, 0, f"[{upg['key'].upper()}] {upg['name']} ({upg['count']}/{upg['max']}) {status}")
            y_offset += 1
    sanity = 20 - w1upgrades
    bar_length = int((sanity / 20) * length)
    bar_str = "#" * bar_length + " " * (length - bar_length)
    stdscr.addstr(y_offset + 1, 0, f"[{bar_str}]")

# --- MAIN LOOP ---
def main(stdscr):
    global money, timea
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(100)  # refresh every 100ms

    generate_city_layout()

    while True:
        stdscr.clear()
        # passive money
        timea += 0.1
        if timea >= 1:
            money += rate * adminmultiplier * othermultiplier
            timea = 0.0

        update_building_heights(w1upgrades)
        draw_city(stdscr)
        draw_ui(stdscr)
        stdscr.refresh()

        try:
            key = stdscr.getkey()
        except:
            key = None

        if key:
            k = key.lower()
            if k == 'q':
                break
            elif k == 'r' and research_page_unlocked:
                pass  # toggle research page if implemented
            else:
                for upg in upgrades:
                    if k == upg['key']:
                        buy_upgrade(upg)
                        break
                for res in research:
                    if k == res['key']:
                        buy_research(res)
                        break
        time.sleep(0.05)

if __name__ == "__main__":
    curses.wrapper(main)
