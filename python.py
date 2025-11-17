import os
import sys
import termios
import time
import select
import tty

world = 1
timea = 0.0

money = 0
rate = 1
adminmultiplier = 10.0
othermultiplier = 1.0

page = 0  # 0 = upgrades, 1 = research

# --- RESEARCH PAGE FLAG ---
research_page_unlocked = False

# --- UPGRADE DATA ---
upgrades = [
    {"key": "a", "name": "Hire Worker", "rate_inc": 1, "base_cost": 10,
     "cost": 10, "multiplier": 1.15, "count": 0, "max": 100, "seen": False},
    {"key": "s", "name": "Hire Manager", "rate_inc": 10, "base_cost": 100,
     "cost": 100, "multiplier": 1.15, "count": 0, "max": 100, "seen": False},
    {"key": "d", "name": "Hire Senior Manager", "rate_inc": 100,
     "base_cost": 1000, "cost": 1000, "multiplier": 1.15, "count": 0,
     "max": 100, "seen": False},
    {"key": "f", "name": "Upgrade Hardware", "rate_inc": 10000,
     "base_cost": 10000, "cost": 10000, "multiplier": 1.15, "count": 0,
     "max": 100, "seen": False},
    {"key": "g", "name": "Unlock Research", "rate_inc": 0,
     "base_cost": 1000000, "cost": 1000000, "multiplier": 0, "count": 0,
     "max": 1, "seen": False},
]

# --- RESEARCH PAGE DATA ---
research = [
    {"key": "1", "name": "Boost Admin Systems",
     "cost": 500000, "purchased": False,
     "effect": "adminmultiplier *= 1.5"},
    {"key": "2", "name": "Machine Learning Boost",
     "cost": 2000000, "purchased": False,
     "effect": "othermultiplier *= 2"},
]

# --- WORLD 1 DATA ---
w1upgrades = 0
max_w1upgrades = 20
length = 40


def clear():
    os.system("clear")


def get_key():
    dr, _, _ = select.select([sys.stdin], [], [], 0)
    if dr:
        return sys.stdin.read(1)
    return None


# --- BUY UPGRADE FUNCTION ---
def buy_upgrade(upg):
    global money, rate, w1upgrades, research_page_unlocked

    if upg["count"] >= upg["max"]:
        return

    if money < upg["cost"]:
        return

    money -= upg["cost"]
    rate += upg["rate_inc"]
    upg["count"] += 1
    w1upgrades += 1

    if upg["name"] == "Unlock Research":
        research_page_unlocked = True

    if upg["count"] < upg["max"]:
        upg["cost"] = int(upg["cost"] * upg["multiplier"])


# --- BUY RESEARCH FUNCTION ---
def buy_research(res):
    global money, adminmultiplier, othermultiplier

    if res["purchased"]:
        return

    if money < res["cost"]:
        return

    money -= res["cost"]
    res["purchased"] = True
    exec(res["effect"], globals())


def main():
    global world, timea, money, page

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    tty.setcbreak(fd)

    try:
        while True:
            key = get_key()
            clear()

            # --- WORLD 1 LOGIC ---
            if world == 1:
                global w1upgrades, max_w1upgrades, length
                timea += 0.1
                if timea >= 1:
                    money += rate * adminmultiplier * othermultiplier
                    timea = 0.0

                print(f"Money: {money:.2f}")
                if page == 0:
                    print("=== UPGRADES ===")
                elif page == 1:
                    print("=== RESEARCH ===")
                print()

                # ======================
                # PAGE 0 — UPGRADES
                # ======================
                if page == 0:
                    any_seen = False
                    for upg in upgrades:
                        if money >= upg["cost"] * 0.1:
                            upg["seen"] = True
                        if upg["seen"]:
                            any_seen = True
                            if upg["count"] < upg["max"]:
                                print(
                                    f"[{upg['key'].upper()}] {upg['name']} "
                                    f"({upg['count']}/{upg['max']}) "
                                    f"+{upg['rate_inc']}/sec | Cost: ${upg['cost']}"
                                )
                            else:
                                print(
                                    f"[{upg['key'].upper()}] {upg['name']} "
                                    f"({upg['count']}/{upg['max']}) MAXED"
                                )

                    if not any_seen:
                        print("(No upgrades available yet...)")

                # ======================
                # PAGE 1 — RESEARCH
                # ======================
                elif page == 1:
                    if not research_page_unlocked:
                        print("Research not unlocked yet.")
                    else:
                        for res in research:
                            if res["purchased"]:
                                print(f"[{res['key']}] {res['name']} — COMPLETED")
                            else:
                                print(f"[{res['key']}] {res['name']} | Cost: ${res['cost']}")

                if research_page_unlocked:
                    print("\nPress [R] to switch pages.")
                # BAR
                sanity = max_w1upgrades - w1upgrades
                bar = int((sanity / max_w1upgrades) * length)
                empty = length - bar
                print("\n[" + "#" * bar + " " * empty + "]\n")

            # --- WORLD 2 LOGIC ---
            elif world == 2:
                print("=== WORLD 2 ===")
                print("Nothing happens here yet.")

            # --- INPUT ---  <--- Moved out so it's executed regardless of world
            if key:
                k = key.lower()

                # Switch worlds
                if k == 'k':
                    world = 2 if world == 1 else 1

                # Quit
                elif k == 'q':
                    break

                # Page switching (only if research is unlocked and we're in world 1)
                elif k == 'r' and world == 1:
                    if research_page_unlocked:
                        page = (page + 1) % 2
                    else:
                        page = 0
                    continue

                # WORLD 1 INPUT
                if world == 1:
                    if page == 0:
                        for upg in upgrades:
                            if k == upg["key"]:
                                buy_upgrade(upg)
                                break
                    elif page == 1 and research_page_unlocked:
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
