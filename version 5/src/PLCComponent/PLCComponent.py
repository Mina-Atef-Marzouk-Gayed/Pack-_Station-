#!/usr/bin/env python3
from __future__ import print_function
import struct
import sys
import argparse
import math

PythonGateways = 'pythonGateways/'
sys.path.append(PythonGateways)

import VsiCommonPythonApi as vsiCommonPythonApi
import VsiTcpUdpPythonGateway as vsiEthernetPythonGateway


class MySignals:
    def __init__(self):
        # Inputs  (FROM Sensors + HR)
        self.printer_present = 0
        self.conveyor_full = 0
        self.carton_blank_empty = 0
        self.tape_empty = 0
        self.label_empty = 0
        self.tape_low = 0
        self.label_low = 0
        self.robot_fault = 0
        self.flap_fault = 0
        self.tape_sealer_fault = 0
        self.labeler_fault = 0
        self.conveyor_fault = 0

        # NEW: box / quality inputs from Sensors
        self.loader_pocket_carton_present = 0
        self.box_at_flap = 0
        self.box_at_tape = 0
        self.box_at_label = 0
        self.product_placed_ok = 0
        self.top_flaps_closed_ok = 0
        self.tape_applied_ok = 0
        self.label_applied_ok = 0

        # HR feedback
        self.hr_repair_done = 0
        self.hr_refill_done = 0

        # Outputs (TO Sensors / Actuators / HR)
        self.carton_consume_cmd = 0
        self.tape_consume_cmd = 0
        self.label_consume_cmd = 0
        # NOTE: refill_stocks_cmd removed – no longer exists in VSI

        self.axis_x_move = 0
        self.axis_x_dir = 0
        self.axis_z_move = 0
        self.axis_z_dir = 0
        self.gripper_cmd = 0
        self.flap_folder_enable = 0
        self.tape_sealer_enable = 0
        self.label_unit_enable = 0
        self.final_conveyor_motor = 0
        self.carton_erector_enable = 0
        self.carton_conveyor_motor = 0
        self.carton_conveyor_stopper = 0
        self.tower_light_green = 0
        self.tower_light_yellow = 0
        self.tower_light_red = 0
        self.hr_repair_request = 0
        self.hr_refill_request = 0
        self.hr_repair_type = 0
        self.hr_refill_type = 0



srcMacAddress = [0x00, 0x10, 0xAA, 0x00, 0x00, 0x02]
SensorsComponentMacAddress = [0x00, 0x10, 0xAA, 0x00, 0x00, 0x01]
ActuatorsComponentMacAddress = [0x00, 0x10, 0xAA, 0x00, 0x00, 0x03]
HumanResourceComponentMacAddress = [0x00, 0x10, 0xAA, 0x00, 0x00, 0x04]
srcIpAddress = [10, 10, 0, 2]
SensorsComponentIpAddress = [10, 10, 0, 1]
ActuatorsComponentIpAddress = [10, 10, 0, 3]
HumanResourceComponentIpAddress = [10, 10, 0, 4]

SensorsComponentSocketPortNumber0 = 9001
PLCComponentSocketPortNumber1 = 9002
PLCComponentSocketPortNumber2 = 9003

PLCComponent0 = 0
ActuatorsComponent1 = 1
HumanResourceComponent2 = 2


# Start of user custom code region. Please apply edits only within these regions:  Global Variables & Definitions
from enum import Enum
import simpy


class StationState(Enum):
    IDLE = 0
    CARTON_TO_POCKET = 1
    ROBOT_LOAD = 2
    FLAP_CLOSE = 3
    TAPE_SEAL = 4
    LABEL_APPLY = 5
    MOVE_OUT = 6
    WAIT_HR_REPAIR = 7
    WAIT_HR_REFILL = 8


def any_fault(sig: MySignals) -> bool:
    return bool(
        sig.robot_fault
        or sig.flap_fault
        or sig.tape_sealer_fault
        or sig.labeler_fault
        or sig.conveyor_fault
    )


def any_stock_empty(sig: MySignals) -> bool:
    return bool(sig.carton_blank_empty or sig.tape_empty or sig.label_empty)


def any_stock_low(sig: MySignals) -> bool:
    # low stock but not completely empty
    return bool(
        (sig.tape_low or sig.label_low) and not any_stock_empty(sig)
    )


KPI_UPDATE_DT = 0.1  # seconds


