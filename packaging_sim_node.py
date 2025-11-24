import simpy
import random
import sys
import time
import threading
from PyQt5.QtWidgets import (QApplication, QAction, QMessageBox, QToolBar, 
                             QWidget, QVBoxLayout, QLabel, QHBoxLayout,
                             QPushButton, QSlider, QDialog, QTextEdit,
                             QGridLayout, QGroupBox, QProgressBar)
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QColor, QBrush, QFont
from nodeeditor.node_editor_window import NodeEditorWindow
from nodeeditor.node_editor_widget import NodeEditorWidget
from nodeeditor.node_node import Node
from nodeeditor.node_socket import Socket
from nodeeditor.node_scene import Scene
from nodeeditor.node_edge import Edge

# =====================================================
# ----------- Failure Configuration -------------------
# =====================================================

class FailureConfiguration:
    """Centralized failure probability configuration - MAX 3%"""
    def __init__(self):
        self.failure_chances = {
            'product_loader': 2,    # 2% failure chance
            'flap_folding': 1,      # 1% failure chance  
            'tape_sealing': 3,      # 3% failure chance (MAX)
            'label_applicator': 1,  # 1% failure chance
            'conveyor': 0.5         # 0.5% failure chance
        }
    
    def should_fail(self, machine_type):
        """Check if a machine should fail based on its failure chance"""
        chance = self.failure_chances.get(machine_type, 0)
        return random.random() * 100 < chance

# =====================================================
# ----------- Human Resources -------------------------
# =====================================================

class MaintenanceOperator:
    """Human operator that handles machine repairs"""
    def __init__(self, env, name="Maintenance Operator"):
        self.env = env
        self.name = name
        self.available = True
        self.current_task = "IDLE"
        self.repair_queue = []
        self.repair_times = {
            'product_loader': (8, 15),
            'flap_folding': (10, 18),  
            'tape_sealing': (6, 12),
            'label_applicator': (4, 8),
            'conveyor': (3, 6)
        }

    def request_repair(self, machine_type, machine_name):
        return self.env.process(self._handle_repair_request(machine_type, machine_name))

    def _handle_repair_request(self, machine_type, machine_name):
        self.repair_queue.append((machine_type, machine_name))
        
        while not self.available:
            yield self.env.timeout(0.5)
        
        self.available = False
        self.current_task = f"REPAIRING_{machine_type.upper()}"
        
        repair_time_range = self.repair_times.get(machine_type, (5, 10))
        repair_time = random.uniform(repair_time_range[0], repair_time_range[1])
        
        yield self.env.timeout(repair_time)
        
        self.available = True
        self.current_task = "IDLE"
        if (machine_type, machine_name) in self.repair_queue:
            self.repair_queue.remove((machine_type, machine_name))
        
        return True

class MaterialHandler:
    """Human worker that handles material refills when requested"""
    def __init__(self, env, name="Material Handler"):
        self.env = env
        self.name = name
        self.available = True
        self.current_task = "IDLE"
        self.refill_queue = []
        self.refill_times = {
            'tape_refill': (10, 20),    # 10-20 seconds to refill tape
            'label_refill': (8, 15)     # 8-15 seconds to refill labels
        }

    def request_refill(self, material_type, machine_name):
        return self.env.process(self._handle_refill_request(material_type, machine_name))

    def _handle_refill_request(self, material_type, machine_name):
        self.refill_queue.append((material_type, machine_name))
        
        while not self.available:
            yield self.env.timeout(0.5)
        
        self.available = False
        self.current_task = f"REFILLING_{material_type.upper()}"
        
        refill_time_range = self.refill_times.get(material_type, (10, 15))
        refill_time = random.uniform(refill_time_range[0], refill_time_range[1])
        
        yield self.env.timeout(refill_time)
        
        self.available = True
        self.current_task = "IDLE"
        if (material_type, machine_name) in self.refill_queue:
            self.refill_queue.remove((material_type, machine_name))
        
        return True

# =====================================================
# ----------- Industrial Packaging Components ---------
# =====================================================

class CartonPresenceDetector:
    """Industrial photoelectric sensor for carton detection"""
    def __init__(self, env, name):
        self.env = env
        self.name = name
        self.detection_status = "NO_CARTON_DETECTED"
        self.carton_present = False
        self.carton_counter = 0

    def generate_detection_data(self):
        while True:
            if not self.carton_present and random.random() < 0.12:
                self.carton_present = True
                self.carton_counter += 1
                self.detection_status = f"CARTON_{self.carton_counter:03d}_DETECTED"
            elif self.carton_present and random.random() < 0.15:
                self.carton_present = False
                self.detection_status = "NO_CARTON_DETECTED"
            
            yield self.env.timeout(1.0)

class ProductLoadingModule:
    def __init__(self, env, name, failure_config, maintenance_operator):
        self.env = env
        self.name = name
        self.failure_config = failure_config
        self.maintenance_operator = maintenance_operator
        self.operational_state = "MODULE_STANDBY"
        self.display_state = "MODULE_STANDBY"
        self.has_failure = False
        self.failure_message = ""

    def execute_loading_sequence(self, command):
        return self.env.process(self._process_loading_command(command))

    def _handle_failure(self, failure_msg):
        self.has_failure = True
        self.operational_state = "LOADING_FAILED"
        self.display_state = "LOADING_FAILED"
        self.failure_message = failure_msg
        
        repair_success = yield self.maintenance_operator.request_repair('product_loader', self.name)
        
        if repair_success:
            self.has_failure = False
            self.failure_message = ""

    def _process_loading_command(self, command):
        if command == "LOAD_PRODUCT":
            if self.failure_config.should_fail('product_loader'):
                yield from self._handle_failure("PRODUCT LOADER JAMMED")
                return
            
            self.operational_state = "LOADING_IN_PROGRESS"
            self.display_state = "LOADING_IN_PROGRESS"
            
            yield self.env.timeout(1.0)
            if self.failure_config.should_fail('product_loader'):
                yield from self._handle_failure("LOADER MOTOR OVERHEAT")
                return
            
            yield self.env.timeout(2.5)
            self.operational_state = "PRODUCT_LOADED"
            self.display_state = "PRODUCT_LOADED"
            
        elif command == "RESET_MODULE":
            if not self.has_failure:
                self.operational_state = "MODULE_STANDBY"
                self.display_state = "MODULE_STANDBY"

