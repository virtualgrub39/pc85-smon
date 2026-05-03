#!/usr/bin/env python3
"""
WARNING: MADE BY A LLM (claude 4.6) - USE ONLY FOR TESTING

rreaper.py - Host-side utility for the EPROG328 EEPROM writer (ATmega328p)
Protocol: Intel HEX over serial UART, 8N1

Usage:
  rreaper.py <port> [--baud N] write  <address> <file> [--verify] [--hex]
  rreaper.py <port> [--baud N] read   <address> <size> <file>      [--hex]
  rreaper.py <port> [--baud N] verify <address> <file>             [--hex]
  rreaper.py <port> [--baud N] crc    <address> <size>

Intel HEX file mode (--hex):
  write  -- reads an .hex file; the start address is taken from the file
             records (the CLI <address> is used only as a sanity-check warning)
  read   -- performs a normal EEPROM read but writes the result as an .hex file
             instead of a raw binary file
  verify -- reads an .hex file; the start address is taken from the file records

Examples:
  rreaper.py /dev/ttyUSB0 write 0x0000 firmware.bin
  rreaper.py /dev/ttyUSB0 write 0x0000 firmware.hex --hex
  rreaper.py /dev/ttyUSB0 write 0x0000 firmware.hex --hex --verify
  rreaper.py /dev/ttyACM0 --baud 115200 read 0x0000 256 dump.bin
  rreaper.py /dev/ttyACM0 --baud 115200 read 0x0000 256 dump.hex --hex
  rreaper.py /dev/ttyUSB0 verify 0x0000 firmware.bin
  rreaper.py /dev/ttyUSB0 verify 0x0000 firmware.hex --hex
  rreaper.py /dev/ttyUSB0 crc 0x0000 256
"""

import argparse
import sys
import time
import serial  # pip install pyserial

# Must match #define DATA_BLOCK_SZ on the device
DATA_BLOCK_SZ = 16

# EEPROM device IDs (must match device firmware)
EEPROM_ID_INTERNAL = 0x00
EEPROM_ID_PARALLEL = 0x01


# ---------------------------------------------------------------------------
# Intel HEX helpers
# ---------------------------------------------------------------------------

def ihex_checksum(byte_count: int, addr: int, rec_type: int, data: bytes) -> int:
    """
    Intel HEX two's complement checksum:
    least significant byte of the two's complement of the sum of all bytes.
    """
    total = byte_count + ((addr >> 8) & 0xFF) + (addr & 0xFF) + rec_type
    total += sum(data)
    return (~total + 1) & 0xFF


def make_ihex_record(addr: int, data: bytes) -> str:
    """Build a type-00 (data) Intel HEX record string, without newline."""
    bc = len(data)
    cs = ihex_checksum(bc, addr, 0x00, data)
    hex_data = ''.join(f'{b:02X}' for b in data)
    return f':{bc:02X}{addr:04X}00{hex_data}{cs:02X}'


def parse_ihex_record(line: str):
    """
    Parse an Intel HEX record line.
    Returns (byte_count, addr, rec_type, data, checksum).
    Raises ValueError on format or checksum errors.
    """
    line = line.strip()
    if not line.startswith(':'):
        raise ValueError(f"Not an Intel HEX record: {line!r}")
    s = line[1:]
    try:
        bc   = int(s[0:2],  16)
        addr = int(s[2:6],  16)
        rt   = int(s[6:8],  16)
        data = bytes(int(s[8 + i*2 : 10 + i*2], 16) for i in range(bc))
        cs   = int(s[8 + bc*2 : 10 + bc*2], 16)
    except (ValueError, IndexError) as exc:
        raise ValueError(f"Malformed Intel HEX record: {line!r}") from exc

    expected = ihex_checksum(bc, addr, rt, data)
    if cs != expected:
        raise ValueError(
            f"Checksum error at 0x{addr:04X}: "
            f"got {cs:02X}, expected {expected:02X}"
        )
    return bc, addr, rt, data, cs


# ---------------------------------------------------------------------------
# Intel HEX file I/O  (full-file, not the wire-level record helpers above)
# ---------------------------------------------------------------------------

# Record type constants
_RT_DATA     = 0x00
_RT_EOF      = 0x01
_RT_EXT_SEG  = 0x02   # Extended Segment Address
_RT_EXT_LIN  = 0x04   # Extended Linear Address
_RT_START_LIN = 0x05  # Start Linear Address (ignored on read)


