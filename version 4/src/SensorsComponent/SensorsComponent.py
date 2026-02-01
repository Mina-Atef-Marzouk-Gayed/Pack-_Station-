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
        # Inputs from PLC
        self.carton_consume_cmd = 0
        self.tape_consume_cmd = 0
        self.label_consume_cmd = 0
        # NEW: PLC command to refill all stocks to 50
        self.refill_stocks_cmd = 0

        # Outputs to PLC
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
        self.loader_pocket_carton_present = 0
        self.box_at_flap = 0
        self.box_at_tape = 0
        self.box_at_label = 0
        self.product_placed_ok = 0
        self.top_flaps_closed_ok = 0
        self.tape_applied_ok = 0
        self.label_applied_ok = 0


srcMacAddress = [0x00, 0x10, 0xAA, 0x00, 0x00, 0x01]
PLCComponentMacAddress = [0x00, 0x10, 0xAA, 0x00, 0x00, 0x02]
srcIpAddress = [10, 10, 0, 1]
PLCComponentIpAddress = [10, 10, 0, 2]

SensorsComponentSocketPortNumber0 = 9001

PLCComponent0 = 0


# Start of user custom code region. Please apply edits only within these regions:  Global Variables & Definitions
import simpy
import random

# thresholds and constants
LOW_THRESHOLD_TAPE = 10
LOW_THRESHOLD_LABEL = 10
MAX_CARTON_STOCK = 50
MAX_TAPE_STOCK = 36
MAX_LABEL_STOCK = 36
CONVEYOR_CAPACITY = 100

# failure model parameters (seconds)
MTBF_ROBOT = 100.0        # mean time between robot failures (for testing)
MTBF_FLAP = 300.0
MTBF_TAPE = 300.0
MTBF_LABEL = 300.0
MTBF_CONVEYOR = 400.0

FAULT_DURATION_ROBOT = 6.0
FAULT_DURATION_FLAP = 5.0
FAULT_DURATION_TAPE = 5.5
FAULT_DURATION_LABEL = 5.5
FAULT_DURATION_CONVEYOR = 7.0
# End of user custom code region. Please don't edit beyond this point.


