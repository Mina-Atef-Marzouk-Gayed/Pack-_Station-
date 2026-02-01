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



srcMacAddress = [0x00, 0x10, 0xAA, 0x00, 0x00, 0x03]
PLCComponentMacAddress = [0x00, 0x10, 0xAA, 0x00, 0x00, 0x02]
srcIpAddress = [10, 10, 0, 3]
PLCComponentIpAddress = [10, 10, 0, 2]

PLCComponentSocketPortNumber0 = 9002

ActuatorsComponent0 = 0


# Start of user custom code region. Please apply edits only within these regions:  Global Variables & Definitions
import simpy

# simple kinematic model for visualization / debugging
AXIS_X_SPEED = 0.3   # “units per second”
AXIS_Z_SPEED = 0.3
ACTUATOR_DT = 0.05   # internal actuator physics step [s]


def clamp(v, vmin=0.0, vmax=1.0):
	return max(vmin, min(vmax, v))


def actuators_physics(env: simpy.Environment, comp: "ActuatorsComponent"):
	"""
	Simple actuator behaviour:
	- moves axis_x_pos / axis_z_pos based on move + dir
	- updates running flags for conveyors / flap / tape / label
	- derives a string tower_state from tower lights
	All of this is *internal* to the Actuators component, PLC is still master.
	"""
	while True:
		s = comp.mySignals

		# --- robot axis X ---
		if s.axis_x_move:
			if s.axis_x_dir > 0:
				comp.axis_x_pos += AXIS_X_SPEED * ACTUATOR_DT
			elif s.axis_x_dir < 0:
				comp.axis_x_pos -= AXIS_X_SPEED * ACTUATOR_DT
		comp.axis_x_pos = clamp(comp.axis_x_pos)

		# --- robot axis Z ---
		if s.axis_z_move:
			if s.axis_z_dir > 0:
				comp.axis_z_pos += AXIS_Z_SPEED * ACTUATOR_DT
			elif s.axis_z_dir < 0:
				comp.axis_z_pos -= AXIS_Z_SPEED * ACTUATOR_DT
		comp.axis_z_pos = clamp(comp.axis_z_pos)

		# --- gripper state (1 = closed / holding) ---
		comp.gripper_closed = bool(s.gripper_cmd)

		# --- machine running flags ---
		comp.carton_conveyor_running = bool(s.carton_conveyor_motor)
		comp.final_conveyor_running = bool(s.final_conveyor_motor)
		comp.flap_unit_running = bool(s.flap_folder_enable)
		comp.tape_unit_running = bool(s.tape_sealer_enable)
		comp.label_unit_running = bool(s.label_unit_enable)

		# --- tower light state (for logs / 3D) ---
		if s.tower_light_red:
			comp.tower_state = "RED"
		elif s.tower_light_yellow:
			comp.tower_state = "YELLOW"
		elif s.tower_light_green:
			comp.tower_state = "GREEN"
		else:
			comp.tower_state = "OFF"

		yield env.timeout(ACTUATOR_DT)