def load_ihex_file(path: str) -> tuple[int, bytes]:
    """
    Parse an Intel HEX file and return (base_address, data).

    Handles:
      - Type 00  Data records
      - Type 01  EOF  record
      - Type 02  Extended Segment Address records (shifts subsequent data)
      - Type 04  Extended Linear Address records  (shifts subsequent data)

    Gaps between records are filled with 0xFF (standard erased EEPROM value).
    Raises ValueError on any format/checksum error or if the file is empty.
    """
    # Collect individual bytes keyed by their 32-bit absolute address.
    mem: dict[int, int] = {}
    upper_base = 0   # set by type-02 / type-04 records

    with open(path, 'r') as fh:
        for lineno, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                bc, addr, rt, data, _ = parse_ihex_record(raw)
            except ValueError as exc:
                raise ValueError(f"Line {lineno}: {exc}") from exc

            if rt == _RT_EOF:
                break
            elif rt == _RT_DATA:
                abs_base = upper_base + addr
                for i, byte in enumerate(data):
                    mem[abs_base + i] = byte
            elif rt == _RT_EXT_SEG:
                # 20-bit segmented address; the record carries a 16-bit segment
                # that is shifted left by 4 bits.
                if bc != 2:
                    raise ValueError(f"Line {lineno}: type-02 record must have 2 data bytes")
                upper_base = ((data[0] << 8) | data[1]) << 4
            elif rt == _RT_EXT_LIN:
                # 32-bit linear address; the record carries the upper 16 bits.
                if bc != 2:
                    raise ValueError(f"Line {lineno}: type-04 record must have 2 data bytes")
                upper_base = ((data[0] << 8) | data[1]) << 16
            elif rt == _RT_START_LIN:
                pass  # Ignore start address records (EIP value for x86)
            else:
                # Unknown record type – warn and continue
                print(f"  Warning: unknown Intel HEX record type 0x{rt:02X} at line {lineno}",
                      file=sys.stderr)

    if not mem:
        raise ValueError(f"No data records found in Intel HEX file: {path!r}")

    min_addr = min(mem.keys())
    max_addr = max(mem.keys())
    size     = max_addr - min_addr + 1

    result = bytearray(b'\xFF' * size)
    for abs_addr, byte in mem.items():
        result[abs_addr - min_addr] = byte

    return min_addr, bytes(result)


def save_ihex_file(path: str, address: int, data: bytes) -> None:
    """
    Write binary *data* starting at *address* to an Intel HEX file at *path*.

    Records are DATA_BLOCK_SZ bytes wide (matching the wire protocol), followed
    by a standard type-01 EOF record.  If *address* requires the upper 16 bits
    to be set (i.e. address >= 0x10000), a type-04 Extended Linear Address
    record is emitted first.
    """
    with open(path, 'w') as fh:
        # Emit an Extended Linear Address record if the base address does not
        # fit in 16 bits.
        upper = (address >> 16) & 0xFFFF
        if upper:
            ela_data  = bytes([upper >> 8, upper & 0xFF])
            ela_cs    = ihex_checksum(2, 0x0000, _RT_EXT_LIN, ela_data)
            ela_hex   = ''.join(f'{b:02X}' for b in ela_data)
            fh.write(f':02000004{ela_hex}{ela_cs:02X}\n')

        offset = 0
        while offset < len(data):
            chunk     = data[offset : offset + DATA_BLOCK_SZ]
            word_addr = (address + offset) & 0xFFFF   # lower 16 bits only
            fh.write(make_ihex_record(word_addr, chunk) + '\n')
            offset   += len(chunk)

        # EOF record
        fh.write(':00000001FF\n')


# ---------------------------------------------------------------------------
# Progress bar
# ---------------------------------------------------------------------------

def _progress(done: int, total: int, width: int = 50) -> None:
    filled = int(width * done / total) if total else width
    bar    = '#' * filled + '-' * (width - filled)
    print(f"\r  [{bar}] {done}/{total} bytes ", end='', flush=True)


# ---------------------------------------------------------------------------
# Device commands
# ---------------------------------------------------------------------------

def probe_device(ser: serial.Serial) -> bool:
    """Send 'I' and look for the EPROG328 banner in the response."""
    ser.write(b'I')
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        raw = ser.readline()
        line = raw.decode(errors='replace').strip()
        if 'RREAPER' in line:
            print(f"  Device: {line}")
            return True
    return False