class FlapFoldingModule:
    def __init__(self, env, name, failure_config, maintenance_operator):
        self.env = env
        self.name = name
        self.failure_config = failure_config
        self.maintenance_operator = maintenance_operator
        self.operational_state = "FLAPS_EXTENDED"
        self.display_state = "FLAPS_EXTENDED"
        self.current_operation = "AWAITING_CARTON"
        self.has_failure = False
        self.failure_message = ""
        
        # Flap status tracking
        self.lower_flaps_status = {
            'front': "EXTENDED", 'back': "EXTENDED", 
            'left': "EXTENDED", 'right': "EXTENDED"
        }
        self.upper_flaps_status = {
            'front': "EXTENDED", 'back': "EXTENDED", 
            'left': "EXTENDED", 'right': "EXTENDED"
        }
        self.folding_phase = "AWAITING_START"

    def execute_folding_sequence(self, command):
        return self.env.process(self._process_folding_command(command))

    def _handle_failure(self, failure_msg):
        self.has_failure = True
        self.operational_state = "FOLDING_FAILED"
        self.display_state = "FOLDING_FAILED"
        self.failure_message = failure_msg
        
        repair_success = yield self.maintenance_operator.request_repair('flap_folding', self.name)
        
        if repair_success:
            self.has_failure = False
            self.failure_message = ""

    def _check_for_failure(self):
        return self.failure_config.should_fail('flap_folding')

    def _process_folding_command(self, command):
        if command == "FOLD_FLAPS":
            if self._check_for_failure():
                yield from self._handle_failure("FLAP FOLDING SYSTEM FAILED")
                return
            
            self.operational_state = "FOLDING_IN_PROGRESS"
            self.display_state = "FOLDING_IN_PROGRESS"
            self.folding_phase = "LOWER_PHASE"
            
            # PHASE 1: FOLD LOWER FLAPS (Create Bottom)
            self.current_operation = "FOLDING_LOWER_FLAPS"
            
            # Fold lower flaps in sequence
            lower_flaps = ['front', 'back', 'left', 'right']
            for flap in lower_flaps:
                self.lower_flaps_status[flap] = "FOLDING"
                yield self.env.timeout(0.8)
                if self._check_for_failure():
                    yield from self._handle_failure(f"LOWER_{flap.upper()}_FOLD_FAILED")
                    return
                self.lower_flaps_status[flap] = "FOLDED"
            
            # Bottom compression
            self.current_operation = "COMPRESSING_BOTTOM"
            yield self.env.timeout(1.0)
            
            # PHASE 2: FOLD UPPER FLAPS (Close Top)
            self.folding_phase = "UPPER_PHASE"
            self.current_operation = "FOLDING_UPPER_FLAPS"
            
            # Fold upper flaps in sequence
            upper_flaps = ['front', 'back', 'left', 'right']
            for flap in upper_flaps:
                self.upper_flaps_status[flap] = "FOLDING"
                yield self.env.timeout(0.8)
                if self._check_for_failure():
                    yield from self._handle_failure(f"UPPER_{flap.upper()}_FOLD_FAILED")
                    return
                self.upper_flaps_status[flap] = "FOLDED"
            
            # Final compression
            self.current_operation = "FINAL_COMPRESSION"
            yield self.env.timeout(1.0)
            
            self.operational_state = "ALL_FLAPS_FOLDED"
            self.display_state = "ALL_FLAPS_FOLDED"
            self.folding_phase = "COMPLETE"
            self.current_operation = "SEQUENCE_COMPLETED"
            
        elif command == "RESET_MODULE":
            if not self.has_failure:
                self.operational_state = "FLAPS_EXTENDED"
                self.display_state = "FLAPS_EXTENDED"
                self.current_operation = "AWAITING_CARTON"
                self.folding_phase = "AWAITING_START"
                # Reset all flaps to extended
                for flap in self.lower_flaps_status:
                    self.lower_flaps_status[flap] = "EXTENDED"
                for flap in self.upper_flaps_status:
                    self.upper_flaps_status[flap] = "EXTENDED"

class TapeSealingModule:
    def __init__(self, env, name, failure_config, maintenance_operator, material_handler):
        self.env = env
        self.name = name
        self.failure_config = failure_config
        self.maintenance_operator = maintenance_operator
        self.material_handler = material_handler
        self.operational_state = "SEALER_READY"
        self.display_state = "SEALER_READY"
        self.tape_remaining_meters = 50
        self.has_failure = False
        self.failure_message = ""
        self.need_tape_refill = False
        self.tape_refill_threshold = 10

    def execute_sealing_cycle(self, command):
        return self.env.process(self._process_sealing_command(command))

    def _handle_failure(self, failure_msg):
        self.has_failure = True
        self.operational_state = "SEALING_FAILED"
        self.display_state = "SEALING_FAILED"
        self.failure_message = failure_msg
        
        repair_success = yield self.maintenance_operator.request_repair('tape_sealing', self.name)
        
        if repair_success:
            self.has_failure = False
            self.failure_message = ""

    def _handle_tape_refill(self):
        """Human material handler must manually refill tape"""
        self.need_tape_refill = True
        self.operational_state = "AWAITING_TAPE_REFILL"
        self.display_state = "AWAITING_TAPE_REFILL"
        
        # Request human material handler to refill
        refill_success = yield self.material_handler.request_refill('tape_refill', self.name)
        
        if refill_success:
            self.tape_remaining_meters = 50
            self.need_tape_refill = False
            self.operational_state = "SEALER_READY"
            self.display_state = "SEALER_READY"

    def _process_sealing_command(self, command):
        if command == "SEAL_CARTON":
            # Check if tape is available
            if self.tape_remaining_meters <= 0:
                yield from self._handle_tape_refill()
                return
                
            # Use tape
            if self.failure_config.should_fail('tape_sealing'):
                yield from self._handle_failure("TAPE SEALING FAILED")
                return
            
            self.operational_state = "SEALING_IN_PROGRESS"
            self.display_state = "SEALING_IN_PROGRESS"
            
            yield self.env.timeout(2.0)
            if self.failure_config.should_fail('tape_sealing'):
                yield from self._handle_failure("TAPE JAM DURING SEALING")
                return
            
            yield self.env.timeout(2.0)
            self.tape_remaining_meters -= 1
            self.operational_state = "CARTON_SEALED"
            self.display_state = f"CARTON_SEALED ({self.tape_remaining_meters}m)"
            
        elif command == "RESET_MODULE":
            if not self.has_failure and not self.need_tape_refill:
                self.operational_state = "SEALER_READY"
                self.display_state = "SEALER_READY"

