"""SSH tunnel: localhost:3307 -> production MySQL. Run as background process."""
import paramiko, socket, threading, time, os, sys

JUMP = "123.57.0.174"
PROD = "190.92.220.4"
KEY = os.path.expanduser("~/.ssh/id_rsa")
PASS = "openlab@123"
MYSQL_IP = "172.27.0.4"

def run():
    while True:
        try:
            key = paramiko.RSAKey.from_private_key_file(KEY)
            jump = paramiko.SSHClient(); jump.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            jump.connect(JUMP, username="root", pkey=key, timeout=30)
            jump.get_transport().set_keepalive(30)
            c = jump.get_transport().open_channel("direct-tcpip", (PROD, 22), ("", 0))
            prod = paramiko.SSHClient(); prod.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            prod.connect(PROD, username="root", password=PASS, sock=c, timeout=30)
            prod.get_transport().set_keepalive(30)

            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("127.0.0.1", 3307))
            server.listen(5)
            server.settimeout(1)
            print(f"[tunnel] localhost:3307 -> {PROD}:3306", flush=True)

            while True:
                try:
                    client, addr = server.accept()
                    chan = prod.get_transport().open_channel("direct-tcpip", (MYSQL_IP, 3306), addr)
                    def fwd(src, dst):
                        try:
                            while True:
                                data = src.recv(4096)
                                if not data: break
                                dst.sendall(data)
                        except: pass
                    t1 = threading.Thread(target=fwd, args=(client, chan), daemon=True)
                    t2 = threading.Thread(target=fwd, args=(chan, client), daemon=True)
                    t1.start(); t2.start()
                except socket.timeout:
                    continue
                except Exception as e:
                    print(f"[tunnel] error: {e}", flush=True)
                    break
            server.close(); prod.close(); jump.close()
        except Exception as e:
            print(f"[tunnel] restart in 5s: {e}", flush=True)
            time.sleep(5)

if __name__ == "__main__":
    run()