def kpi_process(env: simpy.Environment, plc: "PLCComponent"):
    """
    SimPy KPI loop:
    - Runs every KPI_UPDATE_DT seconds.
    - Accumulates operational and downtime seconds.
    - Computes availability_percent.
    """
    while True:
        # downtime when waiting on HR or there is any fault
        in_downtime = plc.state in (
            StationState.WAIT_HR_REPAIR,
            StationState.WAIT_HR_REFILL,
        ) or any_fault(plc.mySignals)

        if in_downtime:
            plc.downtime_seconds += KPI_UPDATE_DT
        else:
            plc.operational_time_seconds += KPI_UPDATE_DT

        total = plc.operational_time_seconds + plc.downtime_seconds
        if total > 0:
            plc.availability_percent = (
                plc.operational_time_seconds / total * 100.0
            )

        yield env.timeout(KPI_UPDATE_DT)
# End of user custom code region. Please don't edit beyond this point.
class PLCComponent:

    def __init__(self, args):
        self.componentId = 1
        self.localHost = args.server_url
        self.domain = args.domain
        self.portNum = 50102
        
        self.simulationStep = 0
        self.stopRequested = False
        self.totalSimulationTime = 0
        
        self.receivedNumberOfBytes = 0
        self.receivedPayload = []

        self.numberOfPorts = 3
        self.clientPortNum = [0] * self.numberOfPorts
        self.receivedDestPortNumber = 0
        self.receivedSrcPortNumber = 0
        self.expectedNumberOfBytes = 0
        self.mySignals = MySignals()

        # Start of user custom code region. Please apply edits only within these regions:  Constructor
        # Finite-state machine for one box cycle
        self.state = StationState.IDLE
        self.state_time_s = 0.0  # time spent in current state [s]

        # SimPy environment for KPIs
        self.env = simpy.Environment()
        self._last_env_target = 0.0

        # KPI counters
        self.packages_completed = 0
        self.arm_cycles = 0
        self.total_repairs = 0
        self.total_refills = 0
        self.operational_time_seconds = 0.0
        self.downtime_seconds = 0.0
        self.availability_percent = 0.0

        # Edge tracking for HR done pulses
        self.prev_hr_repair_done = 0
        self.prev_hr_refill_done = 0

        # NEW: flags to know if we raised a repair/refill request in this PLC cycle
        self.requested_repair_this_cycle = False
        self.requested_refill_this_cycle = False

        # Launch KPI SimPy process
        self.env.process(kpi_process(self.env, self))
        # End of user custom code region. Please don't edit beyond this point.



    def mainThread(self):
        dSession = vsiCommonPythonApi.connectToServer(self.localHost, self.domain, self.portNum, self.componentId)
        vsiEthernetPythonGateway.initialize(dSession, self.componentId, bytes(srcMacAddress), bytes(srcIpAddress))
        try:
            vsiCommonPythonApi.waitForReset()

            # Start of user custom code region. Please apply edits only within these regions:  After Reset
            # ensure we start from a clean state
            self.state = StationState.IDLE
            self.state_time_s = 0.0

            # reset SimPy sync
            self._last_env_target = 0.0

            # reset KPI accumulators
            self.packages_completed = 0
            self.arm_cycles = 0
            self.total_repairs = 0
            self.total_refills = 0
            self.operational_time_seconds = 0.0
            self.downtime_seconds = 0.0
            self.availability_percent = 0.0
            self.prev_hr_repair_done = 0
            self.prev_hr_refill_done = 0

            # reset HR-request flags
            self.requested_repair_this_cycle = False
            self.requested_refill_this_cycle = False
            # End of user custom code region. Please don't edit beyond this point.
            self.updateInternalVariables()

            if(vsiCommonPythonApi.isStopRequested()):
                raise Exception("stopRequested")
            self.establishTcpUdpConnection()
            nextExpectedTime = vsiCommonPythonApi.getSimulationTimeInNs()
            while(vsiCommonPythonApi.getSimulationTimeInNs() < self.totalSimulationTime):

                # Start of user custom code region. Please apply edits only within these regions:  Inside the while loop

                # --- advance internal timers from VSI step (ns -> s) ---
                if self.simulationStep > 0:
                    dt_s = float(self.simulationStep) / 1e9
                else:
                    dt_s = 0.0

                # Sync SimPy env time for KPIs with VSI time
                target = self._last_env_target + dt_s
                if target > self.env.now:
                    self.env.run(until=target)
                self._last_env_target = target

                # advance state-local timer
                self.state_time_s += dt_s

                s = self.mySignals

                # reset HR request flags for this iteration
                self.requested_repair_this_cycle = False
                self.requested_refill_this_cycle = False

                # --- count HR completions (rising edge on *_done) ---
                if s.hr_repair_done and not self.prev_hr_repair_done:
                    self.total_repairs += 1
                if s.hr_refill_done and not self.prev_hr_refill_done:
                    self.total_refills += 1

                self.prev_hr_repair_done = 1 if s.hr_repair_done else 0
                self.prev_hr_refill_done = 1 if s.hr_refill_done else 0

                # --- reset "instant" outputs every cycle ---

                # consumptions are one-shot pulses
                s.carton_consume_cmd = 0
                s.tape_consume_cmd = 0
                s.label_consume_cmd = 0
                # refill_stocks_cmd removed

                # motion / actuators default off
                s.axis_x_move = 0
                s.axis_x_dir = 0
                s.axis_z_move = 0
                s.axis_z_dir = 0
                s.gripper_cmd = 0
                s.flap_folder_enable = 0
                s.tape_sealer_enable = 0
                s.label_unit_enable = 0
                s.final_conveyor_motor = 0
                s.carton_erector_enable = 0
                s.carton_conveyor_motor = 0
                s.carton_conveyor_stopper = 0

                # tower light will be set after we know status
                s.tower_light_green = 0
                s.tower_light_yellow = 0
                s.tower_light_red = 0

                fault = any_fault(s)
                stock_empty = any_stock_empty(s)
                stock_low = any_stock_low(s)

                # --- HR / fault handling: repair path ---
                if fault and self.state not in (
                    StationState.WAIT_HR_REPAIR,
                    StationState.WAIT_HR_REFILL,
                ):
                    # pause normal sequence and ask HR to repair
                    s.hr_repair_request = 1
                    self.requested_repair_this_cycle = True
                    # simple encoding: 1 = generic machine fault
                    if s.hr_repair_type == 0:
                        s.hr_repair_type = 1
                    self.state = StationState.WAIT_HR_REPAIR
                    self.state_time_s = 0.0

                # --- HR / stock handling: refill path ---
                if stock_empty and self.state not in (
                    StationState.WAIT_HR_REPAIR,
                    StationState.WAIT_HR_REFILL,
                ):
                    s.hr_refill_request = 1
                    self.requested_refill_this_cycle = True
                    # simple encoding: 1 = generic material refill (later you can map 1,2,3)
                    if s.hr_refill_type == 0:
                        s.hr_refill_type = 1
                    self.state = StationState.WAIT_HR_REFILL
                    self.state_time_s = 0.0

                # --- state machine ---
                if self.state == StationState.WAIT_HR_REPAIR:
                    # everything stopped, wait for HR
                    if s.hr_repair_done:
                        # HR finished, clear request and go idle
                        s.hr_repair_request = 0
                        s.hr_repair_type = 0
                        self.state = StationState.IDLE
                        self.state_time_s = 0.0

                elif self.state == StationState.WAIT_HR_REFILL:
                    # everything stopped, wait for refill
                    if s.hr_refill_done:
                        s.hr_refill_request = 0
                        s.hr_refill_type = 0
                        # NOTE: Sensors now handle stock refill internally
                        self.state = StationState.IDLE
                        self.state_time_s = 0.0

                elif self.state == StationState.IDLE:
                    # nothing moves, wait for new printer and safe conditions
                    if (
                        s.printer_present
                        and not s.conveyor_full
                        and not stock_empty
                        and not fault
                    ):
                        self.state = StationState.CARTON_TO_POCKET
                        self.state_time_s = 0.0

                elif self.state == StationState.CARTON_TO_POCKET:
                    """
                    Bring a new carton to loader pocket.

                    FIXED PHYSICAL LOGIC:
                    - While carton is moving: motor = 1, stopper = 0
                    - When carton is stopped at pocket: motor = 0, stopper = 1
                    - carton_erector_enable is true only during this state
                    - There is NO state where motor == 1 and stopper == 1
                    """

                    s.carton_erector_enable = 1

                    # pulse consume command once at start of state
                    if self.state_time_s < dt_s + 1e-9:
                        s.carton_consume_cmd = 1

                    if self.state_time_s < 0.5:
                        # conveyor running → moving carton to pocket
                        s.carton_conveyor_motor = 1
                        s.carton_conveyor_stopper = 0
                        # loader_pocket_carton_present is now a sensor input

                    else:
                        # carton reached pocket → stop conveyor, set stopper
                        s.carton_conveyor_motor = 0
                        s.carton_conveyor_stopper = 1
                        # presence at pocket given by Sensors

                    if self.state_time_s >= 1.0:
                        # carton is in pocket, go to robot load
                        self.state = StationState.ROBOT_LOAD
                        self.state_time_s = 0.0

                elif self.state == StationState.ROBOT_LOAD:
                    # robot moves printer into carton
                    # we no longer drive loader_pocket_carton_present from PLC

                    # simple phased motion profile
                    if self.state_time_s < 0.5:
                        # move X to printer
                        s.axis_x_move = 1
                        s.axis_x_dir = -1
                    elif self.state_time_s < 1.0:
                        # move Z down
                        s.axis_x_move = 0
                        s.axis_z_move = 1
                        s.axis_z_dir = -1
                    elif self.state_time_s < 1.5:
                        # grip printer
                        s.gripper_cmd = 1
                    elif self.state_time_s < 2.0:
                        # move Z up
                        s.axis_z_move = 1
                        s.axis_z_dir = 1
                    elif self.state_time_s < 2.5:
                        # move X to carton
                        s.axis_x_move = 1
                        s.axis_x_dir = 1
                    elif self.state_time_s < 3.0:
                        # move Z down to place
                        s.axis_z_move = 1
                        s.axis_z_dir = -1
                    elif self.state_time_s < 3.5:
                        # release printer inside carton
                        s.gripper_cmd = 0
                        # product_placed_ok now comes from Sensors

                    if self.state_time_s >= 3.5:
                        # one full arm cycle completed
                        self.arm_cycles += 1
                        self.state = StationState.FLAP_CLOSE
                        self.state_time_s = 0.0

                elif self.state == StationState.FLAP_CLOSE:
                    # box at flap folding unit
                    # box_at_flap, top_flaps_closed_ok now provided by Sensors
                    s.flap_folder_enable = 1

                    if self.state_time_s >= 1.0:
                        self.state = StationState.TAPE_SEAL
                        self.state_time_s = 0.0

                elif self.state == StationState.TAPE_SEAL:
                    # box at tape unit
                    # box_at_tape, tape_applied_ok now from Sensors
                    s.tape_sealer_enable = 1

                    # pulse tape consumption at entry
                    if self.state_time_s < dt_s + 1e-9:
                        s.tape_consume_cmd = 1

                    if self.state_time_s >= 1.0:
                        self.state = StationState.LABEL_APPLY
                        self.state_time_s = 0.0

                elif self.state == StationState.LABEL_APPLY:
                    # box at label unit
                    # box_at_label, label_applied_ok now from Sensors
                    s.label_unit_enable = 1

                    # pulse label consumption at entry
                    if self.state_time_s < dt_s + 1e-9:
                        s.label_consume_cmd = 1

                    if self.state_time_s >= 1.0:
                        self.state = StationState.MOVE_OUT
                        self.state_time_s = 0.0

                elif self.state == StationState.MOVE_OUT:
                    # move box to exit
                    s.final_conveyor_motor = 1
                    # position out-of-station handled by Sensors / downstream

                    if self.state_time_s >= 1.0:
                        # box leaves station → back to idle
                        self.state = StationState.IDLE
                        self.state_time_s = 0.0
                        # count package as completed when it exits final conveyor
                        self.packages_completed += 1

                # --- ensure HR requests look like clean edges to HR component ---
                # if we did NOT raise a new repair request this cycle
                # and we are NOT in WAIT_HR_REPAIR, force signal low
                if not self.requested_repair_this_cycle and self.state != StationState.WAIT_HR_REPAIR:
                    s.hr_repair_request = 0

                # same for refill
                if not self.requested_refill_this_cycle and self.state != StationState.WAIT_HR_REFILL:
                    s.hr_refill_request = 0

                # --- tower light logic ---
                if self.state in (StationState.WAIT_HR_REPAIR, StationState.WAIT_HR_REFILL) or fault:
                    s.tower_light_red = 1
                elif stock_low or s.conveyor_full:
                    s.tower_light_yellow = 1
                else:
                    s.tower_light_green = 1

                # End of user custom code region. Please don't edit beyond this point.

                self.updateInternalVariables()

                if(vsiCommonPythonApi.isStopRequested()):
                    raise Exception("stopRequested")

                if(vsiEthernetPythonGateway.isTerminationOnGoing()):
                    print("Termination is on going")
                    break

                if(vsiEthernetPythonGateway.isTerminated()):
                    print("Application terminated")
                    break

                receivedData = vsiEthernetPythonGateway.recvEthernetPacket(SensorsComponentSocketPortNumber0)
                if(receivedData[3] != 0):
                    self.decapsulateReceivedData(receivedData)

                receivedData = vsiEthernetPythonGateway.recvEthernetPacket(self.clientPortNum[ActuatorsComponent1])
                if(receivedData[3] != 0):
                    self.decapsulateReceivedData(receivedData)

                receivedData = vsiEthernetPythonGateway.recvEthernetPacket(self.clientPortNum[HumanResourceComponent2])
                if(receivedData[3] != 0):
                    self.decapsulateReceivedData(receivedData)

                # Start of user custom code region. Please apply edits only within these regions:  Before sending the packet
                # all decisions already made above; nothing extra here
                # End of user custom code region. Please don't edit beyond this point.

                #Send ethernet packet to SensorsComponent
                self.sendEthernetPacketToSensorsComponent()

                #Send ethernet packet to ActuatorsComponent
                self.sendEthernetPacketToActuatorsComponent()

                #Send ethernet packet to HumanResourceComponent
                self.sendEthernetPacketToHumanResourceComponent()

                # Start of user custom code region. Please apply edits only within these regions:  After sending the packet
                print(f"[KPI] packages_completed={self.packages_completed}, "
                      f"arm_cycles={self.arm_cycles}, "
                      f"repairs={self.total_repairs}, "
                      f"refills={self.total_refills}, "
                      f"operational_time={self.operational_time_seconds:.1f}s, "
                      f"downtime={self.downtime_seconds:.1f}s, "
                      f"availability={self.availability_percent:.1f}%")
                # End of user custom code region. Please don't edit beyond this point.

                print("\n+=PLCComponent+=")
                print("  VSI time:", end = " ")
                print(vsiCommonPythonApi.getSimulationTimeInNs(), end = " ")
                print("ns")
                print("  Inputs:")
                print("\tprinter_present =", end = " ")
                print(self.mySignals.printer_present)
                print("\tconveyor_full =", end = " ")
                print(self.mySignals.conveyor_full)
                print("\tcarton_blank_empty =", end = " ")
                print(self.mySignals.carton_blank_empty)
                print("\ttape_empty =", end = " ")
                print(self.mySignals.tape_empty)
                print("\tlabel_empty =", end = " ")
                print(self.mySignals.label_empty)
                print("\ttape_low =", end = " ")
                print(self.mySignals.tape_low)
                print("\tlabel_low =", end = " ")
                print(self.mySignals.label_low)
                print("\trobot_fault =", end = " ")
                print(self.mySignals.robot_fault)
                print("\tflap_fault =", end = " ")
                print(self.mySignals.flap_fault)
                print("\ttape_sealer_fault =", end = " ")
                print(self.mySignals.tape_sealer_fault)
                print("\tlabeler_fault =", end = " ")
                print(self.mySignals.labeler_fault)
                print("\tconveyor_fault =", end = " ")
                print(self.mySignals.conveyor_fault)
                print("\tloader_pocket_carton_present =", end = " ")
                print(self.mySignals.loader_pocket_carton_present)
                print("\tbox_at_flap =", end = " ")
                print(self.mySignals.box_at_flap)
                print("\tbox_at_tape =", end = " ")
                print(self.mySignals.box_at_tape)
                print("\tbox_at_label =", end = " ")
                print(self.mySignals.box_at_label)
                print("\tproduct_placed_ok =", end = " ")
                print(self.mySignals.product_placed_ok)
                print("\ttop_flaps_closed_ok =", end = " ")
                print(self.mySignals.top_flaps_closed_ok)
                print("\ttape_applied_ok =", end = " ")
                print(self.mySignals.tape_applied_ok)
                print("\tlabel_applied_ok =", end = " ")
                print(self.mySignals.label_applied_ok)
                print("\thr_repair_done =", end = " ")
                print(self.mySignals.hr_repair_done)
                print("\thr_refill_done =", end = " ")
                print(self.mySignals.hr_refill_done)
                print("  Outputs:")
                print("\tcarton_consume_cmd =", end = " ")
                print(self.mySignals.carton_consume_cmd)
                print("\ttape_consume_cmd =", end = " ")
                print(self.mySignals.tape_consume_cmd)
                print("\tlabel_consume_cmd =", end = " ")
                print(self.mySignals.label_consume_cmd)
                print("\taxis_x_move =", end = " ")
                print(self.mySignals.axis_x_move)
                print("\taxis_x_dir =", end = " ")
                print(self.mySignals.axis_x_dir)
                print("\taxis_z_move =", end = " ")
                print(self.mySignals.axis_z_move)
                print("\taxis_z_dir =", end = " ")
                print(self.mySignals.axis_z_dir)
                print("\tgripper_cmd =", end = " ")
                print(self.mySignals.gripper_cmd)
                print("\tflap_folder_enable =", end = " ")
                print(self.mySignals.flap_folder_enable)
                print("\ttape_sealer_enable =", end = " ")
                print(self.mySignals.tape_sealer_enable)
                print("\tlabel_unit_enable =", end = " ")
                print(self.mySignals.label_unit_enable)
                print("\tfinal_conveyor_motor =", end = " ")
                print(self.mySignals.final_conveyor_motor)
                print("\tcarton_erector_enable =", end = " ")
                print(self.mySignals.carton_erector_enable)
                print("\tcarton_conveyor_motor =", end = " ")
                print(self.mySignals.carton_conveyor_motor)
                print("\tcarton_conveyor_stopper =", end = " ")
                print(self.mySignals.carton_conveyor_stopper)
                print("\ttower_light_green =", end = " ")
                print(self.mySignals.tower_light_green)
                print("\ttower_light_yellow =", end = " ")
                print(self.mySignals.tower_light_yellow)
                print("\ttower_light_red =", end = " ")
                print(self.mySignals.tower_light_red)
                print("\thr_repair_request =", end = " ")
                print(self.mySignals.hr_repair_request)
                print("\thr_refill_request =", end = " ")
                print(self.mySignals.hr_refill_request)
                print("\thr_repair_type =", end = " ")
                print(self.mySignals.hr_repair_type)
                print("\thr_refill_type =", end = " ")
                print(self.mySignals.hr_refill_type)
                print("\n\n")

                self.updateInternalVariables()

                if(vsiCommonPythonApi.isStopRequested()):
                    raise Exception("stopRequested")
                nextExpectedTime += self.simulationStep

                if(vsiCommonPythonApi.getSimulationTimeInNs() >= nextExpectedTime):
                    continue

                if(nextExpectedTime > self.totalSimulationTime):
                    remainingTime = self.totalSimulationTime - vsiCommonPythonApi.getSimulationTimeInNs()
                    vsiCommonPythonApi.advanceSimulation(remainingTime)
                    break

                vsiCommonPythonApi.advanceSimulation(nextExpectedTime - vsiCommonPythonApi.getSimulationTimeInNs())

            if(vsiCommonPythonApi.getSimulationTimeInNs() < self.totalSimulationTime):
                vsiEthernetPythonGateway.terminate()
        except Exception as e:
            if str(e) == "stopRequested":
                print("Terminate signal has been received from one of the VSI clients")
                # Advance time with a step that is equal to "simulationStep + 1" so that all other clients
                # receive the terminate packet before terminating this client
                vsiCommonPythonApi.advanceSimulation(self.simulationStep + 1)
            else:
                print(f"An error occurred: {str(e)}")
        except:
            # Advance time with a step that is equal to "simulationStep + 1" so that all other clients
            # receive the terminate packet before terminating this client
            vsiCommonPythonApi.advanceSimulation(self.simulationStep + 1)



    def establishTcpUdpConnection(self):
        if(self.clientPortNum[PLCComponent0] == 0):
            self.clientPortNum[PLCComponent0] = vsiEthernetPythonGateway.tcpConnect(bytes(SensorsComponentIpAddress), SensorsComponentSocketPortNumber0)

        if(self.clientPortNum[ActuatorsComponent1] == 0):
            self.clientPortNum[ActuatorsComponent1] = vsiEthernetPythonGateway.tcpListen(PLCComponentSocketPortNumber1)

        if(self.clientPortNum[HumanResourceComponent2] == 0):
            self.clientPortNum[HumanResourceComponent2] = vsiEthernetPythonGateway.tcpListen(PLCComponentSocketPortNumber2)

        if(self.clientPortNum[HumanResourceComponent2] == 0):
            print("Error: Failed to connect to port: SensorsComponent on TCP port: ") 
            print(SensorsComponentSocketPortNumber0)
            exit()

        if(self.clientPortNum[HumanResourceComponent2] == 0):
            print("Error: Failed to connect to port: PLCComponent on TCP port: ") 
            print(PLCComponentSocketPortNumber1)
            exit()

        if(self.clientPortNum[HumanResourceComponent2] == 0):
            print("Error: Failed to connect to port: PLCComponent on TCP port: ") 
            print(PLCComponentSocketPortNumber2)
            exit()



    def decapsulateReceivedData(self, receivedData):
        self.receivedDestPortNumber = receivedData[0]
        self.receivedSrcPortNumber = receivedData[1]
        self.receivedNumberOfBytes = receivedData[3]
        self.receivedPayload = [0] * (self.receivedNumberOfBytes)

        for i in range(self.receivedNumberOfBytes):
            self.receivedPayload[i] = receivedData[2][i]

        if(self.receivedSrcPortNumber == SensorsComponentSocketPortNumber0):
            print("Received packet from SensorsComponent")
            receivedPayload = bytes(self.receivedPayload)

            self.mySignals.printer_present, receivedPayload = self.unpackBytes('?', receivedPayload)
            self.mySignals.conveyor_full, receivedPayload = self.unpackBytes('?', receivedPayload)
            self.mySignals.carton_blank_empty, receivedPayload = self.unpackBytes('?', receivedPayload)
            self.mySignals.tape_empty, receivedPayload = self.unpackBytes('?', receivedPayload)
            self.mySignals.label_empty, receivedPayload = self.unpackBytes('?', receivedPayload)
            self.mySignals.tape_low, receivedPayload = self.unpackBytes('?', receivedPayload)
            self.mySignals.label_low, receivedPayload = self.unpackBytes('?', receivedPayload)
            self.mySignals.robot_fault, receivedPayload = self.unpackBytes('?', receivedPayload)
            self.mySignals.flap_fault, receivedPayload = self.unpackBytes('?', receivedPayload)
            self.mySignals.tape_sealer_fault, receivedPayload = self.unpackBytes('?', receivedPayload)
            self.mySignals.labeler_fault, receivedPayload = self.unpackBytes('?', receivedPayload)
            self.mySignals.conveyor_fault, receivedPayload = self.unpackBytes('?', receivedPayload)

            # NEW: box/quality inputs from Sensors
            self.mySignals.loader_pocket_carton_present, receivedPayload = self.unpackBytes('?', receivedPayload)
            self.mySignals.box_at_flap, receivedPayload = self.unpackBytes('?', receivedPayload)
            self.mySignals.box_at_tape, receivedPayload = self.unpackBytes('?', receivedPayload)
            self.mySignals.box_at_label, receivedPayload = self.unpackBytes('?', receivedPayload)
            self.mySignals.product_placed_ok, receivedPayload = self.unpackBytes('?', receivedPayload)
            self.mySignals.top_flaps_closed_ok, receivedPayload = self.unpackBytes('?', receivedPayload)
            self.mySignals.tape_applied_ok, receivedPayload = self.unpackBytes('?', receivedPayload)
            self.mySignals.label_applied_ok, receivedPayload = self.unpackBytes('?', receivedPayload)


        if(self.receivedSrcPortNumber == self.clientPortNum[HumanResourceComponent2]):
            print("Received packet from HumanResourceComponent")
            receivedPayload = bytes(self.receivedPayload)
            self.mySignals.hr_repair_done, receivedPayload = self.unpackBytes('?', receivedPayload)
            self.mySignals.hr_refill_done, receivedPayload = self.unpackBytes('?', receivedPayload)


    def sendEthernetPacketToSensorsComponent(self):
        bytesToSend = bytes()

        bytesToSend += self.packBytes('?', self.mySignals.carton_consume_cmd)
        bytesToSend += self.packBytes('?', self.mySignals.tape_consume_cmd)
        bytesToSend += self.packBytes('?', self.mySignals.label_consume_cmd)
        # refill_stocks_cmd removed

        #Send ethernet packet to SensorsComponent
        vsiEthernetPythonGateway.sendEthernetPacket(SensorsComponentSocketPortNumber0, bytes(bytesToSend))

    def sendEthernetPacketToActuatorsComponent(self):
        bytesToSend = bytes()

        bytesToSend += self.packBytes('?', self.mySignals.axis_x_move)
        bytesToSend += self.packBytes('i', self.mySignals.axis_x_dir)
        bytesToSend += self.packBytes('?', self.mySignals.axis_z_move)
        bytesToSend += self.packBytes('i', self.mySignals.axis_z_dir)
        bytesToSend += self.packBytes('i', self.mySignals.gripper_cmd)
        bytesToSend += self.packBytes('?', self.mySignals.flap_folder_enable)
        bytesToSend += self.packBytes('?', self.mySignals.tape_sealer_enable)
        bytesToSend += self.packBytes('?', self.mySignals.label_unit_enable)
        bytesToSend += self.packBytes('?', self.mySignals.final_conveyor_motor)
        bytesToSend += self.packBytes('?', self.mySignals.carton_erector_enable)
        bytesToSend += self.packBytes('?', self.mySignals.carton_conveyor_motor)
        bytesToSend += self.packBytes('?', self.mySignals.carton_conveyor_stopper)
        bytesToSend += self.packBytes('?', self.mySignals.tower_light_green)
        bytesToSend += self.packBytes('?', self.mySignals.tower_light_yellow)
        bytesToSend += self.packBytes('?', self.mySignals.tower_light_red)

        #Send ethernet packet to ActuatorsComponent
        vsiEthernetPythonGateway.sendEthernetPacket(self.clientPortNum[ActuatorsComponent1], bytes(bytesToSend))

    def sendEthernetPacketToHumanResourceComponent(self):
        bytesToSend = bytes()

        bytesToSend += self.packBytes('?', self.mySignals.hr_repair_request)
        bytesToSend += self.packBytes('?', self.mySignals.hr_refill_request)
        bytesToSend += self.packBytes('i', self.mySignals.hr_repair_type)
        bytesToSend += self.packBytes('i', self.mySignals.hr_refill_type)

        #Send ethernet packet to HumanResourceComponent
        vsiEthernetPythonGateway.sendEthernetPacket(self.clientPortNum[HumanResourceComponent2], bytes(bytesToSend))

        # Start of user custom code region. Please apply edits only within these regions:  Protocol's callback function
        # no extra callback logic needed here
        # End of user custom code region. Please don't edit beyond this point.



    def packBytes(self, signalType, signal):
        if isinstance(signal, list):
            if signalType == 's':
                packedData = b''
                for str in signal:
                    str += '\0'
                    str = str.encode('utf-8')
                    packedData += struct.pack(f'={len(str)}s', str)
                return packedData
            else:
                return struct.pack(f'={len(signal)}{signalType}', *signal)
        else:
            if signalType == 's':
                signal += '\0'
                signal = signal.encode('utf-8')
                return struct.pack(f'={len(signal)}s', signal)
            else:
                return struct.pack(f'={signalType}', signal)



    def unpackBytes(self, signalType, packedBytes, signal = ""):
        if isinstance(signal, list):
            if signalType == 's':
                unpackedStrings = [''] * len(signal)
                for i in range(len(signal)):
                    nullCharacterIndex = packedBytes.find(b'\0')
                    if nullCharacterIndex == -1:
                        break
                    unpackedString = struct.unpack(f'={nullCharacterIndex}s', packedBytes[:nullCharacterIndex])[0].decode('utf-8')
                    unpackedStrings[i] = unpackedString
                    packedBytes = packedBytes[nullCharacterIndex + 1:]
                return unpackedStrings, packedBytes
            else:
                unpackedVariable = struct.unpack(f'={len(signal)}{signalType}', packedBytes[:len(signal)*struct.calcsize(f'={signalType}')])
                packedBytes = packedBytes[len(unpackedVariable)*struct.calcsize(f'={signalType}'):]
                return list(unpackedVariable), packedBytes
        elif signalType == 's':
            nullCharacterIndex = packedBytes.find(b'\0')
            unpackedVariable = struct.unpack(f'={nullCharacterIndex}s', packedBytes[:nullCharacterIndex])[0].decode('utf-8')
            packedBytes = packedBytes[nullCharacterIndex + 1:]
            return unpackedVariable, packedBytes
        else:
            numBytes = 0
            if signalType in ['?', 'b', 'B']:
                numBytes = 1
            elif signalType in ['h', 'H']:
                numBytes = 2
            elif signalType in ['f', 'i', 'I', 'L', 'l']:
                numBytes = 4
            elif signalType in ['q', 'Q', 'd']:
                numBytes = 8
            else:
                raise Exception('received an invalid signal type in unpackBytes()')
            unpackedVariable = struct.unpack(f'={signalType}', packedBytes[0:numBytes])[0]
            packedBytes = packedBytes[numBytes:]
            return unpackedVariable, packedBytes

    def updateInternalVariables(self):
        self.totalSimulationTime = vsiCommonPythonApi.getTotalSimulationTime()
        self.stopRequested = vsiCommonPythonApi.isStopRequested()
        self.simulationStep = vsiCommonPythonApi.getSimulationStep()



def main():
    inputArgs = argparse.ArgumentParser(" ")
    inputArgs.add_argument('--domain', metavar='D', default='AF_UNIX', help='Socket domain for connection with the VSI TLM fabric server')
    inputArgs.add_argument('--server-url', metavar='CO', default='localhost', help='server URL of the VSI TLM Fabric Server')

    # Start of user custom code region. Please apply edits only within these regions:  Main method
    # nothing extra here
    # End of user custom code region. Please don't edit beyond this point.

    args = inputArgs.parse_args()
                      
    pLCComponent = PLCComponent(args)
    pLCComponent.mainThread()



if __name__ == '__main__':
    main()
