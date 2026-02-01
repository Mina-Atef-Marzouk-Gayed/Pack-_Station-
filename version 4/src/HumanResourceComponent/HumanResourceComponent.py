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
import random

# SimPy time step (seconds)
SIMPY_DT = 0.01


class HRInternalState:
    """
    Internal human resource state:
    - repair/ refill busy flags
    - simple statistics
    """
    def __init__(self):
        self.repair_busy = False
        self.refill_busy = False
        self.repairs_completed = 0
        self.refills_completed = 0

        # base times in seconds — can be tuned
        self.base_repair_time = 5.0
        self.base_refill_time = 3.0


def compute_repair_time(state: HRInternalState, repair_type: int) -> float:
    """
    Very simple mapping: repair_type changes duration.
    You can tune for each machine type.
    """
    t = state.base_repair_time
    if repair_type == 1:      # robot
        t *= 1.2
    elif repair_type == 2:    # flap unit
        t *= 1.1
    elif repair_type == 3:    # tape
        t *= 1.3
    elif repair_type == 4:    # label
        t *= 1.2
    else:                     # unknown / generic
        t *= 1.0
    # add small randomness
    return t + random.uniform(-0.5, 0.5)


def compute_refill_time(state: HRInternalState, refill_type: int) -> float:
    """
    Simple mapping for refill slot times.
    """
    t = state.base_refill_time
    if refill_type == 1:      # carton
        t *= 1.0
    elif refill_type == 2:    # tape
        t *= 1.1
    elif refill_type == 3:    # label
        t *= 1.1
    else:
        t *= 1.0
    return t + random.uniform(-0.3, 0.3)


def hr_repair_worker(env, component):
    """
    SimPy process:
    Watches hr_repair_request and performs repairs with delay.
    """
    st = component.internal_state
    while True:
        s = component.mySignals

        if s.hr_repair_request and not st.repair_busy:
            st.repair_busy = True
            # compute repair time from type
            duration = compute_repair_time(st, s.hr_repair_type)
            # simulate walking to machine + repairing
            yield env.timeout(duration)
            # send "done" pulse
            component.mySignals.hr_repair_done = 1
            st.repairs_completed += 1
            # keep pulse for one small step
            yield env.timeout(SIMPY_DT)
            component.mySignals.hr_repair_done = 0
            st.repair_busy = False
        else:
            # nothing to do, small wait
            yield env.timeout(SIMPY_DT)


def hr_refill_worker(env, component):
    """
    SimPy process:
    Watches hr_refill_request and performs refills with delay.
    """
    st = component.internal_state
    while True:
        s = component.mySignals

        if s.hr_refill_request and not st.refill_busy:
            st.refill_busy = True
            duration = compute_refill_time(st, s.hr_refill_type)
            yield env.timeout(duration)
            component.mySignals.hr_refill_done = 1
            st.refills_completed += 1
            yield env.timeout(SIMPY_DT)
            component.mySignals.hr_refill_done = 0
            st.refill_busy = False
        else:
            yield env.timeout(SIMPY_DT)
# End of user custom code region. Please don't edit beyond this point.
class HumanResourceComponent:

    def __init__(self, args):
        self.componentId = 3
        self.localHost = args.server_url
        self.domain = args.domain
        self.portNum = 50104
        
        self.simulationStep = 0
        self.stopRequested = 0
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
        # Create SimPy environment and internal HR state
        self.env = simpy.Environment()
        self.internal_state = HRInternalState()

        # Start parallel HR workers
        self.env.process(hr_repair_worker(self.env, self))
        self.env.process(hr_refill_worker(self.env, self))

        # Track last time we synced SimPy with VSI
        self._last_env_target = 0.0
        # End of user custom code region. Please don't edit beyond this point.



    def mainThread(self):
        dSession = vsiCommonPythonApi.connectToServer(self.localHost, self.domain, self.portNum, self.componentId)
        vsiEthernetPythonGateway.initialize(dSession, self.componentId, bytes(srcMacAddress), bytes(srcIpAddress))
        try:
            vsiCommonPythonApi.waitForReset()

            # Start of user custom code region. Please apply edits only within these regions:  After Reset
            # Reset SimPy sync clock on reset
            self._last_env_target = 0.0
            # End of user custom code region. Please don't edit beyond this point.
            self.updateInternalVariables()

            if(vsiCommonPythonApi.isStopRequested()):
                raise Exception("stopRequested")
            self.establishTcpUdpConnection()
            nextExpectedTime = vsiCommonPythonApi.getSimulationTimeInNs()
            while(vsiCommonPythonApi.getSimulationTimeInNs() < self.totalSimulationTime):

                # Start of user custom code region. Please apply edits only within these regions:  Inside the while loop
                # Sync SimPy time with VSI time
                if self.simulationStep > 0:
                    dt_s = float(self.simulationStep) / 1e9
                else:
                    dt_s = 0.0

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
                # Nothing special to do right before sending; SimPy has already updated *_done flags
                # End of user custom code region. Please don't edit beyond this point.

                #Send ethernet packet to PLCComponent
                self.sendEthernetPacketToPLCComponent()

                # Start of user custom code region. Please apply edits only within these regions:  After sending the packet
                st = self.internal_state
                print("  HR internal state:", end=" ")
                print(f"RepairBusy={st.repair_busy}, RefillBusy={st.refill_busy}, "
                      f"Repairs={st.repairs_completed}, Refills={st.refills_completed}")
                # End of user custom code region. Please don't edit beyond this point.

                print("\n+=HumanResourceComponent+=")
                print("  VSI time:", end = " ")
                print(vsiCommonPythonApi.getSimulationTimeInNs(), end = " ")
                print("ns")
                print("  Inputs:")
                print("\thr_repair_request =", end = " ")
                print(self.mySignals.hr_repair_request)
                print("\thr_refill_request =", end = " ")
                print(self.mySignals.hr_refill_request)
                print("\thr_repair_type =", end = " ")
                print(self.mySignals.hr_repair_type)
                print("\thr_refill_type =", end = " ")
                print(self.mySignals.hr_refill_type)
                print("  Outputs:")
                print("\thr_repair_done =", end = " ")
                print(self.mySignals.hr_repair_done)
                print("\thr_refill_done =", end = " ")
                print(self.mySignals.hr_refill_done)
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

            self.mySignals.hr_repair_type, receivedPayload = self.unpackBytes('i', receivedPayload)

            self.mySignals.hr_refill_type, receivedPayload = self.unpackBytes('i', receivedPayload)


        # Start of user custom code region. Please apply edits only within these regions:  Protocol's callback function
        # No extra protocol logic; SimPy workers watch mySignals every step.
        # End of user custom code region. Please don't edit beyond this point.



    def sendEthernetPacketToPLCComponent(self):
        bytesToSend = bytes()

        bytesToSend += self.packBytes('?', self.mySignals.hr_repair_done)

        bytesToSend += self.packBytes('?', self.mySignals.hr_refill_done)

        #Send ethernet packet to PLCComponent
        vsiEthernetPythonGateway.sendEthernetPacket(PLCComponentSocketPortNumber0, bytes(bytesToSend))



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
    # Nothing extra here for now
    # End of user custom code region. Please don't edit beyond this point.

    args = inputArgs.parse_args()
                      
    humanResourceComponent = HumanResourceComponent(args)
    humanResourceComponent.mainThread()



if __name__ == '__main__':
    main()
