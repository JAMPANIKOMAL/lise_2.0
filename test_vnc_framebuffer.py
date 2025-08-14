#!/usr/bin/env python3
"""
Enhanced VNC test to debug framebuffer issues
"""
import socket
import struct
import des

def test_vnc_framebuffer():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(('127.0.0.1', 6405))
    
    try:
        # 1. Protocol Version Handshake
        version = sock.recv(12)
        print(f"Server version: {version}")
        sock.sendall(version)
        
        # 2. Security Handshake
        num_sec_types = sock.recv(1)[0]
        sec_types = sock.recv(num_sec_types)
        sock.sendall(b'\x02')  # Choose VNC Authentication
        
        # 3. VNC Authentication
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
        print("Authentication successful")
        
        # 4. Client/Server Init
        sock.sendall(b'\x01')  # Share desktop
        
        # ServerInit message
        width, height = struct.unpack('>HH', sock.recv(4))
        bpp, depth, big_endian, true_color = struct.unpack('>BBBB', sock.recv(4))
        red_max, green_max, blue_max = struct.unpack('>HHH', sock.recv(6))
        red_shift, green_shift, blue_shift = struct.unpack('>BBB', sock.recv(3))
        sock.recv(3)  # padding
        name_len = struct.unpack('>I', sock.recv(4))[0]
        name = sock.recv(name_len)
        
        print(f"Desktop: {name.decode()}")
        print(f"Size: {width}x{height}")
        print(f"Pixel format: {bpp}bpp, depth={depth}, true_color={true_color}")
        print(f"RGB max: {red_max}, {green_max}, {blue_max}")
        print(f"RGB shift: {red_shift}, {green_shift}, {blue_shift}")
        
        # 5. Set our preferred pixel format (32-bit ARGB)
        # SetPixelFormat: msg-type(1) + padding(3) + pixel-format(16)
        set_pixel_format_msg = struct.pack('>B3x', 0)  # Message type 0 + 3 bytes padding
        pixel_format = struct.pack('>BBBBHHHBBB3x', 
            32, 24, 0, 1,  # bpp, depth, big_endian, true_color
            255, 255, 255,  # red_max, green_max, blue_max  
            16, 8, 0)       # red_shift, green_shift, blue_shift
        sock.sendall(set_pixel_format_msg + pixel_format)
        print("Set pixel format to 32-bit ARGB")
        
        # 6. Set encodings (Raw only)
        # SetEncodings: msg-type(1) + padding(1) + num-encodings(2) + encodings(4*n)
        sock.sendall(struct.pack('>BB H i', 2, 0, 1, 0))
        print("Set encoding to Raw")
        
        # 7. Request framebuffer update
        sock.sendall(struct.pack('>BBHHHH', 3, 0, 0, 0, width, height))
        print("Requested full framebuffer update")
        
        # 8. Read the response
        msg_type = sock.recv(1)[0]
        print(f"Message type: {msg_type}")
        
        if msg_type == 0:  # FramebufferUpdate
            padding = sock.recv(1)
            num_rects = struct.unpack('>H', sock.recv(2))[0]
            print(f"Number of rectangles: {num_rects}")
            
            for i in range(num_rects):
                x, y, w, h, encoding = struct.unpack('>HHHHi', sock.recv(12))
                print(f"Rectangle {i}: pos=({x},{y}) size={w}x{h} encoding={encoding}")
                
                if encoding == 0:  # Raw
                    bytes_needed = w * h * 4  # Assuming 32bpp
                    print(f"Reading {bytes_needed} bytes of pixel data...")
                    data = b''
                    while len(data) < bytes_needed:
                        chunk = sock.recv(min(8192, bytes_needed - len(data)))
                        if not chunk:
                            break
                        data += chunk
                    print(f"Received {len(data)} bytes")
                    
                    # Sample a few pixels
                    if len(data) >= 16:
                        for p in range(min(4, len(data) // 4)):
                            pixel = data[p*4:(p+1)*4]
                            print(f"Pixel {p}: {pixel.hex()}")
        
        print("VNC test completed successfully!")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        sock.close()

if __name__ == "__main__":
    test_vnc_framebuffer()
