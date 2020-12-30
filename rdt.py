from USocket import UnreliableSocket
import threading
import time
import struct
import _thread


def make_check_sum(data: bytes):
    sum: int = 0
    for byte in data:
        sum += byte
    sum = -(sum % 256)
    checksum = sum & 0xFF
    return checksum


MAX_PACK_LEN = 1440


class Packet:
    SYN_bit: int = (1 << 0)
    FIN_bit: int = (1 << 1)
    ACK_bit: int = (1 << 2)

    def __init__(self, syn=0, fin=0, ack=0, seq=0, seqack=0, data: bytes = b""):
        self.syn = syn
        self.fin = fin
        # 标志位
        self.ack = ack
        # 某一方发送的第几个包
        self.seq = seq
        # 标志位有效情况下，ack哪个包
        self.seqack = seqack
        self.len = len(data)
        self.checksum = 0
        self.data = data
        self.checksum = make_check_sum(self.encode(False))

    def decode(self, data):
        headerdata = data[:18]
        self.data = data[18:]
        buffer = struct.unpack('biiih', headerdata)
        block1, self.seq, self.seqack, self.len, self.checksum = buffer
        if int(block1 / self.ACK_bit) > 0:
            self.ack = 1
            block1 = block1 - self.ACK_bit
        if int(block1 / self.FIN_bit) > 0:
            self.fin = 1
            block1 = block1 - self.FIN_bit
        if int(block1 / self.SYN_bit) > 0:
            self.syn = 1
            block1 = block1 - self.ACK_bit
        return

    def encode(self, have_checksum=True):
        block1 = self.SYN_bit * self.syn + self.FIN_bit * self.fin + self.ACK_bit * self.ack
        checksum = 0
        if have_checksum:
            checksum = self.checksum
        data: bytes = struct.pack('biiih', block1, self.seq, self.seqack, self.len, checksum)
        return data + self.data

    def check_checksum(self):
        checksum = make_check_sum(self.encode(False))
        return checksum == self.checksum

    def __str__(self):
        return "packet: syn:{}-fin:{}-ack:{}-seq:{}-seqack:{}-checksum:{}".format(self.syn == 1, self.fin == 1,
                                                                                  self.ack == 1, self.seq, self.seqack,
                                                                                  self.check_checksum())