# End of user custom code region. Please don't edit beyond this point.
class ActuatorsComponent:

	def __init__(self, args):
		self.componentId = 2
		self.localHost = args.server_url
		self.domain = args.domain
		self.portNum = 50103
        
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
		# local SimPy env for actuator motion
		self.env = simpy.Environment()
		self._last_env_target = 0.0

		# internal physical state (for logs / 3D)
		self.axis_x_pos = 0.0   # 0..1
		self.axis_z_pos = 0.0   # 0..1
		self.gripper_closed = False

		self.carton_conveyor_running = False
		self.final_conveyor_running = False
		self.flap_unit_running = False
		self.tape_unit_running = False
		self.label_unit_running = False

		self.tower_state = "OFF"

		# start actuator physics process
		self.env.process(actuators_physics(self.env, self))
		# End of user custom code region. Please don't edit beyond this point.



	def mainThread(self):
		dSession = vsiCommonPythonApi.connectToServer(self.localHost, self.domain, self.portNum, self.componentId)
		vsiEthernetPythonGateway.initialize(dSession, self.componentId, bytes(srcMacAddress), bytes(srcIpAddress))
		try:
			vsiCommonPythonApi.waitForReset()

			# Start of user custom code region. Please apply edits only within these regions:  After Reset
			# reset internal motion + sync
			self._last_env_target = 0.0
			self.axis_x_pos = 0.0
			self.axis_z_pos = 0.0
			self.gripper_closed = False
			self.carton_conveyor_running = False
			self.final_conveyor_running = False
			self.flap_unit_running = False
			self.tape_unit_running = False
			self.label_unit_running = False
			self.tower_state = "OFF"
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
				# nothing to send from actuators in this design
				# End of user custom code region. Please don't edit beyond this point.

				# Start of user custom code region. Please apply edits only within these regions:  After sending the packet
				# extended debug: show internal actuator “physical” state
				print("\n+=ActuatorsComponent (physics view)+=")
				print("  axis_x_pos         =", f"{self.axis_x_pos:.2f}")
				print("  axis_z_pos         =", f"{self.axis_z_pos:.2f}")
				print("  gripper_closed     =", self.gripper_closed)
				print("  carton_conv_run    =", self.carton_conveyor_running)
				print("  final_conv_run     =", self.final_conveyor_running)
				print("  flap_unit_running  =", self.flap_unit_running)
				print("  tape_unit_running  =", self.tape_unit_running)
				print("  label_unit_running =", self.label_unit_running)
				print("  tower_state        =", self.tower_state)
				# End of user custom code region. Please don't edit beyond this point.

				print("\n+=ActuatorsComponent+=")
				print("  VSI time:", end = " ")
				print(vsiCommonPythonApi.getSimulationTimeInNs(), end = " ")
				print("ns")
				print("  Inputs:")
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
		if(self.clientPortNum[ActuatorsComponent0] == 0):
			self.clientPortNum[ActuatorsComponent0] = vsiEthernetPythonGateway.tcpConnect(bytes(PLCComponentIpAddress), PLCComponentSocketPortNumber0)

		if(self.clientPortNum[ActuatorsComponent0] == 0):
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
			self.mySignals.axis_x_move, receivedPayload = self.unpackBytes('?', receivedPayload)

			self.mySignals.axis_x_dir, receivedPayload = self.unpackBytes('i', receivedPayload)

			self.mySignals.axis_z_move, receivedPayload = self.unpackBytes('?', receivedPayload)

			self.mySignals.axis_z_dir, receivedPayload = self.unpackBytes('i', receivedPayload)

			self.mySignals.gripper_cmd, receivedPayload = self.unpackBytes('i', receivedPayload)

			self.mySignals.flap_folder_enable, receivedPayload = self.unpackBytes('?', receivedPayload)

			self.mySignals.tape_sealer_enable, receivedPayload = self.unpackBytes('?', receivedPayload)

			self.mySignals.label_unit_enable, receivedPayload = self.unpackBytes('?', receivedPayload)

			self.mySignals.final_conveyor_motor, receivedPayload = self.unpackBytes('?', receivedPayload)

			self.mySignals.carton_erector_enable, receivedPayload = self.unpackBytes('?', receivedPayload)

			self.mySignals.carton_conveyor_motor, receivedPayload = self.unpackBytes('?', receivedPayload)

			self.mySignals.carton_conveyor_stopper, receivedPayload = self.unpackBytes('?', receivedPayload)

			self.mySignals.tower_light_green, receivedPayload = self.unpackBytes('?', receivedPayload)

			self.mySignals.tower_light_yellow, receivedPayload = self.unpackBytes('?', receivedPayload)

			self.mySignals.tower_light_red, receivedPayload = self.unpackBytes('?', receivedPayload)


		# Start of user custom code region. Please apply edits only within these regions:  Protocol's callback function
		# nothing extra here – all physics is handled in the SimPy loop
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
                      
	actuatorsComponent = ActuatorsComponent(args)
	actuatorsComponent.mainThread()



if __name__ == '__main__':
    main()
