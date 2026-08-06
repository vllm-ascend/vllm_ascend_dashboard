"""SSH tunnel: localhost:3307 -> production MySQL. Run as background process or Docker."""
import paramiko, socket, threading, time, os, sys

JUMP = os.environ.get("JUMP_HOST", "123.57.0.174")
PROD = os.environ.get("PROD_HOST", "190.92.220.4")
KEY = os.environ.get("SSH_KEY", os.path.expanduser("~/.ssh/id_rsa"))
PASS = os.environ.get("PROD_PASS", "openlab@123")
MYSQL_IP = os.environ.get("MYSQL_IP", "172.27.0.4")

# Parse FORWARDS from env: "3307:172.27.0.4:3306,8080:127.0.0.1:8080"
forwards_str = os.environ.get("FORWARDS", f"3307:{MYSQL_IP}:3306,8080:127.0.0.1:8080")
FORWARDS = []
for f in forwards_str.split(","):
    parts = f.strip().split(":")
    if len(parts) == 3:
        FORWARDS.append((int(parts[0]), (parts[1], int(parts[2]))))

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

            servers = []
            for local_port, (remote_host, remote_port) in FORWARDS:
                srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                srv.bind(("127.0.0.1", local_port))
                srv.listen(5)
                srv.settimeout(1)
                servers.append((srv, remote_host, remote_port))
                print(f"[tunnel] localhost:{local_port} -> {PROD}:{remote_port}", flush=True)

            while True:
                for srv, remote_host, remote_port in servers:
                    try:
                        client, addr = srv.accept()
                        chan = prod.get_transport().open_channel("direct-tcpip", (remote_host, remote_port), addr)
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
                        if "Errno 9" not in str(e):
                            print(f"[tunnel] error: {e}", flush=True)
                time.sleep(0.1)
            for srv, _, _ in servers:
                srv.close(); prod.close(); jump.close()
        except Exception as e:
            print(f"[tunnel] restart in 5s: {e}", flush=True)
            time.sleep(5)

if __name__ == "__main__":
    run()