def cmd_device(ser: serial.Serial, device_id: int) -> None:
    """
    Select the active EEPROM device.
    Sends 'D<XX>' where XX is the device ID as a two-digit hex byte,
    then waits for 'OK'.

    Must be called after every reset before any EEPROM operation because
    the firmware boots with EEPROM_ID_INTERNAL selected by default.
    """
    ser.write(f'D{device_id:02X}'.encode())
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        line = ser.readline().decode(errors='replace').strip()
        if not line:
            continue
        if 'OK' in line:
            return
        if line.startswith('E ') or line.startswith('ERR') or 'ERROR' in line.upper():
            raise RuntimeError(f"Device select failed (id=0x{device_id:02X}): {line!r}")
    raise RuntimeError(f"Timeout waiting for device select ACK (id=0x{device_id:02X})")


def cmd_write(ser: serial.Serial, address: int, data: bytes) -> None:
    """
    Write binary data to EEPROM starting at address.
    Splits into DATA_BLOCK_SZ chunks and sends each as an Intel HEX record
    prefixed with 'W '.  Waits for 'OK' before sending the next chunk.
    """
    total  = len(data)
    offset = 0

    while offset < total:
        chunk  = data[offset : offset + DATA_BLOCK_SZ]
        record = make_ihex_record(address + offset, chunk)

        # Device waits for a ':' start-code after 'W', so the space is fine.
        ser.write(f'W {record}'.encode())

        # Wait for OK (or an error)
        while True:
            line = ser.readline().decode(errors='replace').strip()
            if not line:
                continue
            if 'OK' in line:
                break
            if line.startswith('E ') or line.startswith('ERR') or 'ERROR' in line.upper():
                raise RuntimeError(f"Device error at offset {offset}: {line!r}")

        offset += len(chunk)
        _progress(min(offset, total), total)

    print()  # newline after progress bar


def cmd_read(ser: serial.Serial, address: int, size: int, outfile: str,
             hex_mode: bool = False) -> None:
    expected_records = (size + DATA_BLOCK_SZ - 1) // DATA_BLOCK_SZ

    ser.reset_input_buffer()

    cmd = f'R {address:04X} {size:04X}\n'
    ser.write(cmd.encode())

    result = bytearray(size)
    bytes_stored = 0
    records_got = 0

    print(f"  Expecting {expected_records} records...")

    while records_got < expected_records:
        raw = ser.readline()
        if not raw:
            # This triggers on the 5.0s timeout
            print("\n  [Timeout] No data from MCU. Last record got:", records_got)
            break

        line = raw.decode(errors='replace').strip()

        if line.startswith(':'):
            bc, addr, rt, data, _ = parse_ihex_record(line)
            rel    = addr - address
            actual = min(bc, size - rel)
            if 0 <= rel < size:
                result[rel : rel + actual] = data[:actual]
                bytes_stored += actual
                records_got  += 1
                _progress(bytes_stored, size)
        elif line:
            # This will show us if the MCU is sending "READY" or an error
            print(f"\n  [Unexpected Data] {line!r}")

    print()
    if hex_mode:
        save_ihex_file(outfile, address, bytes(result))
    else:
        with open(outfile, 'wb') as f:
            f.write(result)


class VerifyError(RuntimeError):
    """Raised when the device reports a verify mismatch."""
    def __init__(self, abs_addr: int):
        self.abs_addr = abs_addr          # absolute EEPROM address of the mismatching block
        super().__init__(
            f"Verify mismatch at or near EEPROM address 0x{abs_addr:04X}"
        )


def _send_verify_record(ser: serial.Serial, address: int, chunk: bytes) -> None:
    """
    Send one 'V <ihex record>' to the device and wait for OK or 'E VERIFY'.
    Raises VerifyError on mismatch, RuntimeError on any other device error.

    Note: the firmware reports mismatches as 'E VERIFY\\r\\n' without a byte
    offset (the offset was removed in the current firmware revision).
    """
    record = make_ihex_record(address, chunk)
    ser.write(f'V {record}'.encode())

    while True:
        line = ser.readline().decode(errors='replace').strip()
        if not line:
            continue
        if 'OK' in line:
            return
        if 'VERIFY' in line.upper():
            raise VerifyError(address)
        if line.startswith('E ') or line.startswith('ERR') or 'ERROR' in line.upper():
            raise RuntimeError(f"Device error during verify at 0x{address:04X}: {line!r}")


