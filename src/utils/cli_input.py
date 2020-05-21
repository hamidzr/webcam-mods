import threading


# we treat this as a shared bus for reading incoming input for simplicity
inp = [""]  # need to pass by reference


def read_input():
    global inp
    while True:
        inp[0] = input()


inputThread = threading.Thread(target=read_input, daemon=True)
inputThread.start()
