#!/usr/bin/env python3
"""Smoke test for the unit converter assignment.

Checks the student client and server against a reference implementation of
the application protocol, using the examples in Assegnazione.md. Passing this test
does NOT guarantee a pass in the final grading, which uses further cases.

Usage: smoke_test.py CLIENT_EXE SERVER_EXE
"""

import os
import select
import socket
import struct
import subprocess
import sys
import math
import tempfile
import time

HOST = "127.0.0.1"
DEFAULT_PORT = 56700
REF_PORT = 56701
CLOSED_PORT = 56702
TIMEOUT = 5
MAX_VALUE = 1000.0
PREFIX = "Ricevuto risultato dal server ip 127.0.0.1. "

UNITS = {  # (quantity, 1 unit in metres or kilograms)
    "m": ("L", 1.0), "km": ("L", 1000.0), "ft": ("L", 0.3048),
    "yd": ("L", 0.9144), "mi": ("L", 1609.344),
    "g": ("M", 0.001), "kg": ("M", 1.0), "oz": ("M", 0.028349523),
    "lb": ("M", 0.45359237),
}

# (-r argument, expected client output after PREFIX, expected server log)
CASES = [
    ("mi km 26.2", "26.20 mi = 42.16 km", "Richiesta 'mi km 26.20' dal client ip 127.0.0.1"),
    ("km mi 10", "10.00 km = 6.21 mi", "Richiesta 'km mi 10.00' dal client ip 127.0.0.1"),
    ("m ft 100", "100.00 m = 328.08 ft", "Richiesta 'm ft 100.00' dal client ip 127.0.0.1"),
    ("ft m 1", "1.00 ft = 0.30 m", "Richiesta 'ft m 1.00' dal client ip 127.0.0.1"),
    ("kg lb 70.5", "70.50 kg = 155.43 lb", "Richiesta 'kg lb 70.50' dal client ip 127.0.0.1"),
    ("lb oz 2.5", "2.50 lb = 40.00 oz", "Richiesta 'lb oz 2.50' dal client ip 127.0.0.1"),
    ("yd yd 12.34", "12.34 yd = 12.34 yd", "Richiesta 'yd yd 12.34' dal client ip 127.0.0.1"),
    ("mi ft 1000", "1000.00 mi = 5280000.00 ft", "Richiesta 'mi ft 1000.00' dal client ip 127.0.0.1"),
    ("KM mi 1", "Simbolo non supportato", "Richiesta 'KM mi 1.00' dal client ip 127.0.0.1"),
    ("m xyz 0", "Simbolo non supportato", "Richiesta 'm xyz 0.00' dal client ip 127.0.0.1"),
    ("km kg 0", "Grandezze incompatibili", "Richiesta 'km kg 0.00' dal client ip 127.0.0.1"),
    ("m km -5", "Valore non valido", "Richiesta 'm km -5.00' dal client ip 127.0.0.1"),
    ("g kg 0", "Valore non valido", "Richiesta 'g kg 0.00' dal client ip 127.0.0.1"),
    ("lb kg 1000.01", "Valore non valido", "Richiesta 'lb kg 1000.01' dal client ip 127.0.0.1"),
]

USAGE_CASES = ["mile km 10", "m km abc", "m km 10,50", "m km", "m km 10 20"]

BYTE_ORDER_HINT = "sembra un errore di byte order: hai usato htonl()/ntohl()?"
FLOAT_HINT = "sembra che il float sia stato convertito in intero: vanno copiati i suoi bit con memcpy()"

results = []  # (section, name, ok, detail)


def check(section, name, ok, detail=""):
    results.append((section, name, ok, detail))
    print("[%s] %s: %s%s" % ("OK" if ok else "FAIL", section, name, "" if ok else " -> " + detail))


def to_float32(x):
    """Round a Python float to IEEE 754 single precision, like a C float."""
    return struct.unpack("!f", struct.pack("!f", x))[0]


def same_float(a, b):
    """Equal up to one float32 rounding (compilers may differ in the last bit)."""
    return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-6)


def parse_request(req):
    frm, to, value = req.split(" ")
    return frm, to, to_float32(float(value))


def reference_response(frm, to, value):
    unit_from, unit_to = UNITS.get(frm), UNITS.get(to)
    if unit_from is None or unit_to is None:
        return 1, 0
    if unit_from[0] != unit_to[0]:
        return 2, 0
    if not (value > 0 and value <= MAX_VALUE):
        return 3, 0.0
    factor_from, factor_to = unit_from[1], unit_to[1]
    return 0, to_float32(value * factor_from / factor_to)  # convert(): double math, float result


