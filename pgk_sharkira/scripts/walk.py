#!/usr/bin/env python3

import argparse
import math
import select
import socket
import sys
import rospy
from std_srvs.srv import SetBool
from puppy_control.msg import Velocity, Pose, Gait

ROS_NODE_NAME = 'puppy_demo'
DEFAULT_TCP_PORT = 9999

PuppyMove = {'x':6, 'y':0, 'yaw_rate':0}
PuppyReverse = {'x':-5, 'y':0, 'yaw_rate':0}
PuppyPose = {'roll':math.radians(0), 'pitch':math.radians(0), 'yaw':0.000, 'height':-10, 'x_shift':0.5, 'stance_x':0, 'stance_y':0}

gait = 'Amble'

if gait == 'Trot':
    GaitConfig = {'overlap_time':0.2, 'swing_time':0.3, 'clearance_time':0.0, 'z_clearance':5}
    PuppyPose['x_shift'] = -0.6

elif gait == 'Amble':
    GaitConfig = {'overlap_time':0.1, 'swing_time':0.2, 'clearance_time':0.1, 'z_clearance':5}
    PuppyPose['x_shift'] = -0.9
    
elif gait == 'Walk':
    GaitConfig = {'overlap_time':0.1, 'swing_time':0.2, 'clearance_time':0.3, 'z_clearance':5}
    PuppyPose['x_shift'] = -0.65

stdin_old_settings = None
tcp_server = None
tcp_client = None

def cleanup():
    PuppyVelocityPub.publish(x=0, y=0, yaw_rate=0)
    restore_keyboard()
    close_network()
    print('is_shutdown')

def walk(move):
    PuppyVelocityPub.publish(x=move['x'], y=move['y'], yaw_rate=move['yaw_rate'])

def stop():
    PuppyVelocityPub.publish(x=0, y=0, yaw_rate=0)

def handle_key(key):
    rospy.loginfo('key: %s', repr(key))
    if key in ('w', 'W'):
        walk(PuppyMove)
    elif key in ('s', 'S'):
        walk(PuppyReverse)
    elif key in ('z', 'Z'):
        stop()

def setup_keyboard():
    global stdin_old_settings
    if sys.platform == 'win32':
        return
    import tty
    import termios
    fd = sys.stdin.fileno()
    stdin_old_settings = termios.tcgetattr(fd)
    tty.setcbreak(fd)

def restore_keyboard():
    if stdin_old_settings is None:
        return
    import termios
    termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, stdin_old_settings)

def read_key():
    if sys.platform == 'win32':
        import msvcrt
        if msvcrt.kbhit():
            return msvcrt.getch().decode('utf-8', errors='ignore')
        return None
    if select.select([sys.stdin], [], [], 0.05)[0]:
        return sys.stdin.read(1)
    return None

def close_network():
    global tcp_server, tcp_client
    if tcp_client is not None:
        tcp_client.close()
        tcp_client = None
    if tcp_server is not None:
        tcp_server.close()
        tcp_server = None

def setup_network(host, port):
    global tcp_server
    tcp_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tcp_server.bind((host, port))
    tcp_server.listen(1)
    tcp_server.setblocking(False)
    rospy.loginfo('TCP listening on %s:%s', host, port)

def run_keyboard_loop():
    setup_keyboard()
    while not rospy.is_shutdown():
        try:
            key = read_key()
            if key is None:
                continue
            handle_key(key)
        except KeyboardInterrupt:
            restore_keyboard()
            sys.exit(0)

def run_network_loop():
    global tcp_client
    while not rospy.is_shutdown():
        try:
            readers = [tcp_server]
            if tcp_client is not None:
                readers.append(tcp_client)
            ready, _, _ = select.select(readers, [], [], 0.05)
            for sock in ready:
                if sock is tcp_server:
                    tcp_client, addr = tcp_server.accept()
                    tcp_client.setblocking(False)
                    rospy.loginfo('TCP client connected: %s', addr)
                else:
                    data = sock.recv(1024)
                    if not data:
                        rospy.loginfo('TCP client disconnected')
                        sock.close()
                        tcp_client = None
                        continue
                    for key in data.decode('utf-8', errors='ignore'):
                        handle_key(key)
        except KeyboardInterrupt:
            sys.exit(0)

def parse_args():
    parser = argparse.ArgumentParser(description='Puppy walk control')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--keyboard', action='store_const', const='keyboard', dest='input_mode',
                      help='read keys from terminal (default)')
    mode.add_argument('--network', action='store_const', const='network', dest='input_mode',
                      help='read keys from a TCP connection')
    parser.set_defaults(input_mode='keyboard')
    parser.add_argument('--host', default='0.0.0.0', help='TCP bind address (network mode)')
    parser.add_argument('--port', type=int, default=DEFAULT_TCP_PORT, help='TCP port (network mode)')
    return parser.parse_args(rospy.myargv(argv=sys.argv)[1:])

if __name__ == '__main__':
    args = parse_args()

    rospy.init_node(ROS_NODE_NAME, log_level=rospy.INFO)
    rospy.on_shutdown(cleanup)
    
    PuppyPosePub = rospy.Publisher('/puppy_control/pose', Pose, queue_size=1)
    PuppyGaitConfigPub = rospy.Publisher('/puppy_control/gait', Gait, queue_size=1)
    PuppyVelocityPub = rospy.Publisher('/puppy_control/velocity', Velocity, queue_size=1)

    set_mark_time_srv = rospy.ServiceProxy('/puppy_control/set_mark_time', SetBool)

    rospy.sleep(0.2)
    PuppyPosePub.publish(stance_x=PuppyPose['stance_x'], stance_y=PuppyPose['stance_y'], x_shift=PuppyPose['x_shift']
            ,height=PuppyPose['height'], roll=PuppyPose['roll'], pitch=PuppyPose['pitch'], yaw=PuppyPose['yaw'], run_time = 500)
    
    rospy.sleep(0.2)
    PuppyGaitConfigPub.publish(overlap_time = GaitConfig['overlap_time'], swing_time = GaitConfig['swing_time']
                    , clearance_time = GaitConfig['clearance_time'], z_clearance = GaitConfig['z_clearance'])
    rospy.sleep(0.2)

    set_mark_time_srv(False)
    stop()

    if args.input_mode == 'network':
        setup_network(args.host, args.port)
        run_network_loop()
    else:
        run_keyboard_loop()