class SensorsComponent:

    def __init__(self, args):
        self.componentId = 0
        self.localHost = args.server_url
        self.domain = args.domain
        self.portNum = 50101
        
        self.simulationStep = 0
        self.stopRequested = False
        self.totalSimulationTime = 0
        
        self.receivedNumberOfBytes = 0
        self.receivedPayload = []

        self.numberOfPorts = 1
        self.clientPortNum = [0] * self.numberOfPorts
        self.receivedDestPortNumber = 0
        self.receivedSrcPortNumber = 0
        self.expectedNumberOfBytes = 0
        self.mySignals = MySignals()

        # Start of user custom code region. Please apply edits only within these regions:  Constructor

        # Local SimPy environment for sensor behaviour
        self.env = simpy.Environment()

        # internal stock and conveyor counters
        self.carton_stock = float(MAX_CARTON_STOCK)
        self.tape_stock = float(MAX_TAPE_STOCK)
        self.label_stock = float(MAX_LABEL_STOCK)
        self.conveyor_count = 0

        # ---------------- SENSOR PROCESSES ----------------

        def printer_process(env, signals):
            """
            Simulate printer presence:
            - with probability 0.4, printer_present = 1 for ~10s
            - otherwise idle for ~2s
            """
            while True:
                if random.random() < 0.4:
                    signals.printer_present = 1
                    yield env.timeout(10.0)
                    signals.printer_present = 0
                else:
                    yield env.timeout(2.0)

        def stock_flags_process(env, comp, signals):
            """
            Update low/empty flags based on internal stock counters.
            """
            while True:
                signals.carton_blank_empty = 1 if comp.carton_stock <= 0 else 0
                signals.tape_empty = 1 if comp.tape_stock <= 0 else 0
                signals.tape_low = 1 if 0 < comp.tape_stock <= LOW_THRESHOLD_TAPE else 0
                signals.label_empty = 1 if comp.label_stock <= 0 else 0
                signals.label_low = 1 if 0 < comp.label_stock <= LOW_THRESHOLD_LABEL else 0
                yield env.timeout(0.5)

        def conveyor_process(env, comp, signals):
            """
            Update conveyor_full flag from internal counter.
            (You can later hook this to PLC events to change conveyor_count.)
            """
            while True:
                signals.conveyor_full = 1 if comp.conveyor_count >= CONVEYOR_CAPACITY else 0
                yield env.timeout(0.2)

        # --------------- FAILURE PROCESSES ----------------

        def failure_process(env, signals, attr_name, mtbf, fault_duration):
            """
            Random failure generator for one machine.
            - Waits exponentially-distributed time with mean = mtbf.
            - Sets signals.<attr_name> = 1 for ~fault_duration seconds.
            """
            if mtbf <= 0:
                return

            while True:
                wait_time = random.expovariate(1.0 / mtbf)
                yield env.timeout(wait_time)

                setattr(signals, attr_name, 1)

                jitter = random.uniform(-0.5, 0.5)
                down_time = max(0.5, fault_duration + jitter)
                yield env.timeout(down_time)

                setattr(signals, attr_name, 0)

        # start SimPy processes (sensor behaviour)
        self.env.process(printer_process(self.env, self.mySignals))
        self.env.process(stock_flags_process(self.env, self, self.mySignals))
        self.env.process(conveyor_process(self.env, self, self.mySignals))

        # start SimPy failure processes (robot + machines)
        self.env.process(
            failure_process(self.env, self.mySignals,
                            "robot_fault", MTBF_ROBOT, FAULT_DURATION_ROBOT)
        )
        self.env.process(
            failure_process(self.env, self.mySignals,
                            "flap_fault", MTBF_FLAP, FAULT_DURATION_FLAP)
        )
        self.env.process(
            failure_process(self.env, self.mySignals,
                            "tape_sealer_fault", MTBF_TAPE, FAULT_DURATION_TAPE)
        )
        self.env.process(
            failure_process(self.env, self.mySignals,
                            "labeler_fault", MTBF_LABEL, FAULT_DURATION_LABEL)
        )
        self.env.process(
            failure_process(self.env, self.mySignals,
                            "conveyor_fault", MTBF_CONVEYOR, FAULT_DURATION_CONVEYOR)
        )

        # End of user custom code region. Please don't edit beyond this point.



    def mainThread(self):
        dSession = vsiCommonPythonApi.connectToServer(self.localHost, self.domain, self.portNum, self.componentId)
        vsiEthernetPythonGateway.initialize(dSession, self.componentId, bytes(srcMacAddress), bytes(srcIpAddress))
        try:
            vsiCommonPythonApi.waitForReset()

            # Start of user custom code region. Please apply edits only within these regions:  After Reset
            # nothing special needed here for now – SimPy env is already prepared in the constructor
            # End of user custom code region. Please don't edit beyond this point.
            self.updateInternalVariables()

            if(vsiCommonPythonApi.isStopRequested()):
                raise Exception("stopRequested")
            self.establishTcpUdpConnection()
            nextExpectedTime = vsiCommonPythonApi.getSimulationTimeInNs()
            while(vsiCommonPythonApi.getSimulationTimeInNs() < self.totalSimulationTime):

                # Start of user custom code region. Please apply edits only within these regions:  Inside the while loop

                # 1) apply consume commands coming from PLC
                if self.mySignals.carton_consume_cmd:
                    if self.carton_stock > 0.0:
                        self.carton_stock -= 1.0

                if self.mySignals.tape_consume_cmd:
                    if self.tape_stock > 0.0:
                        self.tape_stock -= 1.0

                if self.mySignals.label_consume_cmd:
                    if self.label_stock > 0.0:
                        self.label_stock -= 1.0

                # 2) refill command from PLC / HR: refill only empty stocks back to 50
                if self.mySignals.refill_stocks_cmd:
                    if self.carton_stock <= 0.0:
                        self.carton_stock = float(MAX_CARTON_STOCK)
                    if self.tape_stock <= 0.0:
                        self.tape_stock = float(MAX_TAPE_STOCK)
                    if self.label_stock <= 0.0:
                        self.label_stock = float(MAX_LABEL_STOCK)

                # 3) advance the local SimPy environment according to VSI simulation step
                # simulationStep is in ns – convert to seconds
                if self.simulationStep > 0:
                    dt_sec = float(self.simulationStep) / 1e9
                    self.env.run(until=self.env.now + dt_sec)

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

                receivedData = vsiEthernetPythonGateway.recvEthernetPacket(self.clientPortNum[PLCComponent0])
                if(receivedData[3] != 0):
                    self.decapsulateReceivedData(receivedData)

                # Start of user custom code region. Please apply edits only within these regions:  Before sending the packet
                # nothing extra here – all sensor values are already updated by SimPy processes
                # End of user custom code region. Please don't edit beyond this point.

                #Send ethernet packet to PLCComponent
                self.sendEthernetPacketToPLCComponent()

                # Start of user custom code region. Please apply edits only within these regions:  After sending the packet
                print("\n+=SensorsComponent+=")
                print("  VSI time:", vsiCommonPythonApi.getSimulationTimeInNs(), "ns")
                print("  Stocks: carton=", self.carton_stock,
                      " tape=", self.tape_stock,
                      " label=", self.label_stock)
                print("  Inputs:")
                print("\tcarton_consume_cmd =", self.mySignals.carton_consume_cmd)
                print("\ttape_consume_cmd   =", self.mySignals.tape_consume_cmd)
                print("\tlabel_consume_cmd  =", self.mySignals.label_consume_cmd)
                print("\trefill_stocks_cmd  =", self.mySignals.refill_stocks_cmd)
                print("  Outputs:")
                print("\tprinter_present    =", self.mySignals.printer_present)
                print("\tconveyor_full      =", self.mySignals.conveyor_full)
                print("\tcarton_blank_empty =", self.mySignals.carton_blank_empty)
                print("\ttape_empty         =", self.mySignals.tape_empty)
                print("\tlabel_empty        =", self.mySignals.label_empty)
                print("\ttape_low           =", self.mySignals.tape_low)
                print("\tlabel_low          =", self.mySignals.label_low)
                print("\trobot_fault        =", self.mySignals.robot_fault)
                print("\tflap_fault         =", self.mySignals.flap_fault)
                print("\ttape_sealer_fault  =", self.mySignals.tape_sealer_fault)
                print("\tlabeler_fault      =", self.mySignals.labeler_fault)
                print("\tconveyor_fault     =", self.mySignals.conveyor_fault)
                print("\tloader_pocket_carton_present =", self.mySignals.loader_pocket_carton_present)
                print("\tbox_at_flap           =", self.mySignals.box_at_flap)
                print("\tbox_at_tape           =", self.mySignals.box_at_tape)
                print("\tbox_at_label          =", self.mySignals.box_at_label)
                print("\tproduct_placed_ok     =", self.mySignals.product_placed_ok)
                print("\ttop_flaps_closed_ok   =", self.mySignals.top_flaps_closed_ok)
                print("\ttape_applied_ok       =", self.mySignals.tape_applied_ok)
                print("\tlabel_applied_ok      =", self.mySignals.label_applied_ok)
                print("\n\n")
                # End of user custom code region. Please don't edit beyond this point.

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
                vsiCommonPythonApi.advanceSimulation(self.simulationStep + 1)
            else:
                print(f"An error occurred: {str(e)}")
        except:
            vsiCommonPythonApi.advanceSimulation(self.simulationStep + 1)



    def establishTcpUdpConnection(self):
        if(self.clientPortNum[PLCComponent0] == 0):
            self.clientPortNum[PLCComponent0] = vsiEthernetPythonGateway.tcpListen(SensorsComponentSocketPortNumber0)

        if(self.clientPortNum[PLCComponent0] == 0):
            print("Error: Failed to connect to port: SensorsComponent on TCP port: ") 
            print(SensorsComponentSocketPortNumber0)
            exit()



    def decapsulateReceivedData(self, receivedData):
        self.receivedDestPortNumber = receivedData[0]
        self.receivedSrcPortNumber = receivedData[1]
        self.receivedNumberOfBytes = receivedData[3]
        self.receivedPayload = [0] * (self.receivedNumberOfBytes)

        for i in range(self.receivedNumberOfBytes):
            self.receivedPayload[i] = receivedData[2][i]

        if(self.receivedSrcPortNumber == self.clientPortNum[PLCComponent0]):
            print("Received packet from PLCComponent")
            receivedPayload = bytes(self.receivedPayload)
            self.mySignals.carton_consume_cmd, receivedPayload = self.unpackBytes('?', receivedPayload)
            self.mySignals.tape_consume_cmd,   receivedPayload = self.unpackBytes('?', receivedPayload)
            self.mySignals.label_consume_cmd,  receivedPayload = self.unpackBytes('?', receivedPayload)
            # NEW: refill command from PLC
            self.mySignals.refill_stocks_cmd,  receivedPayload = self.unpackBytes('?', receivedPayload)


    def sendEthernetPacketToPLCComponent(self):
        bytesToSend = bytes()

        bytesToSend += self.packBytes('?', self.mySignals.printer_present)
        bytesToSend += self.packBytes('?', self.mySignals.conveyor_full)
        bytesToSend += self.packBytes('?', self.mySignals.carton_blank_empty)
        bytesToSend += self.packBytes('?', self.mySignals.tape_empty)
        bytesToSend += self.packBytes('?', self.mySignals.label_empty)
        bytesToSend += self.packBytes('?', self.mySignals.tape_low)
        bytesToSend += self.packBytes('?', self.mySignals.label_low)
        bytesToSend += self.packBytes('?', self.mySignals.robot_fault)
        bytesToSend += self.packBytes('?', self.mySignals.flap_fault)
        bytesToSend += self.packBytes('?', self.mySignals.tape_sealer_fault)
        bytesToSend += self.packBytes('?', self.mySignals.labeler_fault)
        bytesToSend += self.packBytes('?', self.mySignals.conveyor_fault)
        bytesToSend += self.packBytes('?', self.mySignals.loader_pocket_carton_present)
        bytesToSend += self.packBytes('?', self.mySignals.box_at_flap)
        bytesToSend += self.packBytes('?', self.mySignals.box_at_tape)
        bytesToSend += self.packBytes('?', self.mySignals.box_at_label)
        bytesToSend += self.packBytes('?', self.mySignals.product_placed_ok)
        bytesToSend += self.packBytes('?', self.mySignals.top_flaps_closed_ok)
        bytesToSend += self.packBytes('?', self.mySignals.tape_applied_ok)
        bytesToSend += self.packBytes('?', self.mySignals.label_applied_ok)

        #Send ethernet packet to PLCComponent
        vsiEthernetPythonGateway.sendEthernetPacket(self.clientPortNum[PLCComponent0], bytes(bytesToSend))

        # Start of user custom code region. Please apply edits only within these regions:  Protocol's callback function
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
    # nothing special here
    # End of user custom code region. Please don't edit beyond this point.

    args = inputArgs.parse_args()
                      
    sensorsComponent = SensorsComponent(args)
    sensorsComponent.mainThread()



if __name__ == '__main__':
    main()