class RDTSocket(UnreliableSocket):
    """
    The functions with which you are to build your RDT.
    -   recvfrom(bufsize)->bytes, addr
    -   sendto(bytes, address)
    -   bind(address)

    You can set the mode of the socket.
    -   settimeout(timeout)
    -   setblocking(flag)
    By default, a socket is created in the blocking mode. 
    https://docs.python.org/3/library/socket.html#socket-timeouts

    """

    def __init__(self, rate=None, debug=False):
        super().__init__(rate=rate)
        self._rate = rate
        self._send_to = None
        self._recv_from = None
        self.debug = debug
        #############################################################################
        # TODO: ADD YOUR NECESSARY ATTRIBUTES HERE
        #############################################################################
        self.buffer = 2048
        # 已经发送到的seq
        self.seq = 0
        self.sender = False
        # 已经成功接受到的对方的seq
        self.ack = 0
        # 发端超时时间
        self.timeoutTime = 1
        # 动态变化的window_size
        self.windowSize = 10

        # by ljc
        self.rtt = 0
        self.alpha = 0.125
        self.dev = 0
        self.beta = 0.25
        self.ssthresh = 15
        self.flag = False
        self.data = None
        self.address = None

        # by cjy
        self.thread_terminate = True
        #############################################################################
        #                             END OF YOUR CODE                              #
        #############################################################################

    def accept(self):  # ->(RDTSocket, (str, int)):
        """
        Accept a connection. The socket must be bound to an address and listening for
        connections. The return value is a pair (conn, address) where conn is a new
        socket object usable to send and receive data on the connection, and address
        is the address bound to the socket on the other end of the connection.

        This function should be blocking.
        """
        #############################################################################
        # TODO: YOUR CODE HERE                                                      #
        #############################################################################
        run = True
        self.sender = False
        while run:
            data, address = self.recvfrom(self.buffer)
            receive = Packet()
            receive.decode(data)
            print("receive packet from client:")
            print(receive)

            if not receive.check_checksum() or receive.syn != 1:
                continue
            self._recv_from = address
            self._send_to = address
            # 三次握手 发送synack
            self.ack = receive.seq
            reply = Packet(seqack=self.ack, ack=1, syn=1, seq=self.seq)
            self.sendto(reply.encode(), address)
            print("send reply to client: ", address)
            print(reply)
            # 接受回握
            while True:
                data, add = self.recvfrom(self.buffer)
                if add != address:
                    print("receive from wrong address")
                    continue
                packet = Packet()
                packet.decode(data)
                if (not packet.check_checksum()) or packet.seqack != self.seq or packet.ack != 1:
                    print("receive wrong ack")
                    print(packet, "resend reply")
                    self.sendto(reply.encode(), address)
                    time.sleep(1)
                    continue
                # 正确 结束
                self.seq += 1
                print("receive ack success,accept connection success")
                print(packet)
                self.ack = packet.seq
                success = Packet(seqack=self.ack, ack=1, seq=self.seq)
                self.sendto(success.encode(), address)
                run = False
                break
        # 这里是不是不返回self当作socket比较好
        #############################################################################
        #                             END OF YOUR CODE                              #
        #############################################################################
        return self, address

    def connect(self, address: (str, int)):
        """
        Connect to a remote socket at address.
        Corresponds to the process of establishing a connection on the client side.
        """
        #############################################################################
        # TODO: YOUR CODE HERE                                                      #
        #############################################################################
        # raise NotImplementedError()
        self.sender = True
        self._send_to = address
        self._recv_from = address
        requestpack = Packet(syn=1, seq=self.seq)
        request = requestpack.encode()
        flag = True
        while flag:
            # 发第一个信
            self.sendto(request, address)
            print("send first packet to ", address)
            print(requestpack)
            sendTime = time.time()
            while time.time() - sendTime < self.timeoutTime:
                # 收第一个信的ack
                data, add = self.recvfrom(self.buffer)
                if add != address:
                    print("receive first ack from wrong address")
                    continue
                packet = Packet()
                packet.decode(data)
                if (not packet.check_checksum) or packet.seqack != self.seq:
                    print("receive first ack but its wrong.self")
                    print(packet)
                    continue
                # 成功接受 进入状态3
                flag = False
                self.ack = packet.seq
                print("receive first ack success,to next state")
                print(packet)
                break
        # 第三个包的操作
        self.seq += 1
        packet = Packet(seqack=self.ack, seq=self.seq, ack=1)
        self.sendto(packet.encode(), address)
        print("send the third handshake to server")
        print(packet)
        # 发一个包，处理对面的重复ack
        for i in range(5):
            data, add = self.recvfrom(self.buffer)
            if address != add:
                print("recv from wrong address,continue")
                continue
            rcv = Packet()
            rcv.decode(data)
            print("receive packet from server")
            print(rcv)
            if not rcv.check_checksum():
                continue
            # 对面重发了ack,说明packet丢包
            if rcv.ack == self.seq:
                self.ack += 1
                print("connect success,finish")
                break
            else:
                print("wrong ack num,resend third handshake")
                self.sendto(packet, address)
        #############################################################################
        #                             END OF YOUR CODE                              #
        #############################################################################

    def recv(self, bufsize: int) -> bytes:
        """
        Receive data from the socket.
        The return value is a bytes object representing the data received.
        The maximum amount of data to be received at once is specified by bufsize.

        Note that ONLY data send by the peer should be accepted.
        In other words, if someone else sends data to you from another address,
        it MUST NOT affect the data returned by this function.
        """
        data = b""
        assert self._recv_from, "Connection not established yet. Use recvfrom instead."
        #############################################################################
        # TODO: YOUR CODE HERE                                                      #
        #############################################################################
        # 结束判断是有fin的packet
        # 改为收到多个包发一个ack
        # 收的时候只改自己的ack
        # recvfrom是阻塞式接受函数
        # count = 0
        print("------------------start receiving----------------------")
        print("recieve from :", self._recv_from)
        print("self seq= ", self.seq, " self ack= ", self.ack)

        packcount = 0

        while True:
            # 这是一个阻塞式接收
            packdata, address = self.recvfrom(bufsize)
            if address != self._recv_from:
                print("receive from a wrong address !")
                continue
            # 接收到了一个包，将其decode
            recvPack = Packet()
            recvPack.decode(packdata)
            # print("recv packet ")
            # biterror,顺序错的包 发上一个ack
            if not recvPack.check_checksum or recvPack.seq != self.ack + 1:
                # count = 0
                ackPack = Packet(seqack=self.ack, ack=1)
                if self.debug:
                    print("packet wrong ", recvPack)
                    print("send dumplicate ack", ackPack)

                self.sendto(ackPack.encode(), self._recv_from)
                continue

            print("receive: ", recvPack)

            # ack不用超时重发
            # if self.debug:
            #     print("packet right ", recvPack)
            #     print("ack & seq change,ack= ", self.ack, " seq= ", self.seq)

            self.ack = recvPack.seq
            data += recvPack.data
            packcount += 1

            if recvPack.fin != 1:
                ackPack = Packet(seqack=self.ack, fin=recvPack.fin, ack=1)
                self.sendto(ackPack.encode(), self._recv_from)
                print("send ack pack", ackPack)

            if recvPack.fin == 1:
                print("finish receiving")
                ackPack = Packet(seqack=self.ack, fin=recvPack.fin, ack=1)
                self.sendto(ackPack.encode(), self._recv_from)
                print("send finish ack", ackPack)
                break

        # time.sleep(1)
        # by cjy
        self.clear_out()
        time.sleep(0.5)
        #############################################################################
        #                             END OF YOUR CODE                              #
        #############################################################################
        return data

    def send(self, bytes: bytes):
        """
        Send data to the socket.
        The socket must be connected to a remote socket, i.e. self._send_to must not be none.
        """
        assert self._send_to, "Connection not established yet. Use sendto instead."
        #############################################################################
        # TODO: YOUR CODE HERE                                                      #
        #############################################################################
        # 根据数据长度计算出要发多少个包
        length = len(bytes)
        print(length)
        packetnum = int(length / MAX_PACK_LEN) + 1
        top = 0
        lastack = -1
        lastack_count = 0
        print("------------------start sending----------------------")
        print("self seq= ", self.seq, " self ack= ", self.ack)
        print("pack to send: ", packetnum, " send to ", self._send_to)
        # 处理了bit erro 丢包
        # 还没加入收到fin不再传的部分
        # 要加入seq模一个数的操作,保证位数
        # 发的时候只改自己的seq
        window = [Packet()] * packetnum
        # 每个循环等一个ack，根据ack来发包
        # top是已经ack过的最高的
        # send是已经发送过的最高的
        windowmax = 0
        # 相应事件，子线程
        # eve = None
        # rcv_thread = None
        # 先把整个windows填满
        localseq = self.seq + 1
        while windowmax < packetnum:
            if windowmax != packetnum - 1:
                packet = Packet(seq=localseq, seqack=self.ack,
                                data=bytes[windowmax * MAX_PACK_LEN:(windowmax + 1) * MAX_PACK_LEN])
                window[windowmax] = packet
                localseq += 1
            else:
                packet = Packet(fin=1, seq=localseq, seqack=self.ack, data=bytes[(packetnum - 1) * MAX_PACK_LEN:])
                localseq += 1
                window[windowmax] = packet
            windowmax += 1
            # if self.debug:
            #     print("window is full, windowmax:", windowmax, " top:", top)
        windowmax = 0
        while top < packetnum:

            # 从现在开始计时，当成是发送第一个包的时间
            sendTime = time.time()
            # 发所有上一个ack之后的包
            for p in window[windowmax:top + self.windowSize]:
                self.sendto(p.encode(), self._send_to)
                # time.sleep(0.1)
                print(p)
            windowmax = top + self.windowSize
            self.parent(self.timeoutTime)

            while True:
                nowTime = time.time()
                diffTime = nowTime - sendTime
                if diffTime > self.timeoutTime:
                    self.ssthresh = self.windowSize / 2
                    self.windowSize = 1
                    windowmax = top
                    break

                if (self.flag == True):
                    self.flag = False
                    data = self.data
                    address = self.address
                    # 地址不对，回去重新收
                    if address != self._send_to:
                        print("recv ack form wrong address")
                        continue
                    recvPack = Packet()
                    recvPack.decode(data)
                    if recvPack.check_checksum and recvPack.ack == 1:
                        if recvPack.seqack < self.seq:
                            print("wrong ack with ack too small or already acked:", recvPack)
                            continue
                        if recvPack.seqack == lastack:

                            if lastack_count <3:
                                 lastack_count +=1
                            else:
                                 windowmax = top
                                 lastack_count = 0
                                 break

                        if recvPack.seqack != lastack:
                            lastack = recvPack.seqack
                            lastack_count = 0

                        print("ack accept ", recvPack)

                        if self.windowSize < self.ssthresh:
                            self.windowSize = self.windowSize * 2
                        else:
                            self.windowSize = self.windowSize + 1


                        top += recvPack.seqack - self.seq
                        self.seq = recvPack.seqack

                        if recvPack.fin == 1:
                            # cjy
                            self.clear_out()
                            time.sleep(1)
                            return
                        break
        time.sleep(0.5)

    def clear_out(self):
        self.seq = 1
        self.ack = 1
        self.windowSize = 10
        self.buffer = 2048
        # 已经发送到的seq
        # 已经成功接受到的对方的seq
        self.timeoutTime = 5
        self.windowSize = 10
        # by ljc
        self.rtt = 0
        self.alpha = 0.125
        self.dev = 0
        self.beta = 0.25
        self.ssthresh = 15
        self.flag = False
        self.data = None
        self.address = None
        # by cjy
        self.thread_terminate = True

    def close(self):
        """
        Finish the connection and release resources. For simplicity, assume that
        after a socket is closed, neither futher sends nor receives are allowed.
        """
        #############################################################################
        # TODO: YOUR CODE HERE                                                      #
        #############################################################################
        packet = Packet(fin=1, seqack=self.ack, seq=self.seq + 1)
        self.sendto(packet.encode(), self._send_to)
        self._send_to = None

        #############################################################################
        #                             END OF YOUR CODE                              #
        #############################################################################
        super().close()

    def set_send_to(self, send_to):
        self._send_to = send_to

    def set_recv_from(self, recv_from):
        self._recv_from = recv_from

    def parent(self, t):
        self.flag = False
        son = _thread.start_new_thread(self.test, ())
        start_time = time.time()
        # print("test")
        while time.time() - start_time < t:
            if self.flag == True:
                # print("get data!")
                return

    def test(self):
        self.data, self.address = self.recvfrom(self.buffer)
        self.flag = True


"""
You can define additional functions and classes to do thing such as packing/unpacking packets, or threading.

"""


class MyTread(threading.Thread):
    def __init__(self, event, rdt, buffer):
        super().__init__()
        self.event = event
        self.rdt = rdt
        self.buffer = buffer

    def run(self):
        self.data, self.address = self.rdt.recvfrom(self.buffer)
        # 接收完成之后就把标志位设置为True
        self.event.set()

    def get_result(self):
        return (self.data, self.address)


