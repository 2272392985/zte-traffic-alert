from zte_traffic_alert.app_paths import default_gui_config_path
from zte_traffic_alert.gui import run_gui


if __name__ == "__main__":
    run_gui(str(default_gui_config_path()))

