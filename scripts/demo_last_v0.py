#!/usr/bin/env python
# -*- coding: utf-8 -*-
import rospy
import numpy
from std_msgs.msg import String,Float64
from ur5_kinematics import *
from ur5_pose_get import *
from transfer import *
from trans_methods import *
from sensor_msgs.msg import JointState
from geometry_msgs.msg import TwistStamped
from ur_tool_velocity_sub import *
from urdf_parser_py.urdf import URDF
from pykdl_utils.kdl_parser import kdl_tree_from_urdf_model
from pykdl_utils.kdl_kinematics import KDLKinematics
import serial
import time
import modbus_tk
import modbus_tk.defines as cst
from modbus_tk import modbus_rtu


class UrLineCircle:
    def __init__(self,weights,radius,urdfname,p,Kp,Port):
        self.Port=Port
        self.weights = weights
        self.radius=radius#m
        self.vel = 0.4
        self.ace = 50
        self.cont=50
        self.t=0
        self.theta=-math.pi / 4
        self.tempq=[]
        self.p=p
        self.Kp=Kp
        self.urdfname=urdfname
        # rotating 45 degree with Z aisx
        self.wRb = [math.cos(self.theta), -1*math.sin(self.theta), 0, math.sin(self.theta), math.cos(self.theta), 0, 0, 0,1]
        self.border_length_pub=rospy.Publisher("/uree_border_length_in_cartisian", Float64, queue_size=10)
        self.uree_velocity_q1_pub = rospy.Publisher("/uree_velocity_q1", Float64, queue_size=10)
        self.uree_velocity_q2_pub = rospy.Publisher("uree_velocity_q2", Float64, queue_size=10)
        self.uree_velocity_q3_pub = rospy.Publisher("uree_velocity_q3", Float64, queue_size=10)
        self.uree_velocity_q4_pub = rospy.Publisher("uree_velocity_q4", Float64, queue_size=10)
        self.uree_velocity_q5_pub = rospy.Publisher("uree_velocity_q5", Float64, queue_size=10)
        self.uree_velocity_q6_pub = rospy.Publisher("uree_velocity_q6", Float64, queue_size=10)

        self.uree_world_v_x_pub = rospy.Publisher("/ur_world_frame_ee_v_x", Float64, queue_size=10)
        self.uree_world_v_y_pub = rospy.Publisher("/ur_world_frame_ee_v_y", Float64, queue_size=10)
        self.uree_world_v_z_pub = rospy.Publisher("/ur_world_frame_ee_v_z", Float64, queue_size=10)
        self.jacabian_det_pub = rospy.Publisher("/ur_jacabian_det", Float64, queue_size=10)
        self.jacabian_rank_pub = rospy.Publisher("/ur_jacabian_rank", Float64, queue_size=10)
        #self.io_pub=rospy.Publisher("/io_state", String, queue_size=10)
    def Init_node(self):
        rospy.init_node("move_ur5_circle")
        pub = rospy.Publisher("/ur_driver/URScript", String, queue_size=10)
        return pub
    def get_urobject_ur5kinetmatics(self):
        ur0 = Kinematic()
        return ur0
    def get_jacabian_from_joint(self,jointq):
        #robot = URDF.from_xml_file("/data/ros/ur_ws/src/universal_robot/ur_description/urdf/ur5.urdf")
        robot = URDF.from_xml_file(self.urdfname)
        tree = kdl_tree_from_urdf_model(robot)
        # print tree.getNrOfSegments()
        chain = tree.getChain("base_link", "ee_link")
        # print chain.getNrOfJoints()
        # forwawrd kinematics
        kdl_kin = KDLKinematics(robot, "base_link", "ee_link")
        q=jointq
        #q = [0, 0, 1, 0, 1, 0]
        pose = kdl_kin.forward(q)  # forward kinematics (returns homogeneous 4x4 matrix)
        # print pose
        #print list(pose)
        q0=Kinematic()
        # if flag==1:
        #     q_ik=q0.best_sol_for_other_py( [1.] * 6, 0, q0.Forward(q))
        # else:
        q_ik = kdl_kin.inverse(pose)  # inverse kinematics
        # print "----------iverse-------------------\n", q_ik

        if q_ik is not None:
            pose_sol = kdl_kin.forward(q_ik)  # should equal pose
            print "------------------forward ------------------\n",pose_sol

        J = kdl_kin.jacobian(q)
        #print 'J:', J
        return J,pose

    def caculate_vlocity_by_jocabian_impedance(self,t,Tstar,q_joint_t):
        """

        :return:
        """
        Jacabian_t,pose=self.get_jacabian_from_joint(q_joint_t)
        Jacabian_singularity=numpy.matrix(Jacabian_t).reshape(6,6)+self.p*numpy.eye(6)
        print "Jacabian_t",Jacabian_singularity
        print "tr2delta(numpy.array(Tstar).reshape(4,4),numpy.array(pose).reshape(4,4)).T",tr2delta(numpy.array(Tstar).reshape(4,4),numpy.array(pose).reshape(4,4)).T
        qdot_t=numpy.dot(Jacabian_singularity.I,tr2delta(numpy.array(Tstar).reshape(4,4),numpy.array(pose).reshape(4,4)).T)
        print "qdot_t",self.Kp*t*qdot_t.T
        print "numpy.array(q_joint_t).T",numpy.array(q_joint_t).T
        # jacabian_rank=
        new_q_t_1=numpy.array(q_joint_t).T+self.Kp*t*qdot_t.T

        print "new_q_t1",new_q_t_1
        return new_q_t_1
    def caculate_vlocity_by_jocabian_pinv(self,t,Tstar,q_joint_t):
        """

        :return:
        """
        Jacabian_t,pose=self.get_jacabian_from_joint(q_joint_t)
        Jacabian_plus=numpy.dot(numpy.dot(Jacabian_t.T,Jacabian_t).I,Jacabian_t.T)
        # Jacabian_singularity=numpy.matrix(Jacabian_t).reshape(6,6)+self.p*numpy.eye(6)
        print "Jacabian_plus",Jacabian_plus.reshape(6,6)
        print "tr2delta(numpy.array(Tstar).reshape(4,4),numpy.array(pose).reshape(4,4)).T",tr2delta(numpy.array(Tstar).reshape(4,4),numpy.array(pose).reshape(4,4)).T
        qdot_t=numpy.dot(Jacabian_plus.I,tr2delta(numpy.array(Tstar).reshape(4,4),numpy.array(pose).reshape(4,4)).T)
        print "qdot_t",self.Kp*t*qdot_t.T
        print "numpy.array(q_joint_t).T",numpy.array(q_joint_t).T
        new_q_t_1=numpy.array(q_joint_t).T+self.Kp*1*qdot_t.T

        print "new_q_t1",new_q_t_1
        return new_q_t_1

    def caculate_vlocity_by_jocabian_v1(self, cn, q_joint_t, deltax, flagx, flagy):

        Jacabian_t, pose = self.get_jacabian_from_joint(q_joint_t)
        # Jacabian_plus=numpy.dot(numpy.dot(Jacabian_t.T,Jacabian_t).I,Jacabian_t.T)
        # # Jacabian_singularity=numpy.matrix(Jacabian_t).reshape(6,6)+self.p*numpy.eye(6)
        # print "real time pose x",(pose[0].tolist()[0][3])
        # print "Tstar",Tstar[3],Tstar[3]-(pose[0].tolist()[0][3])
        # print "Jacabian_plus",Jacabian_plus.reshape(6,6)
        # print "tr2delta(numpy.array(Tstar).reshape(4,4),numpy.array(pose).reshape(4,4)).T",tr2delta(numpy.array(Tstar).reshape(4,4),numpy.array(pose).reshape(4,4)).T
        Jacabian_plus = numpy.dot(numpy.dot(Jacabian_t.T, Jacabian_t).I, Jacabian_t.T)
        new_deta_v = numpy.array([[flagx * deltax, flagy * deltax, 0, 0, 0]])



        new_jacabian_t = Jacabian_t[:5, :5]
        print "new_jacabian_t",new_jacabian_t
        jacabian_det = numpy.linalg.det(new_jacabian_t)
        qdot_t = numpy.dot(new_jacabian_t.I, new_deta_v.T).tolist()
        print "qdot_t",qdot_t
        new_qdot_t = numpy.array([[qdot_t[0][0]], [qdot_t[1][0]], [qdot_t[2][0]], [qdot_t[3][0]], [qdot_t[4][0]], [0]])
        print "jacabian_det", type(jacabian_det), jacabian_det
        # qdot_t = numpy.dot(Jacabian_t.I, new_deta_v.T)
        qdot_dot = new_qdot_t.tolist()
        print "qdot_dot", qdot_dot
        self.uree_velocity_q1_pub.publish(qdot_dot[0][0])
        self.uree_velocity_q2_pub.publish(qdot_dot[1][0])
        self.uree_velocity_q3_pub.publish(qdot_dot[2][0])
        self.uree_velocity_q4_pub.publish(qdot_dot[3][0])
        self.uree_velocity_q5_pub.publish(qdot_dot[4][0])
        self.uree_velocity_q6_pub.publish(qdot_dot[5][0])
        if jacabian_det == 0:
            print "jacabian_det-------is zero-------"
        # self.jacabian_rank_pub.publish()
        # print "qdot_t",self.Kp*1*qdot_t.T
        # print "numpy.array(q_joint_t).T",numpy.array(q_joint_t).T
        jacabian_rank = numpy.linalg.matrix_rank(new_jacabian_t)

        self.jacabian_rank_pub.publish(jacabian_rank)
        self.jacabian_det_pub.publish(jacabian_det)

        new_q_t_1 = numpy.array(q_joint_t).T + self.Kp * 1 * new_qdot_t.T

        print "new_q_t1", new_q_t_1
        return new_q_t_1
    def caculate_vlocity_by_jocabian(self,cn,q_joint_t,deltax,flagx,flagy):

        Jacabian_t,pose=self.get_jacabian_from_joint(q_joint_t)
        Jacabian_plus = numpy.dot(numpy.dot(Jacabian_t.T, Jacabian_t).I, Jacabian_t.T)
        new_deta_v=numpy.array([[flagx*deltax,flagy*deltax,0,0,0,0]])

        jacabian_det=numpy.linalg.det(Jacabian_t)

        #print "jacabian_det",type(jacabian_det),jacabian_det
        qdot_t=numpy.dot(Jacabian_t.I,new_deta_v.T)
        qdot_dot=qdot_t.tolist()
        #print "qdot_dot",qdot_dot
        self.uree_velocity_q1_pub.publish(qdot_dot[0][0])
        self.uree_velocity_q2_pub.publish(qdot_dot[1][0])
        self.uree_velocity_q3_pub.publish(qdot_dot[2][0])
        self.uree_velocity_q4_pub.publish(qdot_dot[3][0])
        self.uree_velocity_q5_pub.publish(qdot_dot[4][0])
        self.uree_velocity_q6_pub.publish(qdot_dot[5][0])
        if jacabian_det==0:
            print "jacabian_det-------is zero-------"
        # self.jacabian_rank_pub.publish()
        # print "qdot_t",self.Kp*1*qdot_t.T
        # print "numpy.array(q_joint_t).T",numpy.array(q_joint_t).T
        jacabian_rank=numpy.linalg.matrix_rank(Jacabian_t)

        self.jacabian_rank_pub.publish(jacabian_rank)
        self.jacabian_det_pub.publish(jacabian_det)

        new_q_t_1=numpy.array(q_joint_t).T+self.Kp*1*qdot_t.T

        print "new_q_t1",new_q_t_1
        return new_q_t_1
    def get_draw_circle_xy(self,t,xy_center_pos):
        x = xy_center_pos[0] + self.radius * math.cos( 2 * math.pi * t / self.cont )
        y = xy_center_pos[1] + self.radius * math.sin( 2 * math.pi * t / self.cont)
        return  [x,y]
    def get_draw_line_x(self,transxyz0,transxyz_d):#transxyz[x,y,z]
        xn_1=1*(transxyz_d[0]-transxyz0[0])/self.cont
        return xn_1

    def get_T_translation(self, T):
        trans_x = T[3]
        trans_y = T[7]
        trans_z = T[11]
        return [trans_x, trans_y, trans_z]

    def insert_new_xy(self,T,nx,ny,nz):
        temp=[]
        for i in xrange(16):
            if i==3:
                temp.append(nx)
            elif i==7:
                temp.append(ny)
            elif i == 11:
                temp.append(nz)
            else:
                temp.append(T[i])
        return temp
    def numpyarray_tolist(self,T):
        tt=T.tolist()
        temp=[]
        for i in range(4):
            for j in range(4):
                temp.append(tt[i][j])
        return temp

    def urscript_pub(self, pub, qq, vel, ace, t):

        ss = "movej([" + str(qq[0]) + "," + str(qq[1]) + "," + str(qq[2]) + "," + str(
            qq[3]) + "," + str(qq[4]) + "," + str(qq[5]) + "]," + "a=" + str(ace) + "," + "v=" + str(
            vel) + "," + "t=" + str(t) + ")"
        print("Move UR script:---->:", ss)
            # ss="movej([-0.09577000000000001, -1.7111255555555556, 0.7485411111111111, 0.9948566666666667, 1.330836666666667, 2.3684322222222223], a=1.0, v=1.0,t=5)"
        pub.publish(ss)

    """
        [RwbRbe Rwbtbe
        0          1  ]
        """

    def caculate_world_frame(self, T):
        bRe = tr2r(T)
        bte = transl(T)
        wRb = numpy.array(self.wRb).reshape((3, 3))
        homegeneous_T_part3 = numpy.array([0, 0, 0, 1])
        wRbbRe = numpy.dot(wRb, bRe)
        wRbbte = numpy.dot(wRb, bte)
        new_T_T = numpy.column_stack((wRbbRe, wRbbte))
        new_T = np.row_stack((new_T_T, homegeneous_T_part3))
        last_T = self.numpyarray_tolist(new_T)
        inv_wTb_part = numpy.array([0, 0, 0]).T
        inv_wTb_1 = numpy.column_stack((wRb, inv_wTb_part))
        inv_wTb_2 = np.row_stack((inv_wTb_1, homegeneous_T_part3))
        return last_T, inv_wTb_2

    def move_ee(self,ur5_pub,q_now_t,deltax,cn,flagx,flagy):
        q_new_from_jacabian=self.caculate_vlocity_by_jocabian(cn,q_now_t,deltax,flagx,flagy).tolist()[0]

        self.urscript_pub(ur5_pub, q_new_from_jacabian, self.vel, self.ace, self.t)
        return q_new_from_jacabian

    """
    flag=-1,upward
    flag=1,downward
    cont#负上,正下 77mm/300,每一个数量级相当于向上77/300mm
    """
    """
    flag=-1,anticlockwise
    flag=1,clockwise
    cont## 负逆时针90度/162,相当于每一个数量级，旋转90/162度
    """
    def Move_Upward_Rotaion_Motor(self,flag,cont,controller_num):
        """

        :param flag:
        :param cont:
        :param controller_num: 1,push,2,rotaion,3up and down
        :return:
        """
        logger = modbus_tk.utils.create_logger("console")

        try:
            # Connect to the slave
            master = modbus_rtu.RtuMaster(
                serial.Serial(port=self.Port, baudrate=115200, bytesize=8, parity='O', stopbits=1, xonxoff=0)
            )
            master.set_timeout(5.0)
            master.set_verbose(True)
            logger.info("connected")
            #
            logger.info(master.execute(controller_num, cst.READ_HOLDING_REGISTERS, 0, 8))
            # #change to SigIn SON enable driver
            output_value_0=flag*cont
            output_value_1 = flag * 5000
            logger.info(master.execute(controller_num, cst.WRITE_SINGLE_REGISTER, 3, output_value=1))
            logger.info(master.execute(controller_num, cst.WRITE_SINGLE_REGISTER, 109, output_value=2))
            logger.info(master.execute(controller_num, cst.WRITE_SINGLE_REGISTER, 112, output_value=50))
            logger.info(master.execute(controller_num, cst.WRITE_SINGLE_REGISTER, 117, output_value=1))
            logger.info(master.execute(controller_num, cst.WRITE_SINGLE_REGISTER, 120, output_value=output_value_0))#负上,正下 77mm/300,每一个数量级相当于向上77/300mm
            logger.info(master.execute(controller_num, cst.WRITE_SINGLE_REGISTER, 121, output_value=output_value_1))
            logger.info(master.execute(controller_num, cst.WRITE_SINGLE_REGISTER, 128, output_value=500))
            logger.info(master.execute(controller_num, cst.WRITE_SINGLE_REGISTER, 69, output_value=1024))
            logger.info(master.execute(controller_num, cst.WRITE_SINGLE_REGISTER, 71, output_value=32767))
            time.sleep(0.1)#
            logger.info(master.execute(controller_num, cst.WRITE_SINGLE_REGISTER, 71, output_value=31743))
            logger.info(master.execute(controller_num, cst.READ_HOLDING_REGISTERS, 0, 4))

        except modbus_tk.modbus.ModbusError as exc:
            logger.error("%s- Code=%d", exc, exc.get_exception_code())


    """
    back zero,move rotation and upward moto go back zero
    """
    def Move_Rotation_Upward_Motor(self,ro_flag,up_flag,rotation_cont,upward_cont,controller_num):
        """

        :param ro_flag:
        :param up_flag:
        :param rotation_cont:
        :param upward_cont:
        :param controller_num: [num1_rotation,num2_up]
        :return:
        """
        logger = modbus_tk.utils.create_logger("console")

        try:
            # Connect to the slave
            master = modbus_rtu.RtuMaster(
                serial.Serial(port=self.Port, baudrate=115200, bytesize=8, parity='O', stopbits=1, xonxoff=0)
            )
            master.set_timeout(5.0)
            master.set_verbose(True)
            logger.info("connected")
            #
            # logger.info(master.execute(2, cst.READ_HOLDING_REGISTERS, 0, 8))
            # #change to SigIn SON enable driver
            rotation_output_value_0=ro_flag*rotation_cont
            rotation_output_value_1 = ro_flag * 5000

            upward_output_value_0=up_flag*upward_cont
            upward_output_value_1 = up_flag * 5000

            logger.info(master.execute(controller_num[0], cst.READ_HOLDING_REGISTERS, 0, 8))
            logger.info(master.execute(controller_num[1], cst.READ_HOLDING_REGISTERS, 0, 8))
            #change to SigIn SON enable driver
            logger.info(master.execute(controller_num[0], cst.WRITE_SINGLE_REGISTER, 3, output_value=1))
            logger.info(master.execute(controller_num[1], cst.WRITE_SINGLE_REGISTER, 3, output_value=1))
            logger.info(master.execute(controller_num[0], cst.WRITE_SINGLE_REGISTER, 109, output_value=2))
            logger.info(master.execute(controller_num[1], cst.WRITE_SINGLE_REGISTER, 109, output_value=2))
            logger.info(master.execute(controller_num[0], cst.WRITE_SINGLE_REGISTER, 112, output_value=50))
            logger.info(master.execute(controller_num[1], cst.WRITE_SINGLE_REGISTER, 112, output_value=50))
            logger.info(master.execute(controller_num[0], cst.WRITE_SINGLE_REGISTER, 117, output_value=1))
            logger.info(master.execute(controller_num[1], cst.WRITE_SINGLE_REGISTER, 117, output_value=1))
            logger.info(master.execute(controller_num[0], cst.WRITE_SINGLE_REGISTER, 120, output_value=rotation_output_value_0))#负逆时针
            logger.info(master.execute(controller_num[1], cst.WRITE_SINGLE_REGISTER, 120, output_value=upward_output_value_0))#正的向下,负的向上
            logger.info(master.execute(controller_num[0], cst.WRITE_SINGLE_REGISTER, 121, output_value=rotation_output_value_1))#负逆时针
            logger.info(master.execute(controller_num[1], cst.WRITE_SINGLE_REGISTER, 121, output_value=upward_output_value_1))#正的向下,负的向上
            logger.info(master.execute(controller_num[0], cst.WRITE_SINGLE_REGISTER, 128, output_value=100))
            logger.info(master.execute(controller_num[1], cst.WRITE_SINGLE_REGISTER, 128, output_value=250))#下250,上500
            logger.info(master.execute(controller_num[0], cst.WRITE_SINGLE_REGISTER, 69, output_value=1024))
            logger.info(master.execute(controller_num[1], cst.WRITE_SINGLE_REGISTER, 69, output_value=1024))
            logger.info(master.execute(controller_num[0], cst.WRITE_SINGLE_REGISTER, 71, output_value=32767))
            logger.info(master.execute(controller_num[1], cst.WRITE_SINGLE_REGISTER, 71, output_value=32767))
            time.sleep(2)#4
            logger.info(master.execute(controller_num[0], cst.WRITE_SINGLE_REGISTER, 71, output_value=31743))
            logger.info(master.execute(controller_num[1], cst.WRITE_SINGLE_REGISTER, 71, output_value=31743))
            logger.info(master.execute(controller_num[0], cst.READ_HOLDING_REGISTERS, 0, 4))

        except modbus_tk.modbus.ModbusError as exc:
            logger.error("%s- Code=%d", exc, exc.get_exception_code())
    def control_electric_switch(self,timecnt,serialstring):
        """

        :param timecnt: sleeping time
        :param serialstring: "55C8190000F055":open three motor,"55C8190008F055":open air
        :return:
        """
        cmdstring='rostopic pub /io_state std_msgs/String '+serialstring+' --once'
        os.system(cmdstring)
        time.sleep(timecnt)

    def test_three_motor_serial_port_is_ok(self,Port):
        pass
    def caculate_point2point_line(self,T0,T1):
        """

        :param T0:homegeneors for Point 0 [x,y,z]
        :param T1: homegeneors for Point 1 [x,y,z]
        :return: length
        length:sqrt((x0-x1)^2+(y0-y1)^2+(z0-z1)^2)
        """
        length=math.sqrt((T0[3]-T1[3])**2+(T0[7]-T1[7])**2+(T0[11]-T1[11])**2)
        return length
    def change_angle_to_pi(self,qangle):
        temp = []
        for i in xrange(len(qangle)):
            temp.append(qangle[i] / 180.0 * 3.14)
        return temp
