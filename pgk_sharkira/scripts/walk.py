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

SPEED_FORWARD = 6
SPEED_BACK = -5
YAW_RATE = 0.3

PuppyPose = {'roll':math.radians(0), 'pitch':math.radians(0), 'yaw':0.000, 'height':-10, 'x_shift':0.5, 'stance_x':0, 'stance_y':0}

gait = 'Trot'

if gait == 'Trot':
    GaitConfig = {'overlap_time':0.2, 'swing_time':0.3, 'clearance_time':0.0, 'z_clearance':5}
    PuppyPose['x_shift'] = 0.6

elif gait == 'Amble':
    GaitConfig = {'overlap_time':0.1, 'swing_time':0.2, 'clearance_time':0.1, 'z_clearance':5}
    PuppyPose['x_shift'] = -0.9
    
elif gait == 'Walk':
    GaitConfig = {'overlap_time':0.1, 'swing_time':0.2, 'clearance_time':0.3, 'z_clearance':5}
    PuppyPose['x_shift'] = -0.65

def build_pose(height, pitch, x_shift=None):
    pose = dict(PuppyPose)
    pose['height'] = height
    pose['pitch'] = pitch
    if x_shift is not None:
        pose['x_shift'] = x_shift
    return pose

POSE_WALK = build_pose(PuppyPose['height'], PuppyPose['pitch'])
POSE_SIT_FLAT = build_pose(-20, math.radians(0), x_shift=0)
POSE_SIT_ANGLE = build_pose(-6, math.radians(28), x_shift=-1.1)

MOTION_KEYS = frozenset('wasdz')
POSE_KEYS = frozenset('kl')

stdin_old_settings = None
tcp_server = None
tcp_client = None
network_rx_buffer = ''

class ControlState(object):
    __slots__ = ('w', 'a', 's', 'd', 'z')

    def __init__(self):
        self.w = self.a = self.s = self.d = self.z = False

    def velocity(self):
        if self.z:
            return 0.0, 0.0, 0.0
        x = 0.0
        if self.w:
            x += SPEED_FORWARD
        if self.s:
            x += SPEED_BACK
        yaw_rate = 0.0
        if self.a:
            yaw_rate += YAW_RATE
        if self.d:
            yaw_rate -= YAW_RATE
        return x, 0.0, yaw_rate

control = ControlState()

def cleanup():
    PuppyVelocityPub.publish(x=0, y=0, yaw_rate=0)
    restore_keyboard()
    close_network()
    print('is_shutdown')

def apply_velocity():
    x, y, yaw_rate = control.velocity()
    PuppyVelocityPub.publish(x=x, y=y, yaw_rate=yaw_rate)

def stop():
    control.w = control.a = control.s = control.d = control.z = False
    apply_velocity()

def publish_pose(pose):
    PuppyPosePub.publish(
        stance_x=pose['stance_x'], stance_y=pose['stance_y'], x_shift=pose['x_shift'],
        height=pose['height'], roll=pose['roll'], pitch=pose['pitch'], yaw=pose['yaw'],
        run_time=800,
    )

def apply_pose(pose, label):
    stop()
    publish_pose(pose)
    rospy.loginfo('pose: %s', label)

def set_key(key, down):
    k = key.lower()
    if k in POSE_KEYS:
        if not down:
            return
        if k == 'k':
            apply_pose(POSE_SIT_FLAT, 'sit_flat')
        elif k == 'l':
            apply_pose(POSE_SIT_ANGLE, 'sit_angle')
        return
    if k not in MOTION_KEYS:
        return
    attr = k
    if getattr(control, attr) == down:
        return
    setattr(control, attr, down)
    rospy.loginfo('key %s %s', 'down' if down else 'up', k)
    if down and k in 'wasd':
        publish_pose(POSE_WALK)
    apply_velocity()

def feed_network_text(text):
    global network_rx_buffer
    network_rx_buffer += text
    while network_rx_buffer:
        ch = network_rx_buffer[0]
        if ch in '+-':
            if len(network_rx_buffer) < 2:
                break
            down = ch == '+'
            key = network_rx_buffer[1]
            network_rx_buffer = network_rx_buffer[2:]
            set_key(key, down)
            continue
        if ch in '\r\n':
            network_rx_buffer = network_rx_buffer[1:]
            continue
        network_rx_buffer = network_rx_buffer[1:]
        rospy.logwarn('ignored network byte: %s', repr(ch))

def setup_keyboard():
    global stdin_old_settings
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
    if select.select([sys.stdin], [], [], 0)[0]:
        return sys.stdin.read(1)
    return None

def poll_stdin_keys():
    key = read_key()
    if key is None:
        return
    if key in '+-':
        nxt = read_key()
        if nxt is None:
            return
        feed_network_text(key + nxt)

pose_key_held = {'k': False, 'l': False}

def start_pynput_listener():
    from pynput import keyboard

    def on_press(key):
        if getattr(key, 'char', None):
            set_key(key.char, True)

    def on_release(key):
        if getattr(key, 'char', None):
            set_key(key.char, False)

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.daemon = True
    listener.start()
    return listener

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
    rospy.loginfo('TCP listening on %s:%s (+w/-w motion, +k/+l pose)', host, port)

def run_keyboard_loop():
    try:
        start_pynput_listener()
        use_pynput = True
        rospy.loginfo('keyboard: WASD+Z via pynput')
    except ImportError:
        setup_keyboard()
        rospy.loginfo('keyboard: type +w/-w (+k/+l pose)')

    while not rospy.is_shutdown():
        try:
            poll_stdin_keys()
            rospy.sleep(0.05)
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
                    feed_network_text(data.decode('utf-8', errors='ignore'))
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
    publish_pose(POSE_WALK)
    
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
