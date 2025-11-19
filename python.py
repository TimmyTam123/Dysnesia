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
     "base_cost": 1000, "cost": 1000, "multiplier": 1.15, "count": 0, "max": 50, "seen": False},
    {"key": "f", "name": "Upgrade Hardware", "rate_inc": 10000,
     "base_cost": 10000, "cost": 10000, "multiplier": 1.15, "count": 0, "max": 30, "seen": False},
    {"key": "g", "name": "Unlock Research", "rate_inc": 0,
     "base_cost": 1000000, "cost": 1000000, "multiplier": 0, "count": 0, "seen": False, "max": 1,},
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
        {"name": "house",      "roof": "▲", "body": "▓"},
        {"name": "factory",    "roof": "■", "body": "▒"},
        {"name": "tower",      "roof": "▲", "body": "▌"},
        {"name": "skyscraper", "roof": "■", "body": "█"},
        {"name": "dome",       "roof": "◯", "body": "░"},
        {"name": "antenna",    "roof": "│", "body": "┃"},
        {"name": "villa",      "roof": "♢", "body": "▒"},
        {"name": "castle",     "roof": "♜", "body": "█"},
        {"name": "tent",       "roof": "△", "body": "┼"},
        {"name": "hut",        "roof": "⌂", "body": "▖"},
        {"name": "spire",      "roof": "†", "body": "▚"},
        {"name": "mall",       "roof": "▀", "body": "▤"},
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


def update_building_heights(upgrades):
    """Grow building heights toward the middle based on total upgrades, preserving random offsets."""
    max_height = 15
    for b in city_buildings:
        pyramid_height = int(upgrades / 2 / (b["mid_offset"] + 1)) + 1
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


def draw_research_tree():
    """Render a 10-node boxed research tree with || connectors and completion marks."""
    # Convert your research list into 10 nodes
    # If fewer than 10 exist, pad them
    nodes = []
    for i in range(10):
        if i < len(research):
            r = research[i]
            mark = "X" if r["purchased"] else " "
            nodes.append(f"[R{i+1}:{mark}]")
        else:
            nodes.append(f"[R{i+1}: ]")

    # Build tree layout (square aesthetic, double vertical lines)
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
    global world, timea, money, page, w1upgrades

    generate_city_layout()  # generate static layout once

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    tty.setcbreak(fd)

    try:
        while True:
            key = get_key()
            clear()

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
                        if money >= upg.get("cost",0) * 0.1:
                            upg["seen"] = True
                        if upg.get("seen", False):
                            any_seen = True
                            status = f"+{upg.get('rate_inc',0)}/sec | Cost: ${upg.get('cost', 0)}" \
                                if upg.get("count", 0) < upg.get("max",100) else "MAXED"
                            print(f"[{upg.get('key', '?').upper()}] {upg.get('name', 'Unknown')} "
                                f"({upg.get('count', 0)}/{upg.get('max',100)}) {status}")
                    if not any_seen:
                        print("(No upgrades available yet...)")

                elif page == 1:
                    if not research_page_unlocked:
                        print("Research not unlocked yet.")
                    else:
                        draw_research_tree()
                        print("Research Keys:")
                        for res in research:
                            status = "— COMPLETED" if res["purchased"] else f"| Cost: ${res['cost']}"
                            print(f"[{res['key']}] Research {res['key']} {status}")


                if research_page_unlocked:
                    print("\nPress [R] to switch pages.")

                # Upgrade bar at the bottom
                sanity = 20 - w1upgrades
                bar = int((sanity / 20) * length)
                empty = length - bar
                print("\n[" + "#" * bar + " " * empty + "]\n")

            if key:
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
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        clear()
        print("Exited cleanly.")


if __name__ == "__main__":
    main()