class LabelApplicationModule:
    def __init__(self, env, name, failure_config, maintenance_operator, material_handler):
        self.env = env
        self.name = name
        self.failure_config = failure_config
        self.maintenance_operator = maintenance_operator
        self.material_handler = material_handler
        self.operational_state = "LABELER_READY"
        self.display_state = "LABELER_READY"
        self.labels_remaining_count = 5
        self.has_failure = False
        self.failure_message = ""
        self.need_label_refill = False
        self.label_refill_threshold = 5

    def execute_labeling_cycle(self, command):
        return self.env.process(self._process_labeling_command(command))

    def _handle_failure(self, failure_msg):
        self.has_failure = True
        self.operational_state = "LABELING_FAILED"
        self.display_state = "LABELING_FAILED"
        self.failure_message = failure_msg
        
        repair_success = yield self.maintenance_operator.request_repair('label_applicator', self.name)
        
        if repair_success:
            self.has_failure = False
            self.failure_message = ""

    def _handle_label_refill(self):
        """Human material handler must manually refill labels"""
        self.need_label_refill = True
        self.operational_state = "AWAITING_LABEL_REFILL"
        self.display_state = "AWAITING_LABEL_REFILL"
        
        # Request human material handler to refill
        refill_success = yield self.material_handler.request_refill('label_refill', self.name)
        
        if refill_success:
            self.labels_remaining_count = 5
            self.need_label_refill = False
            self.operational_state = "LABELER_READY"
            self.display_state = "LABELER_READY"

    def _process_labeling_command(self, command):
        if command == "APPLY_LABEL":
            # Check if labels are available
            if self.labels_remaining_count <= 0:
                yield from self._handle_label_refill()
                return
            
            # Use label
            if self.failure_config.should_fail('label_applicator'):
                yield from self._handle_failure("LABEL APPLICATOR FAILED")
                return
            
            self.operational_state = "LABELING_IN_PROGRESS"
            self.display_state = "LABELING_IN_PROGRESS"
            
            yield self.env.timeout(1.25)
            if self.failure_config.should_fail('label_applicator'):
                yield from self._handle_failure("LABEL JAM DURING APPLICATION")
                return
            
            yield self.env.timeout(1.25)
            self.labels_remaining_count -= 1
            self.operational_state = "LABEL_APPLIED"
            self.display_state = f"LABEL_APPLIED ({self.labels_remaining_count})"
            
        elif command == "RESET_MODULE":
            if not self.has_failure and not self.need_label_refill:
                self.operational_state = "LABELER_READY"
                self.display_state = "LABELER_READY"

class ConveyorDriveUnit:
    def __init__(self, env, name, failure_config, maintenance_operator):
        self.env = env
        self.name = name
        self.failure_config = failure_config
        self.maintenance_operator = maintenance_operator
        self.operational_state = "CONVEYOR_STOPPED"
        self.display_state = "CONVEYOR_STOPPED"
        self.has_failure = False
        self.failure_message = ""

    def execute_conveyor_command(self, command):
        return self.env.process(self._process_conveyor_command(command))

    def _handle_failure(self, failure_msg):
        self.has_failure = True
        self.operational_state = "CONVEYOR_FAILED"
        self.display_state = "CONVEYOR_FAILED"
        self.failure_message = failure_msg
        
        repair_success = yield self.maintenance_operator.request_repair('conveyor', self.name)
        
        if repair_success:
            self.has_failure = False
            self.failure_message = ""

    def _process_conveyor_command(self, command):
        if command == "START_CONVEYOR":
            if self.failure_config.should_fail('conveyor'):
                yield from self._handle_failure("CONVEYOR DRIVE FAILED")
                return
            
            self.operational_state = "CONVEYOR_RUNNING"
            self.display_state = "CONVEYOR_RUNNING"
            
            yield self.env.timeout(1.5)
            if self.failure_config.should_fail('conveyor'):
                yield from self._handle_failure("CONVEYOR BELT SLIPPAGE")
                return
            
            yield self.env.timeout(1.5)
            self.operational_state = "CONVEYOR_STOPPED"
            self.display_state = "CONVEYOR_STOPPED"
            
        elif command == "RESET_MODULE":
            if not self.has_failure:
                self.operational_state = "CONVEYOR_STOPPED"
                self.display_state = "CONVEYOR_STOPPED"

# =====================================================
# ----------- Packaging Station Controller ------------
# =====================================================

