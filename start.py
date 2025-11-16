import os
import sys
import time
import termios
import tty
import select

money = 0
rate = 1
running = True
page = 0
pmultiplier = 1.0
adminmultiplier = 5000
pp = 0
prestige = False

# Define upgrades in a structured way
upgrades = [
    {"key": "a", "name": "Upg1", "rate_inc": 1, "base_cost": 10, "cost": 10, "multiplier": 1.15, "count": 0, "max": 100},
]


def clear():
    os.system("clear")


def get_key():

    dr, _, _ = select.select([sys.stdin], [], [], 0)
    if dr:
        return sys.stdin.read(1)
    return None


def buy_upgrade(upgrade):
    global money, rate

    if upgrade["count"] >= upgrade["max"]:
        print(f"Max level reached for {upgrade['name']}!")
        time.sleep(0.3)
        return

    if money >= upgrade["cost"]:
        money -= upgrade["cost"]
        rate += upgrade["rate_inc"]
        upgrade["count"] += 1
        if upgrade["count"] >= upgrade["max"]:
            pass
        else:
            upgrade["cost"] = int(upgrade["cost"] * upgrade["multiplier"])
    else:
        print(f"Not enough money for {upgrade['name']}! Need ${upgrade['cost']}.")
        time.sleep(0.3)


def main():
    global money, rate, running, page, pmultiplier, adminmultiplier, prestige, pp

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    tty.setcbreak(fd)

    try:
        last_income = time.time()

        while running:
            now = time.time()

            # Money accumulation
            if now - last_income >= 1:
                pmultiplier = 1.0 + (pp * 0.1)
                money += int(rate * pmultiplier * adminmultiplier)
                last_income = now
                clear()
                if prestige == True:
                    print(f"Money: ${money:,}  |  Rate: ${rate * pmultiplier * adminmultiplier:,}/sec | Prestige Points: {pp}")
                else:
                    print(f"Money: ${money:,}  |  Rate: ${rate * pmultiplier * adminmultiplier:,}/sec")
                if page == 0:
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
                                    f"({upg['count']}/{upg['max']}) "
                                    f"MAXED"
                                )
                    if not visible:
                        print("(No upgrades available yet...)")
                    if money >= 1000000:
                        print("[N] Prestige")
                if page == 1:
                    if money >= 1000000:
                        print ("Prestige?")
                        print ("Are you sure you want to prestige?")
                        print ("You will lose all your money and upgrades,")
                        print (f"You will also gain {int(money/1000000)} prestige points.")
                        print ("This can be done multiple times for increasing multipliers.")
                        print ("Press space to prestige")
                    print("[B] Back")
                print("[Q] Quit")
            key = get_key()
            if key:
                key = key.lower()
                if key == "q":
                    running = False
                elif key == "n":
                    if money >= 1000000 or prestige:
                        page = (1)
                    else:
                        print ("Too broke for this feature")
                elif key == "b":
                    page = (0)
                elif key == " ":
                    if page == 1 and money >= 1000000:
                        pp += int(money / 1000000)
                        money = 0
                        rate = 1

                        for upg in upgrades:
                            upg["count"] = 0
                            upg["cost"] = upg["base_cost"]
                        page = 0
                        prestige = True
                else:
                    if page == 0:
                        for upg in upgrades:
                            if key == upg["key"]:
                                buy_upgrade(upg)
                                break
            time.sleep(0.05)

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        print("\nExiting...")


if __name__ == "__main__":
    main()
