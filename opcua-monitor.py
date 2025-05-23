from opcua import Client, ua
import time
import yaml
import pandas as pd
import utilities
import psycopg2
from datetime import datetime
import logging
import gc


# Configure logger
logger = logging.getLogger("OPCUA_Monitor")
logger.setLevel(logging.DEBUG)

# Log file handler
file_handler = logging.FileHandler("logs/opcua.log")
file_handler.setLevel(logging.DEBUG)

# Log message format
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)

# Add handler to logger
logger.addHandler(file_handler)

# OPC UA Server URL
# OPC_SERVER_URL = "opc.tcp://127.0.0.1:49320"
# REMOTE KEPServer (Tailscale Tunnel)
OPC_SERVER_URL = "opc.tcp://100.120.39.70:49320"

yamlfile = open(utilities.CONFIG_FILE_NAME, "r")
# Loads data from config file
data = yaml.load(yamlfile, Loader = yaml.FullLoader)

# Access the list of mobile numbers directly from config file
mobile_numbers = data.get('mobile_number', [])
connection_string = data['db_connection']['connection_string_postgre']

# Load the Excel file
file_path = "RegistersList.xlsx"
df = pd.read_excel(file_path)

# Convert to YAML format
registers = []
for _, row in df.iterrows():
    registers.append({
        "address": row["Address"],
        "trigger_value": int(row["Trigger Value"]),
        "normal_value": int(row["Normal Value"]),
        "trigger_message": row["Trigger Message"],
        "normal_message": row["Normal Message"]
    })

# Save to register.yml
yaml_file = "registers.yml"
with open(yaml_file, "w") as file:
    yaml.dump({"registers": registers}, file, default_flow_style=False)

print(f"✅ Successfully imported {len(registers)} registers into {yaml_file}")
logger.info(f"✅ Successfully imported {len(registers)} registers into {yaml_file}")


# Load registers from register.yml
def load_registers():
    with open("registers.yml", "r") as file:
        return yaml.safe_load(file)["registers"]

REGISTERS = load_registers()

# 🔔 OPC UA Subscription Handler
def monitor_opcua():
    client = Client(OPC_SERVER_URL)
    
    try:
        client.connect()
        print(f"Connected to OPC UA Server: {OPC_SERVER_URL}")
        logger.info(f"Connected to OPC UA Server: {OPC_SERVER_URL}")
        
        last_states = {reg["address"]: None for reg in REGISTERS}
        
        while True:
            for reg in REGISTERS:
                node = client.get_node(reg["address"])
                value = node.get_value()
                
                if value == reg["trigger_value"] and last_states[reg["address"]] != value:
                    print(f"ALERT: {reg['trigger_message']}")
                    insert_sms_log(reg['trigger_message'])
                elif value == reg["normal_value"] and last_states[reg["address"]] != value:
                    print(f"INFO: {reg['normal_message']}")
                    insert_sms_log(reg['normal_message'])
                
                last_states[reg["address"]] = value
            
            time.sleep(1)  # Poll every second
    
    except Exception as e:
        print(f"Error: {e}")
        logger.error(f"Error: {e}")
    finally:
        client.disconnect()
        print("Disconnected from OPC UA Server")
        logger.info("Disconnected from OPC UA Server")
        gc.collect()

        print("🔄 Reconnecting in 5 seconds...")
        logger.info("🔄 Reconnecting in 5 seconds...")
        time.sleep(5)
        monitor_opcua()


def insert_sms_log(message):
    try:
        # (INSERTING DATA TO POSTGRESQL DATABASE)
        conn = None
        cursor = None

        conn = psycopg2.connect(connection_string)
        cursor = conn.cursor()

        for each_row in mobile_numbers:
            cursor.execute("""
                INSERT INTO sms_log (message, person_name, mobile_number)
                VALUES (%s, %s, %s);
            """, (message, each_row['name'], each_row['ph_number']))

            conn.commit()

        # Close the cursor and connection
        if cursor:
            cursor.close()
        if conn:
            conn.close()
            
    except Exception as e:
        print("Error sending SMS:", str(e))
        return None


if __name__ == "__main__":
    logger.info("Monitor OPC UA Tags Module Started.")
    monitor_opcua()