class PackagingStationController:
    def __init__(self, env):
        self.env = env
        self.station_status = "STATION_IDLE"
        self.total_packages_processed = 0
        self.queued_cartons = 0
        self.work_in_progress_count = 0
        self.completed_packages_count = 0
        self.has_station_failure = False
        self.station_failure_message = ""
        
        # Initialize human resources
        self.failure_config = FailureConfiguration()
        self.maintenance_operator = MaintenanceOperator(env, "Maintenance Operator")
        self.material_handler = MaterialHandler(env, "Material Handler")
        
        # Initialize components with human resources
        self.carton_presence_detector = CartonPresenceDetector(env, "CartonPresenceSensor")
        self.product_loading_module = ProductLoadingModule(env, "ProductLoader", self.failure_config, self.maintenance_operator)
        self.flap_folding_module = FlapFoldingModule(env, "FlapFoldingUnit", self.failure_config, self.maintenance_operator)
        self.tape_sealing_module = TapeSealingModule(env, "TapeSealingSystem", self.failure_config, self.maintenance_operator, self.material_handler)
        self.label_application_module = LabelApplicationModule(env, "LabelApplicator", self.failure_config, self.maintenance_operator, self.material_handler)
        self.conveyor_drive_unit = ConveyorDriveUnit(env, "ConveyorDrive", self.failure_config, self.maintenance_operator)
        
        # Start system processes
        self.env.process(self.carton_presence_detector.generate_detection_data())
        self.env.process(self._packaging_sequence_controller())
        self.env.process(self._production_monitor())

    def _production_monitor(self):
        while True:
            if "DETECTED" in self.carton_presence_detector.detection_status and self.station_status == "STATION_IDLE":
                self.queued_cartons = 1
            else:
                self.queued_cartons = 0
                
            if self.station_status in ["PROCESSING_ACTIVE", "LOADING_PRODUCT", "FOLDING_FLAPS", 
                                     "SEALING_CARTON", "APPLYING_LABEL", "CONVEYOR_OPERATING"]:
                self.work_in_progress_count = 1
            else:
                self.work_in_progress_count = 0
            
            yield self.env.timeout(0.5)

    def _check_for_station_failure(self):
        failed_modules = []
        if self.product_loading_module.has_failure:
            failed_modules.append("Product Loader")
        if self.flap_folding_module.has_failure:
            failed_modules.append("Flap Folding")
        if self.tape_sealing_module.has_failure:
            failed_modules.append("Tape Sealing")
        if self.label_application_module.has_failure:
            failed_modules.append("Label Application")
        if self.conveyor_drive_unit.has_failure:
            failed_modules.append("Conveyor")
            
        if failed_modules:
            self.has_station_failure = True
            self.station_failure_message = f"STATION HALTED: {', '.join(failed_modules)} FAILED"
            self.station_status = "STATION_FAILED"
            return True
        return False

    def _check_for_material_shortage(self):
        if (self.tape_sealing_module.need_tape_refill or 
            self.label_application_module.need_label_refill):
            self.station_status = "AWAITING_MATERIALS"
            return True
        return False

    def _packaging_sequence_controller(self):
        while True:
            if ("DETECTED" in self.carton_presence_detector.detection_status and 
                self.station_status == "STATION_IDLE"):
                self.total_packages_processed += 1
                self.station_status = "PROCESSING_ACTIVE"
                yield self.env.process(self._execute_packaging_workflow())
            
            yield self.env.timeout(0.5)

    def _execute_packaging_workflow(self):
        # Check for material shortages before starting
        if self._check_for_material_shortage():
            while self._check_for_material_shortage():
                yield self.env.timeout(1.0)

        # Step 1: Load product
        self.station_status = "LOADING_PRODUCT"
        yield self.product_loading_module.execute_loading_sequence("LOAD_PRODUCT")
        if self._check_for_station_failure():
            yield from self._handle_station_failure()
            return

        # Step 2: Fold flaps
        self.station_status = "FOLDING_FLAPS"
        yield self.flap_folding_module.execute_folding_sequence("FOLD_FLAPS")
        if self._check_for_station_failure():
            yield from self._handle_station_failure()
            return

        # Step 3: Seal carton
        self.station_status = "SEALING_CARTON"
        yield self.tape_sealing_module.execute_sealing_cycle("SEAL_CARTON")
        if self._check_for_station_failure():
            yield from self._handle_station_failure()
            return

        # Step 4: Apply label
        self.station_status = "APPLYING_LABEL"
        yield self.label_application_module.execute_labeling_cycle("APPLY_LABEL")
        if self._check_for_station_failure():
            yield from self._handle_station_failure()
            return

        # Step 5: Conveyor
        self.station_status = "CONVEYOR_OPERATING"
        yield self.conveyor_drive_unit.execute_conveyor_command("START_CONVEYOR")
        if self._check_for_station_failure():
            yield from self._handle_station_failure()
            return

        # Step 6: Reset
        self.station_status = "RESETTING_STATION"
        yield self.product_loading_module.execute_loading_sequence("RESET_MODULE")
        yield self.flap_folding_module.execute_folding_sequence("RESET_MODULE")
        yield self.tape_sealing_module.execute_sealing_cycle("RESET_MODULE")
        yield self.label_application_module.execute_labeling_cycle("RESET_MODULE")
        yield self.conveyor_drive_unit.execute_conveyor_command("RESET_MODULE")
        
        self.completed_packages_count += 1
        self.station_status = "STATION_IDLE"

    def _handle_station_failure(self):
        while (self.product_loading_module.has_failure or 
               self.flap_folding_module.has_failure or
               self.tape_sealing_module.has_failure or
               self.label_application_module.has_failure or
               self.conveyor_drive_unit.has_failure):
            yield self.env.timeout(1.0)
        
        yield self.env.process(self._reset_station_after_repair())

    def _reset_station_after_repair(self):
        yield self.product_loading_module.execute_loading_sequence("RESET_MODULE")
        yield self.flap_folding_module.execute_folding_sequence("RESET_MODULE")
        yield self.tape_sealing_module.execute_sealing_cycle("RESET_MODULE")
        yield self.label_application_module.execute_labeling_cycle("RESET_MODULE")
        yield self.conveyor_drive_unit.execute_conveyor_command("RESET_MODULE")
        
        self.has_station_failure = False
        self.station_failure_message = ""
        self.station_status = "STATION_IDLE"

