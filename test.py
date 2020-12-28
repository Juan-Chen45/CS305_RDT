import _thread
import time


def test():
    global flag
    input("请输入: ")
    print("test terminated!")
    flag = False


def parent(t):
    global flag
    flag = True
    son = _thread.start_new_thread(test, ())
    start_time = time.time()
    while time.time() - start_time < t:
        if flag == False:
            print("parent terminated!")
            break
        else:
            time.sleep(0.2)



t = float(input("需要运行几秒？ "))
parent(t)