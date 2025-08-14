#!/usr/bin/env python3
"""
Test script to debug VNC connection issues
"""
import socket
import struct
import des

def test_vnc_connection():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(('127.0.0.1', 6405))
    
    try:
        # 1. Protocol Version Handshake
        version = sock.recv(12)
        print(f"Server version: {version}")
        sock.sendall(version)  # Echo back
        
        # 2. Security Handshake
        num_sec_types = sock.recv(1)[0]
        print(f"Number of security types: {num_sec_types}")
        sec_types = sock.recv(num_sec_types)
        print(f"Security types: {list(sec_types)}")
        
        # Choose VNC Authentication (type 2)
        if 2 not in sec_types:
            raise ValueError("VNC Authentication not supported by server.")
        sock.sendall(b'\x02')
        print("Sent security type choice: 2 (VNC Authentication)")
        
        # 3. VNC Authentication
        challenge = sock.recv(16)
        print(f"Received challenge: {challenge.hex()}")
        
        # Generate DES key from password "lise" with bit reversal
        password = "lise"
        key = bytearray(8)
        for i, char in enumerate(password.ljust(8, '\0')[:8]):
            byte = ord(char)
            # Reverse the bits in each byte (VNC requirement)
            reversed_byte = 0
            for j in range(8):
                if byte & (1 << j):
                    reversed_byte |= (1 << (7 - j))
            key[i] = reversed_byte
        print(f"DES key (bit-reversed): {key.hex()}")
        
        # Encrypt challenge
        response = des.DesKey(key).encrypt(challenge, padding=True)
        print(f"Response: {response.hex()}")
        sock.sendall(response)
        
        # Check authentication result
        status = struct.unpack('>I', sock.recv(4))[0]
        print(f"Authentication status: {status}")
        if status != 0:
            raise ValueError(f"VNC Authentication failed with status {status}")
        
        print("VNC Authentication successful!")
        
        # 4. Client/Server Init
        sock.sendall(b'\x01')  # Share desktop flag
        print("Sent client init (shared mode)")
        
        # ServerInit message
        width, height = struct.unpack('>HH', sock.recv(4))
        print(f"Screen size: {width}x{height}")
        
        print("VNC connection test successful!")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        sock.close()

if __name__ == "__main__":
    test_vnc_connection()
