import threading

# we treat this as a shared bus for reading incoming input for simplicity
inp = [""]  # need to pass by reference


def read_input():
    while True:
        try:
            inp[0] = input()
        except EOFError:
            return


inputThread = threading.Thread(target=read_input, daemon=True)
inputThread.start()