def recv_exactly(sock, n):
    data = b""
    while len(data) < n:
        try:
            chunk = sock.recv(n - len(data))
        except socket.timeout:
            if data:  # partial message: report its length instead of a generic timeout
                break
            raise
        if not chunk:
            break
        data += chunk
    return data


def normalize(out):
    return out.decode("utf-8", errors="replace").replace("\r\n", "\n").rstrip("\n")


def executable(path):
    path = os.path.abspath(path)
    if os.name == "nt" and not path.lower().endswith(".exe"):
        path += ".exe"
    return path


def run_client(client, args):
    try:
        proc = subprocess.run([client] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              stdin=subprocess.DEVNULL, timeout=TIMEOUT)
        return proc.returncode, normalize(proc.stdout), None
    except subprocess.TimeoutExpired:
        return None, "", "il client non termina entro %d s" % TIMEOUT
    except OSError as e:
        return None, "", "impossibile eseguire il client: %s" % e


def connect_with_retry(port):
    deadline = time.time() + TIMEOUT
    while True:
        try:
            return socket.create_connection((HOST, port), timeout=TIMEOUT)
        except ConnectionRefusedError:
            if time.time() > deadline:
                raise
            time.sleep(0.2)


def test_server(server, client):
    section = "server"
    log = tempfile.TemporaryFile()
    errors = tempfile.TemporaryFile()
    try:
        proc = subprocess.Popen([server], stdout=log, stderr=errors, stdin=subprocess.DEVNULL)
    except OSError as e:
        check(section, "avvio", False, "impossibile eseguire il server: %s" % e)
        return
    time.sleep(1)
    if proc.poll() is not None:
        errors.seek(0)
        stderr = normalize(errors.read()).strip()
        check(section, "avvio", False, "il server termina subito (exit code %s)%s"
              % (proc.returncode, (": " + stderr.replace("\n", " | ")) if stderr else ""))
        return
    check(section, "avvio", True)

    expected_log = []
    for req, _, log_line in CASES:
        frm, to, value = parse_request(req)
        payload = struct.pack("!4s4sf", frm.encode(), to.encode(), value)
        name = "risposta a '%s'" % req
        try:
            with connect_with_retry(DEFAULT_PORT) as sock:
                sock.sendall(payload)
                data = recv_exactly(sock, 8)
        except OSError as e:
            check(section, name, False, "errore di comunicazione sulla porta %d: %s (richieste "
                  "successive saltate)" % (DEFAULT_PORT, e))
            break
        expected_log.append(log_line)
        if len(data) != 8:
            check(section, name, False, "ricevuti %d byte invece di 8" % len(data))
            continue
        got = struct.unpack("!If", data)
        expected = reference_response(frm, to, value)
        if got[0] == expected[0] and same_float(got[1], expected[1]):
            check(section, name, True)
        else:
            detail = "status/value = (%d, %g), attesi (%d, %g)" % (got[0], got[1], expected[0], expected[1])
            got_le = struct.unpack("<If", data)
            if (got_le[0] == expected[0] and same_float(got_le[1], expected[1])) \
                    or (got[0] > 3 and got_le[0] <= 3):
                detail += "; " + BYTE_ORDER_HINT
            elif got[0] == expected[0] and struct.unpack("!I", data[4:8])[0] == int(expected[1]):
                detail += "; " + FLOAT_HINT
            check(section, name, False, detail)

    # End-to-end: student client against student server, default address and port
    code, out, err = run_client(client, ["-r", CASES[0][0]])
    expected_out = PREFIX + CASES[0][1]
    if err:
        check("end-to-end", "client e server con parametri di default", False, err)
    else:
        expected_log.append(CASES[0][2])
        check("end-to-end", "client e server con parametri di default", code == 0 and out == expected_out,
              "exit code %s, output %r, atteso %r" % (code, out, expected_out))

    proc.terminate()
    try:
        proc.wait(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
    log.seek(0)
    lines = normalize(log.read()).split("\n")
    missing = [line for line in expected_log if line not in lines]
    if not expected_log:  # no request reached the server: nothing to verify
        return
    check(section, "log delle richieste", not missing,
          "righe mancanti o diverse, ad es. %r (righe stampate: %r). Se non stampa nulla, "
          "chiama fflush(stdout) dopo ogni printf" % (missing[0] if missing else "", lines[:3]))


def serve_reference(conn):
    """Read one request and reply as the reference server. Returns the raw request."""
    with conn:
        conn.settimeout(TIMEOUT)
        data = recv_exactly(conn, 12)
        if len(data) == 12:
            frm = data[0:4].split(b"\0")[0].decode("ascii", errors="replace")
            to = data[4:8].split(b"\0")[0].decode("ascii", errors="replace")
            value = struct.unpack("!f", data[8:12])[0]
            conn.sendall(struct.pack("!If", *reference_response(frm, to, value)))
        return data


def client_vs_reference(client, args, listener):
    """Run the client against the reference server.

    Returns (exit code, stdout, raw request or None if no connection, error).
    """
    try:
        proc = subprocess.Popen([client] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                stdin=subprocess.DEVNULL)
    except OSError as e:
        return None, "", None, "impossibile eseguire il client: %s" % e
    request, error = None, None
    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        exited = proc.poll() is not None
        if select.select([listener], [], [], 0.3 if exited else 0.1)[0]:
            try:
                request = serve_reference(listener.accept()[0])
            except OSError as e:
                request, error = b"", "errore di comunicazione: %s" % e
            break
        if exited:
            break
    try:
        out, _ = proc.communicate(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return None, "", request, "il client non termina entro %d s" % TIMEOUT
    return proc.returncode, normalize(out), request, error


def check_request(data, frm, to, value):
    if data is None:
        return "nessuna richiesta ricevuta"
    if len(data) != 12:
        return "ricevuti %d byte invece di 12" % len(data)
    if b"\0" not in data[0:4] or b"\0" not in data[4:8]:
        return "i campi from/to devono terminare con '\\0' entro i 4 byte"
    got_from = data[0:4].split(b"\0")[0].decode("ascii", "replace")
    got_to = data[4:8].split(b"\0")[0].decode("ascii", "replace")
    if (got_from, got_to) != (frm, to):
        return "simboli ricevuti %r, attesi %r" % ((got_from, got_to), (frm, to))
    got = struct.unpack("!f", data[8:12])[0]
    if not same_float(got, value):
        detail = "value ricevuto %g, atteso %g" % (got, value)
        if same_float(struct.unpack("<f", data[8:12])[0], value):
            detail += "; " + BYTE_ORDER_HINT
        elif struct.unpack("!I", data[8:12])[0] == int(value):
            detail += "; " + FLOAT_HINT
        return detail
    return None


def test_client(client):
    section = "client"
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name != "nt":  # on Windows SO_REUSEADDR allows port hijacking
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((HOST, REF_PORT))
    listener.listen(5)
    port_args = ["-s", HOST, "-p", str(REF_PORT)]

    for req, expected_out, _ in CASES:
        frm, to, value = parse_request(req)
        name = "output per '%s'" % req
        code, out, request, err = client_vs_reference(client, port_args + ["-r", req], listener)
        if err:
            check(section, name, False, err)
            continue
        if request is None:
            check(section, name, False, "il client non si connette al server")
            continue
        problem = check_request(request, frm, to, value)
        if problem:
            check(section, name, False, "richiesta errata: " + problem)
            continue
        expected_out = PREFIX + expected_out
        check(section, name, code == 0 and out == expected_out,
              "exit code %s, output %r, atteso %r" % (code, out, expected_out))

    for req in USAGE_CASES:
        name = "argomenti non validi '%s'" % req
        code, out, request, err = client_vs_reference(client, port_args + ["-r", req], listener)
        if err:
            check(section, name, False, err)
        else:
            check(section, name, code != 0 and request is None,
                  "atteso exit code != 0 e nessuna connessione (exit code %s, connessione: %s)"
                  % (code, "no" if request is None else "si"))
    listener.close()

    code, out, err = run_client(client, ["-s", HOST, "-p", str(CLOSED_PORT), "-r", CASES[0][0]])
    check(section, "server non raggiungibile", not err and code != 0 and not out.startswith(PREFIX),
          err or "atteso exit code != 0 (exit code %s, output %r)" % (code, out))


def write_summary():
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write("## Smoke test\n\n| Esito | Area | Verifica | Dettaglio |\n|---|---|---|---|\n")
        for section, name, ok, detail in results:
            f.write("| %s | %s | %s | %s |\n" % ("✅" if ok else "❌", section, name.replace("|", "\\|"),
                                               "" if ok else detail.replace("|", "\\|")))
        f.write("\n> Il superamento dello smoke test non garantisce il superamento della correzione finale.\n")


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    # On Windows a piped stdout is cp1252: avoid crashing on the student's output
    sys.stdout.reconfigure(errors="replace")
    client, server = executable(sys.argv[1]), executable(sys.argv[2])
    test_client(client)
    test_server(server, client)
    write_summary()
    failed = sum(1 for r in results if not r[2])
    print("\n%d verifiche, %d fallite" % (len(results), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
