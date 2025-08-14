#!/usr/bin/env python3
"""
Simple VNC test focusing on message format
"""
import socket
import struct
import des

def test_vnc_messages():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(('127.0.0.1', 6405))
    
    try:
        # 1-3. Protocol, Security, Authentication (we know these work)
        version = sock.recv(12)
        sock.sendall(version)
        
        num_sec_types = sock.recv(1)[0]
        sec_types = sock.recv(num_sec_types)
        sock.sendall(b'\x02')
        
        challenge = sock.recv(16)
        password = "lise"
        key = bytearray(8)
        for i, char in enumerate(password.ljust(8, '\0')[:8]):
            byte = ord(char)
            reversed_byte = 0
            for j in range(8):
                if byte & (1 << j):
                    reversed_byte |= (1 << (7 - j))
            key[i] = reversed_byte
        
        response = des.DesKey(key).encrypt(challenge, padding=True)
        sock.sendall(response)
        
        status = struct.unpack('>I', sock.recv(4))[0]
        if status != 0:
            raise ValueError(f"Authentication failed: {status}")
        
        # 4. Client Init
        sock.sendall(b'\x01')  # Share desktop
        
        # ServerInit
        width, height = struct.unpack('>HH', sock.recv(4))
        bpp, depth, big_endian, true_color = struct.unpack('>BBBB', sock.recv(4))
        red_max, green_max, blue_max = struct.unpack('>HHH', sock.recv(6))
        red_shift, green_shift, blue_shift = struct.unpack('>BBB', sock.recv(3))
        sock.recv(3)  # padding
        name_len = struct.unpack('>I', sock.recv(4))[0]
        name = sock.recv(name_len)
        
        print(f"Connected to: {name.decode()}, {width}x{height}")
        
        # Must send SetEncodings before requesting framebuffer
        print("Setting encodings to Raw (0)...")
        # SetEncodings: msg-type(1) + padding(1) + num-encodings(2) + encodings(4*n)
        set_encodings = struct.pack('>BBHi', 2, 0, 1, 0)  # Type 2, 0 padding, 1 encoding, Raw(0)
        print(f"Sending SetEncodings: {set_encodings.hex()}")
        sock.sendall(set_encodings)
        
        print("Requesting framebuffer update...")
        
        # FramebufferUpdateRequest: msg-type(1) + incremental(1) + x(2) + y(2) + w(2) + h(2)
        framebuffer_request = struct.pack('>BBHHHH', 3, 0, 0, 0, width, height)
        print(f"Sending framebuffer request: {framebuffer_request.hex()}")
        sock.sendall(framebuffer_request)
        
        # Try to read response
        print("Waiting for response...")
        sock.settimeout(5.0)  # 5 second timeout
        response = sock.recv(1)
        if response:
            msg_type = response[0]
            print(f"Received message type: {msg_type}")
            
            if msg_type == 0:  # FramebufferUpdate
                padding = sock.recv(1)
                num_rects = struct.unpack('>H', sock.recv(2))[0]
                print(f"Framebuffer update with {num_rects} rectangles")
        else:
            print("No response received")
        
    except socket.timeout:
        print("Timeout waiting for response")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        sock.close()

if __name__ == "__main__":
    test_vnc_messages()