# =====================================================
# ----------- Real-time Simulation Engine -------------
# =====================================================

class IndustrialPackagingSimulation:
    def __init__(self):
        self.env = simpy.Environment()
        self.packaging_controller = PackagingStationController(self.env)
        self.simulation_active = False
        self.simulation_speed_factor = 2.0

    def set_simulation_speed(self, speed):
        self.simulation_speed_factor = max(0.5, min(10.0, speed))

    def run_realtime_simulation(self, until=float('inf'), time_step=0.1):
        self.simulation_active = True
        
        simulation_start_time = time.time()
        current_simulation_time = 0
        
        while current_simulation_time < until and self.simulation_active:
            self.env.run(until=current_simulation_time + time_step)
            current_simulation_time += time_step
            
            real_elapsed_time = time.time() - simulation_start_time
            adjusted_simulation_time = real_elapsed_time * self.simulation_speed_factor
            
            if (time_delay := (current_simulation_time - adjusted_simulation_time) / self.simulation_speed_factor) > 0:
                time.sleep(time_delay)
                
        if not self.simulation_active:
            print("🛑 Simulation terminated")

    def stop_simulation(self):
        self.simulation_active = False

# =====================================================
# ----------- Compact SCADA Dashboard -----------------
# =====================================================

class IndustrialSCADADashboard(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Industrial Packaging Station SCADA")
        self.setFixedSize(1000, 700)  # Much more compact size
        
        layout = QVBoxLayout()
        
        # Title
        title = QLabel("🏭 Packaging Station SCADA")
        title.setFont(QFont("Arial", 14, QFont.Bold))
        layout.addWidget(title)
        
        # Main Grid - 2x2 layout
        main_grid = QGridLayout()
        
        # Top Left: System Status
        status_group = QGroupBox("📊 System Status")
        status_layout = QVBoxLayout()
        
        # Speed Control
        speed_layout = QHBoxLayout()
        self.speed_label = QLabel("Speed: 2.0x")
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setMinimum(1)
        self.speed_slider.setMaximum(10)
        self.speed_slider.setValue(4)
        self.speed_slider.valueChanged.connect(self.on_speed_changed)
        speed_layout.addWidget(self.speed_label)
        speed_layout.addWidget(self.speed_slider)
        status_layout.addLayout(speed_layout)
        
        # Station Status
        self.station_status_label = QLabel("Station: STATION_IDLE")
        self.station_status_label.setFont(QFont("Arial", 12, QFont.Bold))
        status_layout.addWidget(self.station_status_label)
        
        # Production Info
        self.packages_label = QLabel("Completed: 0/50")
        self.queued_label = QLabel("Queued: 0")
        status_layout.addWidget(self.packages_label)
        status_layout.addWidget(self.queued_label)
        
        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(50)
        self.progress_bar.setValue(0)
        status_layout.addWidget(self.progress_bar)
        
        status_group.setLayout(status_layout)
        main_grid.addWidget(status_group, 0, 0)
        
        # Top Right: Equipment Status
        equipment_group = QGroupBox("⚙️ Equipment")
        equipment_layout = QVBoxLayout()
        
        self.loader_status = QLabel("📥 Loader: STANDBY")
        self.folder_status = QLabel("🏗️ Folder: STANDBY")
        self.sealer_status = QLabel("📦 Sealer: READY")
        self.labeler_status = QLabel("🏷️ Labeler: READY")
        self.conveyor_status = QLabel("🔄 Conveyor: STOPPED")
        
        equipment_layout.addWidget(self.loader_status)
        equipment_layout.addWidget(self.folder_status)
        equipment_layout.addWidget(self.sealer_status)
        equipment_layout.addWidget(self.labeler_status)
        equipment_layout.addWidget(self.conveyor_status)
        
        # Alerts
        self.alerts_label = QLabel("Alerts: None")
        self.alerts_label.setStyleSheet("color: green; font-weight: bold;")
        equipment_layout.addWidget(self.alerts_label)
        
        equipment_group.setLayout(equipment_layout)
        main_grid.addWidget(equipment_group, 0, 1)
        
        # Bottom Left: Human Resources
        human_group = QGroupBox("👥 Human Resources")
        human_layout = QVBoxLayout()
        
        # Maintenance Operator
        op_layout = QHBoxLayout()
        self.operator_status = QLabel("🔧 Operator:")
        self.operator_task = QLabel("IDLE")
        op_layout.addWidget(self.operator_status)
        op_layout.addWidget(self.operator_task)
        human_layout.addLayout(op_layout)
        
        self.repair_queue = QLabel("Repairs: 0")
        human_layout.addWidget(self.repair_queue)
        
        # Material Handler
        mh_layout = QHBoxLayout()
        self.material_status = QLabel("📦 Handler:")
        self.material_task = QLabel("IDLE")
        mh_layout.addWidget(self.material_status)
        mh_layout.addWidget(self.material_task)
        human_layout.addLayout(mh_layout)
        
        self.refill_queue = QLabel("Refills: 0")
        human_layout.addWidget(self.refill_queue)
        
        human_group.setLayout(human_layout)
        main_grid.addWidget(human_group, 1, 0)
        
        # Bottom Right: Flap Folding & Materials
        process_group = QGroupBox("🏗️ Process & Materials")
        process_layout = QVBoxLayout()
        
        # Flap Folding
        flap_layout = QGridLayout()
        self.folding_phase = QLabel("Phase: AWAITING")
        flap_layout.addWidget(self.folding_phase, 0, 0, 1, 2)
        
        # Lower Flaps
        flap_layout.addWidget(QLabel("🔽 Lower:"), 1, 0, 1, 2)
        self.lower_front = QLabel("Front: EXT")
        self.lower_back = QLabel("Back: EXT")
        self.lower_left = QLabel("Left: EXT")
        self.lower_right = QLabel("Right: EXT")
        flap_layout.addWidget(self.lower_front, 2, 0)
        flap_layout.addWidget(self.lower_back, 2, 1)
        flap_layout.addWidget(self.lower_left, 3, 0)
        flap_layout.addWidget(self.lower_right, 3, 1)
        
        # Upper Flaps
        flap_layout.addWidget(QLabel("🔼 Upper:"), 4, 0, 1, 2)
        self.upper_front = QLabel("Front: EXT")
        self.upper_back = QLabel("Back: EXT")
        self.upper_left = QLabel("Left: EXT")
        self.upper_right = QLabel("Right: EXT")
        flap_layout.addWidget(self.upper_front, 5, 0)
        flap_layout.addWidget(self.upper_back, 5, 1)
        flap_layout.addWidget(self.upper_left, 6, 0)
        flap_layout.addWidget(self.upper_right, 6, 1)
        
        process_layout.addLayout(flap_layout)
        
        # Materials
        materials_layout = QHBoxLayout()
        self.tape_status = QLabel("📦 Tape: 50m")
        self.label_status = QLabel("🏷️ Labels: 5")
        materials_layout.addWidget(self.tape_status)
        materials_layout.addWidget(self.label_status)
        process_layout.addLayout(materials_layout)
        
        process_group.setLayout(process_layout)
        main_grid.addWidget(process_group, 1, 1)
        
        layout.addLayout(main_grid)
        
        # Emergency Stop
        emergency_btn = QPushButton("🛑 EMERGENCY STOP")
        emergency_btn.setStyleSheet("background-color: red; color: white; font-weight: bold; height: 40px;")
        emergency_btn.clicked.connect(self.emergency_stop)
        layout.addWidget(emergency_btn)
        
        self.setLayout(layout)

    def on_speed_changed(self, value):
        speed = value / 2.0
        self.speed_label.setText(f"Speed: {speed:.1f}x")
        if hasattr(self.parent(), 'simulation_manager') and self.parent().simulation_manager:
            self.parent().simulation_manager.sim.set_simulation_speed(speed)

    def update_dashboard(self, controller):
        # System Status Updates
        self.station_status_label.setText(f"Station: {controller.station_status}")
        self.packages_label.setText(f"Completed: {controller.completed_packages_count}/50")
        self.queued_label.setText(f"Queued: {controller.queued_cartons}")
        self.progress_bar.setValue(controller.completed_packages_count)
        
        # Equipment Status
        self.loader_status.setText(f"📥 Loader: {controller.product_loading_module.operational_state}")
        self.folder_status.setText(f"🏗️ Folder: {controller.flap_folding_module.operational_state}")
        self.sealer_status.setText(f"📦 Sealer: {controller.tape_sealing_module.operational_state}")
        self.labeler_status.setText(f"🏷️ Labeler: {controller.label_application_module.operational_state}")
        self.conveyor_status.setText(f"🔄 Conveyor: {controller.conveyor_drive_unit.operational_state}")
        
        # Human Resources
        operator = controller.maintenance_operator
        op_status = "🟢" if operator.available else "🔴"
        self.operator_status.setText(f"🔧 Operator: {op_status}")
        self.operator_task.setText(f"{operator.current_task}")
        self.repair_queue.setText(f"Repairs: {len(operator.repair_queue)}")
        
        material_handler = controller.material_handler
        mh_status = "🟢" if material_handler.available else "🔴"
        self.material_status.setText(f"📦 Handler: {mh_status}")
        self.material_task.setText(f"{material_handler.current_task}")
        self.refill_queue.setText(f"Refills: {len(material_handler.refill_queue)}")
        
        # Flap Folding Process
        flap_module = controller.flap_folding_module
        self.folding_phase.setText(f"Phase: {flap_module.folding_phase}")
        
        # Update flaps with abbreviated status
        self.lower_front.setText(f"Front: {flap_module.lower_flaps_status['front'][:3]}")
        self.lower_back.setText(f"Back: {flap_module.lower_flaps_status['back'][:3]}")
        self.lower_left.setText(f"Left: {flap_module.lower_flaps_status['left'][:3]}")
        self.lower_right.setText(f"Right: {flap_module.lower_flaps_status['right'][:3]}")
        
        self.upper_front.setText(f"Front: {flap_module.upper_flaps_status['front'][:3]}")
        self.upper_back.setText(f"Back: {flap_module.upper_flaps_status['back'][:3]}")
        self.upper_left.setText(f"Left: {flap_module.upper_flaps_status['left'][:3]}")
        self.upper_right.setText(f"Right: {flap_module.upper_flaps_status['right'][:3]}")
        
        # Color code flap status
        self._color_code_flaps(flap_module)
        
        # Materials
        tape_module = controller.tape_sealing_module
        label_module = controller.label_application_module
        
        self.tape_status.setText(f"📦 Tape: {tape_module.tape_remaining_meters}m")
        self.label_status.setText(f"🏷️ Labels: {label_module.labels_remaining_count}")
        
        # Update alerts
        self._update_alerts(controller)

    def _color_code_flaps(self, flap_module):
        flaps = [
            (self.lower_front, flap_module.lower_flaps_status['front']),
            (self.lower_back, flap_module.lower_flaps_status['back']),
            (self.lower_left, flap_module.lower_flaps_status['left']),
            (self.lower_right, flap_module.lower_flaps_status['right']),
            (self.upper_front, flap_module.upper_flaps_status['front']),
            (self.upper_back, flap_module.upper_flaps_status['back']),
            (self.upper_left, flap_module.upper_flaps_status['left']),
            (self.upper_right, flap_module.upper_flaps_status['right'])
        ]
        
        for label, status in flaps:
            if status == "FOLDING":
                label.setStyleSheet("color: orange; font-weight: bold;")
            elif status == "FOLDED":
                label.setStyleSheet("color: green; font-weight: bold;")
            elif status == "EXTENDED":
                label.setStyleSheet("color: blue;")
            else:
                label.setStyleSheet("color: black;")

    def _update_alerts(self, controller):
        alerts = []
        
        # Check for failures
        if controller.product_loading_module.has_failure:
            alerts.append("Loader")
        if controller.flap_folding_module.has_failure:
            alerts.append("Folder")
        if controller.tape_sealing_module.has_failure:
            alerts.append("Sealer")
        if controller.label_application_module.has_failure:
            alerts.append("Labeler")
        if controller.conveyor_drive_unit.has_failure:
            alerts.append("Conveyor")
            
        # Check for material shortages
        if controller.tape_sealing_module.need_tape_refill:
            alerts.append("Tape")
        if controller.label_application_module.need_label_refill:
            alerts.append("Labels")
            
        if alerts:
            self.alerts_label.setText(f"Alerts: {', '.join(alerts)}")
            self.alerts_label.setStyleSheet("color: red; font-weight: bold;")
        else:
            self.alerts_label.setText("Alerts: None")
            self.alerts_label.setStyleSheet("color: green; font-weight: bold;")

    def emergency_stop(self):
        if hasattr(self.parent(), 'simulation_manager') and self.parent().simulation_manager:
            self.parent().simulation_manager.sim.stop_simulation()
        self.close()

# =====================================================
# ----------- Node Editor Visualization ---------------
# =====================================================

class FixedNode(Node):
    def __init__(self, scene, title="Undefined Node"):
        super().__init__(scene, title)
        self.grNode.width = 180
        self.grNode.height = 120
        self.grNode.edge_padding = 8
        self.grNode.edge_roundness = 10
        
        if hasattr(self, 'content') and self.content is not None:
            self.content.hide()
        self.grNode.update()

class InputNode(FixedNode):
    def __init__(self, scene, input_name):
        super().__init__(scene, f"Input\n{input_name}")
        self.output_socket = Socket(node=self, index=0, position=2, socket_type=1)
        self.input_name = input_name
        self.value = "UNKNOWN"
        self.update_display()
        
    def update_display(self, value=None):
        if value is not None:
            self.value = value
        display_value = str(self.value)[:15]
        self.grNode.title = f"Input\n{self.input_name}\n{display_value}"
        self.grNode.update()

class MachineNode(FixedNode):
    def __init__(self, scene, machine_name):
        super().__init__(scene, f"Machine\n{machine_name}")
        self.input_socket = Socket(node=self, index=0, position=1, socket_type=1)
        self.output_socket = Socket(node=self, index=1, position=2, socket_type=1)
        self.machine_name = machine_name
        self.status = "IDLE"
        self.package_count = 0
        self.update_display()
        
    def update_display(self, status=None, package_count=None):
        if status is not None:
            self.status = status
        if package_count is not None:
            self.package_count = package_count
        self.grNode.title = f"Machine\n{self.machine_name}\n{self.status}\nPkgs: {self.package_count}"
        self.grNode.update()

class OutputNode(FixedNode):
    def __init__(self, scene, output_name):
        super().__init__(scene, f"Output\n{output_name}")
        self.input_socket = Socket(node=self, index=0, position=1, socket_type=1)
        self.output_name = output_name
        self.state = "OFF"
        self.update_display()
        
    def update_display(self, state=None):
        if state is not None:
            self.state = state
            
        if self.state in ["PRODUCT_LOADED", "ALL_FLAPS_FOLDED", "CARTON_SEALED", "LABEL_APPLIED", "CONVEYOR_RUNNING"]:
            color = "#4CAF50"  # Green
        elif self.state in ["MODULE_STANDBY", "FLAPS_EXTENDED", "SEALER_READY", "LABELER_READY", "CONVEYOR_STOPPED"]:
            color = "#B71C1C"  # Red
        elif self.state in ["LOADING_IN_PROGRESS", "FOLDING_IN_PROGRESS", "SEALING_IN_PROGRESS", "LABELING_IN_PROGRESS"]:
            color = "#FF9800"  # Orange
        elif "FAILED" in self.state:
            color = "#FF0000"  # Bright Red
        elif "AWAITING" in self.state or "REFILL" in self.state:
            color = "#FF5722"  # Deep Orange
        else:
            color = "#2196F3"  # Blue
            
        self.grNode._brush_title = QBrush(QColor(color))
        display_state = str(self.state)[:15]
        self.grNode.title = f"Output\n{self.output_name}\n{display_state}"
        self.grNode.update()

class SimulationManager:
    def __init__(self, editor_wnd):
        self.wnd = editor_wnd
        self.scene = editor_wnd.scene
        self.sim = IndustrialPackagingSimulation()
        self.scada_dashboard = None

    def start_simulation(self):
        thread = threading.Thread(target=self.sim.run_realtime_simulation, daemon=True)
        thread.start()

class PackagingNodeEditor(NodeEditorWindow):
    def initUI(self):
        super().initUI()
        self.setWindowTitle("Industrial Packaging Station SCADA System")
        self.setGeometry(100, 100, 1200, 700)

        self.scene = Scene()
        self.editor = NodeEditorWidget(parent=self)
        self.editor.scene = self.scene
        self.editor.grScene = self.scene.grScene
        view = self.editor.view
        view.setScene(self.scene.grScene)
        self.setCentralWidget(view)

        toolbar = QToolBar("Industrial Packaging Controls")
        self.addToolBar(toolbar)
        
        run_sim = QAction("▶ Start Simulation", self)
        run_sim.triggered.connect(self.start_simulation)
        toolbar.addAction(run_sim)
        
        scada_btn = QAction("📊 SCADA Dashboard", self)
        scada_btn.triggered.connect(self.show_scada_dashboard)
        toolbar.addAction(scada_btn)
        
        stop_sim = QAction("⏹ Stop Simulation", self)
        stop_sim.triggered.connect(self.stop_simulation)
        toolbar.addAction(stop_sim)

        self.create_packaging_nodes()
        self.create_correct_connections()
        
        self.sim_manager = None
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_node_states)
        self.scada_timer = QTimer()
        self.scada_timer.timeout.connect(self.update_scada_dashboard)

    def create_packaging_nodes(self):
        self.carton_presence_node = InputNode(self.scene, "CartonPresenceSensor")
        self.carton_presence_node.setPos(-400, 0)

        self.machine_node = MachineNode(self.scene, "PackagingController")
        self.machine_node.setPos(-150, 0)

        self.loader_output = OutputNode(self.scene, "ProductLoader")
        self.loader_output.setPos(100, -200)
        
        self.folder_output = OutputNode(self.scene, "FlapFoldingUnit")
        self.folder_output.setPos(100, -100)
        
        self.sealer_output = OutputNode(self.scene, "TapeSealingSystem")
        self.sealer_output.setPos(100, 0)
        
        self.labeler_output = OutputNode(self.scene, "LabelApplicator")
        self.labeler_output.setPos(100, 100)
        
        self.conveyor_output = OutputNode(self.scene, "ConveyorDrive")
        self.conveyor_output.setPos(100, 200)

    def create_correct_connections(self):
        try:
            self._connect_nodes(self.carton_presence_node.output_socket, self.machine_node.input_socket)
            self._connect_nodes(self.machine_node.output_socket, self.loader_output.input_socket)
            self._connect_nodes(self.machine_node.output_socket, self.folder_output.input_socket)
            self._connect_nodes(self.machine_node.output_socket, self.sealer_output.input_socket)
            self._connect_nodes(self.machine_node.output_socket, self.labeler_output.input_socket)
            self._connect_nodes(self.machine_node.output_socket, self.conveyor_output.input_socket)
            
            print("🔗 INDUSTRIAL ARCHITECTURE: Sensor → Controller → Actuators")
            print("🔧 FAILURE SYSTEM (MAX 3%): 2% Loader, 1% Folder, 3% Sealer, 1% Labeler, 0.5% Conveyor")
            print("👥 HUMAN RESOURCES: Maintenance Operator + Material Handler")
            print("🏗️ FLAP FOLDING: Lower flaps first → Upper flaps second")
            print("📊 SCADA: Compact single screen dashboard")
            
        except Exception as e:
            print(f"⚠️ Error creating connections: {e}")

    def _connect_nodes(self, start_socket, end_socket):
        try:
            edge = Edge(self.scene, start_socket, end_socket)
            return edge
        except Exception as e:
            print(f"⚠️ Connection failed: {e}")
            return None

    def show_scada_dashboard(self):
        if not hasattr(self, 'scada_dashboard') or not self.scada_dashboard:
            self.scada_dashboard = IndustrialSCADADashboard(self)
        self.scada_dashboard.show()

    def start_simulation(self):
        if self.sim_manager and self.timer.isActive():
            QMessageBox.warning(self, "Simulation", "Simulation is already running.")
            return

        self.sim_manager = SimulationManager(self)
        
        QMessageBox.information(self, "Industrial Packaging SCADA System", 
                               "🏭 Starting Industrial Packaging Station SCADA System\n\n"
                               "🔧 FAILURE SYSTEM (MAX 3%):\n"
                               "   📥 Product Loader: 2% failure chance\n"
                               "   🏗️ Flap Folding: 1% failure chance\n"
                               "   📦 Tape Sealing: 3% failure chance\n"
                               "   🏷️ Label Applicator: 1% failure chance\n"
                               "   🔄 Conveyor: 0.5% failure chance\n\n"
                               "👥 HUMAN RESOURCES:\n"
                               "   🔧 Maintenance Operator: Handles machine repairs\n"
                               "   📦 Material Handler: Manually refills materials\n\n"
                               "🏗️ FLAP FOLDING PROCESS:\n"
                               "   • Lower flaps FIRST (create bottom structure)\n"
                               "   • Upper flaps SECOND (close top)\n"
                               "   • Real-time visualization in SCADA\n\n"
                               "📊 COMPACT SCADA DASHBOARD:\n"
                               "   • All information on one compact screen\n"
                               "   • Real-time status updates\n"
                               "   • Color-coded alerts and status")

        self.sim_manager.start_simulation()
        self.timer.start(1000)
        self.scada_timer.start(500)

    def stop_simulation(self):
        self.timer.stop()
        self.scada_timer.stop()
        if self.sim_manager:
            self.sim_manager.sim.stop_simulation()
        QMessageBox.information(self, "Simulation", "Industrial packaging simulation stopped.")

    def refresh_node_states(self):
        if not self.sim_manager:
            return
            
        sim = self.sim_manager.sim
        controller = sim.packaging_controller
        
        self.carton_presence_node.update_display(controller.carton_presence_detector.detection_status)
        self.machine_node.update_display(
            status=controller.station_status,
            package_count=controller.total_packages_processed
        )
        self.loader_output.update_display(controller.product_loading_module.operational_state)
        self.folder_output.update_display(controller.flap_folding_module.operational_state)
        self.sealer_output.update_display(controller.tape_sealing_module.operational_state)
        self.labeler_output.update_display(controller.label_application_module.operational_state)
        self.conveyor_output.update_display(controller.conveyor_drive_unit.operational_state)

    def update_scada_dashboard(self):
        if hasattr(self, 'scada_dashboard') and self.scada_dashboard and self.sim_manager:
            sim = self.sim_manager.sim
            controller = sim.packaging_controller
            self.scada_dashboard.update_dashboard(controller)

    def isModified(self): 
        return False
        
    def maybeSave(self): 
        return True

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    font = QFont("Arial", 9)
    app.setFont(font)
    
    wnd = PackagingNodeEditor()
    wnd.show()
    
    try:
        sys.exit(app.exec_())
    except Exception as e:
        print(f"Application error: {e}")
        sys.exit(1)