def cmd_verify(ser: serial.Serial, address: int, data: bytes) -> None:
    """
    Verify EEPROM contents against data starting at address.
    Sends each block as a 'V' record; the MCU reads back the EEPROM and
    compares on-device, replying OK or E VERIFY.
    Raises VerifyError on first mismatch.
    """
    total  = len(data)
    offset = 0

    while offset < total:
        chunk = data[offset : offset + DATA_BLOCK_SZ]
        _send_verify_record(ser, address + offset, chunk)
        offset += len(chunk)
        _progress(min(offset, total), total)

    print()


def cmd_crc(ser: serial.Serial, address: int, size: int) -> int:
    """
    Ask the device to compute CRC16 over size bytes of EEPROM starting at
    address.  Sends 'C<AAAA><SSSS>' (address and size as 4-digit hex words)
    and reads back the 4-digit hex CRC word emitted by the device.
    Returns the CRC as an integer.
    """
    ser.write(f'C{address:04X}{size:04X}'.encode())

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        line = ser.readline().decode(errors='replace').strip()
        if not line:
            continue
        if line.startswith('E ') or line.startswith('ERR') or 'ERROR' in line.upper():
            raise RuntimeError(f"CRC command error: {line!r}")
        try:
            return int(line, 16)
        except ValueError:
            # Could be an unexpected informational line; keep reading.
            continue

    raise RuntimeError("Timeout waiting for CRC response")


# ---------------------------------------------------------------------------
# Helpers used by main()
# ---------------------------------------------------------------------------

