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
        # Inputs
        self.hr_repair_request = 0
        self.hr_refill_request = 0
        self.hr_repair_type = 0
        self.hr_refill_type = 0

        # Outputs
        self.hr_repair_done = 0
        self.hr_refill_done = 0



srcMacAddress = [0x00, 0x10, 0xAA, 0x00, 0x00, 0x04]
PLCComponentMacAddress = [0x00, 0x10, 0xAA, 0x00, 0x00, 0x02]
srcIpAddress = [10, 10, 0, 4]
PLCComponentIpAddress = [10, 10, 0, 2]

PLCComponentSocketPortNumber0 = 9003

HumanResourceComponent0 = 0


# Start of user custom code region. Please apply edits only within these regions:  Global Variables & Definitions
import simpy

# simple “service times” for HR
# you can tune these if you want
REPAIR_TIME_DEFAULT = 8.0   # seconds to repair a fault
REFILL_TIME_DEFAULT = 5.0   # seconds to refill one stock

class HRState:
    IDLE = 0
    REPAIRING = 1
    REFILLING = 2
# End of user custom code region. Please don't edit beyond this point.
class HumanResourceComponent:

    def __init__(self, args):
        self.componentId = 3
        self.localHost = args.server_url
        self.domain = args.domain
        self.portNum = 50104
        
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
        # local SimPy env to simulate HR walking / working time
        self.env = simpy.Environment()
        self._last_env_target = 0.0

        # current HR state
        self.hr_state = HRState.IDLE

        # edge tracking for requests (rising edges)
        self.prev_repair_req = 0
        self.prev_refill_req = 0

        # start the main HR behaviour process
        self.env.process(self.hr_behavior_process())
        # End of user custom code region. Please don't edit beyond this point.



    def mainThread(self):
        dSession = vsiCommonPythonApi.connectToServer(self.localHost, self.domain, self.portNum, self.componentId)
        vsiEthernetPythonGateway.initialize(dSession, self.componentId, bytes(srcMacAddress), bytes(srcIpAddress))
        try:
            vsiCommonPythonApi.waitForReset()

            # Start of user custom code region. Please apply edits only within these regions:  After Reset
            # reset HR internal state
            self.hr_state = HRState.IDLE
            self._last_env_target = 0.0
            self.prev_repair_req = 0
            self.prev_refill_req = 0
            self.mySignals.hr_repair_done = 0
            self.mySignals.hr_refill_done = 0
            # End of user custom code region. Please don't edit beyond this point.
            self.updateInternalVariables()

            if(vsiCommonPythonApi.isStopRequested()):
                raise Exception("stopRequested")
            self.establishTcpUdpConnection()
            nextExpectedTime = vsiCommonPythonApi.getSimulationTimeInNs()
            while(vsiCommonPythonApi.getSimulationTimeInNs() < self.totalSimulationTime):

                # Start of user custom code region. Please apply edits only within these regions:  Inside the while loop

                # advance SimPy env based on VSI step (ns → s)
                if self.simulationStep > 0:
                    dt_s = float(self.simulationStep) / 1e9
                    target = self._last_env_target + dt_s
                    if target > self.env.now:
                        self.env.run(until=target)
                    self._last_env_target = target
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

                receivedData = vsiEthernetPythonGateway.recvEthernetPacket(PLCComponentSocketPortNumber0)
                if(receivedData[3] != 0):
                    self.decapsulateReceivedData(receivedData)

                # Start of user custom code region. Please apply edits only within these regions:  Before sending the packet
                # nothing extra here – HR logic runs inside SimPy
                # End of user custom code region. Please don't edit beyond this point.

                #Send ethernet packet to PLCComponent
                self.sendEthernetPacketToPLCComponent()

                # Start of user custom code region. Please apply edits only within these regions:  After sending the packet
                print("\n+=HumanResourceComponent+=")
                print("  VSI time:", vsiCommonPythonApi.getSimulationTimeInNs(), "ns")
                print("  Inputs:")
                print("\thr_repair_request =", self.mySignals.hr_repair_request)
                print("\thr_refill_request =", self.mySignals.hr_refill_request)
                print("\thr_repair_type   =", self.mySignals.hr_repair_type)
                print("\thr_refill_type   =", self.mySignals.hr_refill_type)
                print("  Outputs:")
                print("\thr_repair_done   =", self.mySignals.hr_repair_done)
                print("\thr_refill_done   =", self.mySignals.hr_refill_done)
                print("  HR state:", self.hr_state)
                print("\n")
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
        if(self.clientPortNum[HumanResourceComponent0] == 0):
            self.clientPortNum[HumanResourceComponent0] = vsiEthernetPythonGateway.tcpConnect(bytes(PLCComponentIpAddress), PLCComponentSocketPortNumber0)

        if(self.clientPortNum[HumanResourceComponent0] == 0):
            print("Error: Failed to connect to port: PLCComponent on TCP port: ") 
            print(PLCComponentSocketPortNumber0)
            exit()



    def decapsulateReceivedData(self, receivedData):
        self.receivedDestPortNumber = receivedData[0]
        self.receivedSrcPortNumber = receivedData[1]
        self.receivedNumberOfBytes = receivedData[3]
        self.receivedPayload = [0] * (self.receivedNumberOfBytes)

        for i in range(self.receivedNumberOfBytes):
            self.receivedPayload[i] = receivedData[2][i]

        if(self.receivedSrcPortNumber == PLCComponentSocketPortNumber0):
            print("Received packet from PLCComponent")
            receivedPayload = bytes(self.receivedPayload)
            self.mySignals.hr_repair_request, receivedPayload = self.unpackBytes('?', receivedPayload)
            self.mySignals.hr_refill_request, receivedPayload = self.unpackBytes('?', receivedPayload)
            self.mySignals.hr_repair_type,   receivedPayload = self.unpackBytes('i', receivedPayload)
            self.mySignals.hr_refill_type,   receivedPayload = self.unpackBytes('i', receivedPayload)


    def sendEthernetPacketToPLCComponent(self):
        bytesToSend = bytes()

        bytesToSend += self.packBytes('?', self.mySignals.hr_repair_done)
        bytesToSend += self.packBytes('?', self.mySignals.hr_refill_done)

        #Send ethernet packet to PLCComponent
        vsiEthernetPythonGateway.sendEthernetPacket(PLCComponentSocketPortNumber0, bytes(bytesToSend))

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

    # Start of user custom code region. Please apply edits only within these regions:  HR behaviour with SimPy
    def hr_behavior_process(self):
        """
        SimPy process that:
        - watches hr_repair_request / hr_refill_request
        - waits a realistic time
        - then raises hr_repair_done / hr_refill_done (short pulse)
        This is the "simulation of human refill/repair".
        """
        while True:
            # small step
            yield self.env.timeout(0.1)

            s = self.mySignals

            # detect rising edges of requests
            repair_req_edge = s.hr_repair_request and not self.prev_repair_req
            refill_req_edge = s.hr_refill_request and not self.prev_refill_req

            self.prev_repair_req = 1 if s.hr_repair_request else 0
            self.prev_refill_req = 1 if s.hr_refill_request else 0

            # clear done pulses by default (one-shot)
            s.hr_repair_done = 0
            s.hr_refill_done = 0

            # if idle, we can start a new job
            if self.hr_state == HRState.IDLE:
                if repair_req_edge:
                    # start async repair job
                    self.env.process(self._do_repair_job(s.hr_repair_type))
                    self.hr_state = HRState.REPAIRING
                elif refill_req_edge:
                    # start async refill job
                    self.env.process(self._do_refill_job(s.hr_refill_type))
                    self.hr_state = HRState.REFILLING

    def _do_repair_job(self, repair_type: int):
        """
        Simulate a repair job.
        repair_type can later be used to vary time per machine.
        """
        # simple model: one generic time for now
        duration = REPAIR_TIME_DEFAULT
        yield self.env.timeout(duration)

        # send done pulse
        self.mySignals.hr_repair_done = 1

        # keep done high for a short HR tick so PLC can see it
        yield self.env.timeout(0.1)
        self.mySignals.hr_repair_done = 0

        self.hr_state = HRState.IDLE

    def _do_refill_job(self, refill_type: int):
        """
        Simulate a refill job for one material
        (carton OR tape OR label, not all).
        refill_type can encode which material (1,2,3...).
        """
        duration = REFILL_TIME_DEFAULT
        # later you can make:
        # if refill_type == 1: duration = ...
        # elif refill_type == 2: ...
        yield self.env.timeout(duration)

        # send done pulse
        self.mySignals.hr_refill_done = 1

        # keep done high for a short HR tick so PLC can see it
        yield self.env.timeout(0.1)
        self.mySignals.hr_refill_done = 0

        self.hr_state = HRState.IDLE
    # End of user custom code region. Please don't edit beyond this point.



def main():
    inputArgs = argparse.ArgumentParser(" ")
    inputArgs.add_argument('--domain', metavar='D', default='AF_UNIX', help='Socket domain for connection with the VSI TLM fabric server')
    inputArgs.add_argument('--server-url', metavar='CO', default='localhost', help='server URL of the VSI TLM Fabric Server')

    # Start of user custom code region. Please apply edits only within these regions:  Main method

    # End of user custom code region. Please don't edit beyond this point.

    args = inputArgs.parse_args()
                      
    humanResourceComponent = HumanResourceComponent(args)
    humanResourceComponent.mainThread()



if __name__ == '__main__':
    main()