def main():
    t=0
    vel=0.1
    ace=50
    # vel=1.05
    # ace=1.4
    port="/dev/ttyUSB1"
    urdfname = "/data/ros/ur_ws_yue/src/ur5_planning/urdf/ur5.urdf"
    qstart=[-85, -180, 90, -180, -90, 180]

    ratet = 30#1.5
    radius=0.1
    weights = [1.] * 6
    T_list=[]
    p=0.001
    Kp=1
    urc=UrLineCircle(weights,radius,urdfname,p,Kp,port)
    pub=urc.Init_node()
    rate = rospy.Rate(ratet)

    # first step go to initial pos
    qzero = urc.change_angle_to_pi(qstart)
    #qzero = display(getpi(qstart))

    # urc.urscript_pub(pub,q,vel,ace,t)
    # second get T use urkinematics
    urk = urc.get_urobject_ur5kinetmatics()
    F_T = urk.Forward(qzero)
    # ur5_pub=urc.
    # print "F_T", F_T
    TransT = urc.get_T_translation(F_T)

    ur_reader = Urposition()
    ur_sub = rospy.Subscriber("/joint_states", JointState, ur_reader.callback)

    tool0 = UrToolVelocityRead()
    tool_sub = rospy.Subscriber("/tool_velocity", TwistStamped, tool0.Ur_tool_velocity_callback)

    WTe, inv_wTb = urc.caculate_world_frame(numpy.array(F_T).reshape((4, 4)))
    ur0_kinematics=urc.get_urobject_ur5kinetmatics()
    cn=1


    flag_to_zero=1


    go_back_start_flag=0

    num_cnt=210
    #velocity 1/rate*detax*cnt=xt-x0
    #velocity 1/30*detax*250=0.4---->0.135m/s

    flag_up_down=[0,0,0,0,0,0,0]
    flag_left_right=[0,0,0,0,0,0,0]
    temp_joint_q=0
    count_num=[0,0,0,0,0,0,0,0,0]
    flag_for_up_left_motor=[0,0,0,0,0,0,0]

    left_right_gap=4
    up_down_gap=1
    plus_num=0.1
    time_cnt=0.
    count_for_up_ward=0
    close_all_flag=1
    while not rospy.is_shutdown():
        if len(ur_reader.ave_ur_pose)!=0:
            q_now = ur_reader.ave_ur_pose
            """
            go to the largest distance 
            """
            deltax = urc.get_draw_line_x([0, 0, 0], [1.5, 0, 0])
            if close_all_flag==1:
                if flag_to_zero == 1:
                    print cn, "go to the largest distance  -----", q_now
                    urc.move_ee(pub,q_now,deltax,cn,1,0)
                    cn += 1
                    # time.sleep(0.1)
                    urc.border_length_pub.publish(urc.caculate_point2point_line(F_T, ur0_kinematics.Forward(q_now)))
                    if cn == int(urc.cont*2):
                        flag_to_zero = 0
                        flag_left_right[0] = 1#right
                        temp_joint_q=q_now
                        urc.control_electric_switch(0, "55C81900020055")
                        #time.sleep(1.5)
                        cn = 1
                if flag_left_right[0] == 1:
                    print "first move to right -----"
                    # deltax = urc.get_draw_line_x([0.286, 0, 0], [0.5, 0, 0])
                    qq = urc.move_ee(pub,q_now,deltax,cn,-1,0)
                    print cn, "move to right -----", qq
                    cn += 1
                    urc.border_length_pub.publish(
                        urc.caculate_point2point_line(ur0_kinematics.Forward(temp_joint_q), ur0_kinematics.Forward(q_now)))
                    if cn == int((urc.cont)*left_right_gap):
                        flag_up_down[0] = 1#up
                        flag_left_right[0] = 0
                        time.sleep(time_cnt)

                        temp_joint_q=q_now
                        cn = 1
                if flag_up_down[0] == 1:
                    print "first move to down -----"
                    # detay = urc.get_draw_line_x(cn, [-0.45, 0, 0], [0.45, 0, 0])
                    qq = urc.move_ee(pub,q_now,deltax,cn,0,-1)
                    print cn, "first move to down -----", qq
                    cn += 1
                    urc.border_length_pub.publish(urc.caculate_point2point_line(ur0_kinematics.Forward(temp_joint_q), ur0_kinematics.Forward(q_now)))
                    if cn == int((urc.cont)*up_down_gap):
                        flag_up_down[0] = 0
                        flag_left_right[1] = 1#left
                        temp_joint_q=q_now
                        time.sleep(time_cnt)
                        cn = 1
                if flag_left_right[1] == 1:
                    print "first move to right -----"
                    # deltax = urc.get_draw_line_x([0.286, 0, 0], [0.5, 0, 0])
                    qq = urc.move_ee(pub,q_now,deltax,cn,1,0)#left
                    print cn, "move to right -----", qq
                    cn += 1
                    urc.border_length_pub.publish(
                        urc.caculate_point2point_line(ur0_kinematics.Forward(temp_joint_q), ur0_kinematics.Forward(q_now)))
                    if cn == int((urc.cont)*left_right_gap+2.5*(urc.cont)*plus_num):
                        flag_up_down[1] = 1#down
                        flag_left_right[1] = 0
                        time.sleep(time_cnt)
                        go_back_start_flag=1
                        temp_joint_q=q_now
                        cn = 1

                if go_back_start_flag == 1:
                    urc.control_electric_switch(0, "55C8190000F055")  # open electric relay and close eletric switch
                    urc.urscript_pub(pub, qzero, 0.5, 1.4, t)
                    time.sleep(1)
                    cn = 1
                    go_back_start_flag = 0

                    #time.sleep(3)
                    flag_for_up_left_motor[0]=1
                    print "path planning over ------"

                if flag_for_up_left_motor[0]==1:
                    print "Ok-----"
                    count_for_up_ward += 1
                    if count_for_up_ward==4:
                        flag_to_zero = 0
                        close_all_flag=0
                        flag_for_up_left_motor[0] = 0
                        print "everything is ok-----"
                    else:
                        flag_to_zero = 1
                        urc.Move_Upward_Rotaion_Motor(-1, 1500, 3)
                        time.sleep(5)
                        print "upward over ------->"
                        urc.control_electric_switch(0, "55C81900000055")
                        flag_for_up_left_motor[0]=0

            else:
                print "everything is ok-----------Bye-Bye--------------"
        rate.sleep()
if __name__ == '__main__':
        main()