def _load_input_file(filepath: str, cli_address: int,
                     hex_mode: bool) -> tuple[int, bytes]:
    """
    Load *filepath* as either raw binary or Intel HEX depending on *hex_mode*.

    Returns (effective_address, data).

    In hex mode the start address is taken from the file.  If it differs from
    *cli_address* a warning is printed, but the file's address wins.
    In binary mode the returned address is always *cli_address*.
    """
    if hex_mode:
        file_addr, data = load_ihex_file(filepath)
        if file_addr != cli_address:
            print(
                f"  Note: Intel HEX file base address is 0x{file_addr:04X}; "
                f"using that instead of the CLI address 0x{cli_address:04X}.",
                file=sys.stderr,
            )
        return file_addr, data
    else:
        with open(filepath, 'rb') as fh:
            data = fh.read()
        return cli_address, data


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description='EPROG328 host-side EEPROM utility (Intel HEX / UART)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)

    parser.add_argument('port',
        help='Serial device path, e.g. /dev/ttyUSB0 or /dev/ttyACM0')
    parser.add_argument('--baud', type=int, default=9600,
        help='Baud rate (default: 9600; must match BAUD in config.h)')
    parser.add_argument('--no-probe', action='store_true',
        help="Skip the 'I' device probe on startup")
    parser.add_argument('--timeout', type=float, default=5.0,
        help='Serial read timeout in seconds (default: 5)')

    sub = parser.add_subparsers(dest='command', required=True)

    # -- write subcommand --
    wp = sub.add_parser('write', help='Write a binary or Intel HEX file to EEPROM')
    wp.add_argument('address', type=lambda x: int(x, 0),
        help='Start address, hex (0x0000) or decimal. '
             'Ignored in --hex mode (address is read from the file).')
    wp.add_argument('file', help='Binary (.bin) or Intel HEX (.hex) input file')
    wp.add_argument('--verify', action='store_true',
        help='Verify each block against EEPROM contents after writing')
    wp.add_argument('--hex', action='store_true',
        help='Treat <file> as an Intel HEX file instead of raw binary')

    # -- read subcommand --
    rp = sub.add_parser('read', help='Read EEPROM region into a binary or Intel HEX file')
    rp.add_argument('address', type=lambda x: int(x, 0),
        help='Start address, hex (0x0000) or decimal')
    rp.add_argument('size', type=lambda x: int(x, 0),
        help='Number of bytes to read, hex (0x100) or decimal')
    rp.add_argument('file', help='Output file path (.bin or .hex)')
    rp.add_argument('--hex', action='store_true',
        help='Write output as an Intel HEX file instead of raw binary')

    # -- verify subcommand --
    vp = sub.add_parser('verify', help='Verify EEPROM contents against a binary or Intel HEX file')
    vp.add_argument('address', type=lambda x: int(x, 0),
        help='Start address, hex (0x0000) or decimal. '
             'Ignored in --hex mode (address is read from the file).')
    vp.add_argument('file', help='Binary (.bin) or Intel HEX (.hex) file to verify against')
    vp.add_argument('--hex', action='store_true',
        help='Treat <file> as an Intel HEX file instead of raw binary')

    # -- crc subcommand --
    cp = sub.add_parser('crc', help='Compute CRC16 of an EEPROM region')
    cp.add_argument('address', type=lambda x: int(x, 0),
        help='Start address, hex (0x0000) or decimal')
    cp.add_argument('size', type=lambda x: int(x, 0),
        help='Number of bytes, hex (0x100) or decimal')

    args = parser.parse_args()

    # -- open serial port --
    print(f"Opening {args.port} at {args.baud} baud...")
    try:
        ser = serial.Serial(args.port, args.baud, timeout=args.timeout)
    except serial.SerialException as exc:
        sys.exit(f"Error opening serial port: {exc}")

    # Many AVR boards reset when DTR is toggled on connect; give them time.
    time.sleep(2)
    ser.reset_input_buffer()

    # -- probe --
    if not args.no_probe:
        print("Probing device...")
        if not probe_device(ser):
            print("Warning: no EPROG328 banner received (continuing anyway)",
                  file=sys.stderr)

    # -- select parallel EEPROM --
    # The firmware boots with EEPROM_ID_INTERNAL (0x00) selected; switch to
    # EEPROM_ID_PARALLEL (0x01) unconditionally on every connect/reset.
    print(f"Selecting EEPROM device 0x{EEPROM_ID_PARALLEL:02X} (parallel)...")
    try:
        cmd_device(ser, EEPROM_ID_PARALLEL)
        print("  Device selected OK.")
    except RuntimeError as exc:
        ser.close()
        sys.exit(f"Error selecting EEPROM device: {exc}")

    # -- dispatch --
    try:
        if args.command == 'write':
            hex_mode = args.hex
            try:
                effective_addr, data = _load_input_file(
                    args.file, args.address, hex_mode)
            except (OSError, ValueError) as exc:
                sys.exit(f"Cannot read input file: {exc}")

            if not data:
                sys.exit("Error: input file is empty")

            file_kind  = "Intel HEX" if hex_mode else "binary"
            n_records  = (len(data) + DATA_BLOCK_SZ - 1) // DATA_BLOCK_SZ
            print(f"Writing {len(data)} bytes ({file_kind}) "
                  f"to 0x{effective_addr:04X} ({n_records} records)...")
            cmd_write(ser, effective_addr, data)
            print("Write complete.")

            if args.verify:
                print(f"Verifying {len(data)} bytes at 0x{effective_addr:04X}...")
                cmd_verify(ser, effective_addr, data)
                print("Verify OK.")

        elif args.command == 'read':
            hex_mode = args.hex
            file_kind = "Intel HEX" if hex_mode else "binary"
            print(f"Reading {args.size} bytes from 0x{args.address:04X} "
                  f"(output: {file_kind})...")
            cmd_read(ser, args.address, args.size, args.file, hex_mode=hex_mode)
            print("Read complete.")

        elif args.command == 'verify':
            hex_mode = args.hex
            try:
                effective_addr, data = _load_input_file(
                    args.file, args.address, hex_mode)
            except (OSError, ValueError) as exc:
                sys.exit(f"Cannot read input file: {exc}")

            if not data:
                sys.exit("Error: input file is empty")

            file_kind = "Intel HEX" if hex_mode else "binary"
            print(f"Verifying {len(data)} bytes ({file_kind}) "
                  f"at 0x{effective_addr:04X}...")
            cmd_verify(ser, effective_addr, data)
            print("Verify OK.")

        elif args.command == 'crc':
            print(f"Computing CRC16 of {args.size} bytes at 0x{args.address:04X}...")
            crc = cmd_crc(ser, args.address, args.size)
            print(f"CRC16: 0x{crc:04X}  ({crc})")

    except VerifyError as exc:
        print()
        sys.exit(f"VERIFY FAILED: {exc}")
    except RuntimeError as exc:
        print()
        sys.exit(f"Error: {exc}")
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(1)
    finally:
        ser.close()


if __name__ == '__main__':
    main()
