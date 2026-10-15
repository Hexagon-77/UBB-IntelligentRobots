#! /usr/bin/env python3
import rospy
if __name__ == "__main__":
	rospy.init_node("shakira_node", log_level=rospy.DEBUG)
	rospy.loginfo("Hello")
	rospy.spin()
