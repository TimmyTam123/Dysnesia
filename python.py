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
adminmultiplier = 1.0
othermultiplier = 1.0

# --- UPGRADE DATA ---
upgrades = [
    {"key": "a", "name": "Upg1", "rate_inc": 1, "base_cost": 10, "cost": 10,
     "multiplier": 1.15, "count": 0, "max": 100},
]

# --- WORLD 1 DATA ---
w1upgrades = 0
max_w1upgrades = 10
length = 40


def clear():
    os.system("clear")


def get_key():
    dr, _, _ = select.select([sys.stdin], [], [], 0)
    if dr:
        return sys.stdin.read(1)
    return None


# --- BUY UPGRADE FUNCTION (ADDED) ---
def buy_upgrade(upg):
    global money, rate

    # Maxed
    if upg["count"] >= upg["max"]:
        return

    # Not enough money
    if money < upg["cost"]:
        return

    # Buy it
    money -= upg["cost"]
    rate += upg["rate_inc"]
    upg["count"] += 1

    # Update cost
    if upg["count"] < upg["max"]:
        upg["cost"] = int(upg["cost"] * upg["multiplier"])


def main():
    global world, timea, money

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

                line1 = "Money: {money:.2f}"
                print(line1.format(money=money))

                # --- UPGRADE DISPLAY ---
                visible = False
                for upg in upgrades:
                    if money >= upg["cost"] * 0.1:
                        visible = True
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

                if not visible:
                    print("(No upgrades available yet...)")

                # BAR
                sanity = max_w1upgrades - w1upgrades
                bar = int((sanity / max_w1upgrades) * length)
                empty = length - bar
                print("[" + "#" * bar + " " * empty + "]")
                print()

            # --- WORLD 2 LOGIC ---
            elif world == 2:
                print("=== WORLD 2 ===")
                print("Nothing happens here yet.")

            # --- INPUT ---
            if key:
                k = key.lower()

                # switching worlds
                if k == 'g':
                    world = 2 if world == 1 else 1

                # quit
                elif k == 'q':
                    break

                # BUYING UPGRADES (ADDED)
                if world == 1:
                    for upg in upgrades:
                        if k == upg["key"]:
                            buy_upgrade(upg)
                            break

            time.sleep(0.1)

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        clear()
        print("Exited cleanly.")


if __name__ == "__main__":
    main()
