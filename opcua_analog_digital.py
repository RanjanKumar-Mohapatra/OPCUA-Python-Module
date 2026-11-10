from opcua import Client, ua
import time
import yaml
import utilities
import psycopg2
from datetime import datetime, timezone
import logging
import gc
import pyodbc
import requests
import os
import pandas as pd
from opcua.ua.uaerrors import UaStatusCodeError, BadSessionClosed
from zoneinfo import ZoneInfo
from psycopg2.extras import DictCursor

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

# OPC_SERVER_URL = os.getenv("OPC_SERVER_URL", "opc.tcp://192.168.1.213:49320") 
opcua_url = os.getenv("OPCUA_URL", "opc.tcp://192.168.1.213:49320")
postgres_url = os.getenv("POSTGRES_URL", "postgresql://postgres:sa123@192.168.1.215:5432/RapidSMS_Db")
register_file = os.getenv("REGISTER_FILE")

print(f"OPC UA Server URL: {opcua_url}")
print(f"PostgreSQL DB Connection: {postgres_url}")
print(f"Register File Path: {register_file}")
# breakpoint()

yamlfile = open(utilities.CONFIG_FILE_NAME, "r")
# Loads data from config file
data = yaml.load(yamlfile, Loader = yaml.FullLoader)

connection_string = postgres_url
OPC_SERVER_URL = opcua_url

# Access the list of mobile numbers directly from config file
# mobile_numbers = data.get('mobile_number', [])
# clientid = data['client_id']
# # deviceid = os.getenv("device_id", data['device_id'])
# deviceid = os.getenv("device_id", data['device_id']).split(',') if os.getenv("device_id", data['device_id']) else []
# value_type = os.getenv("value_type", data['value_type'])
# # connection_string = data['db_connection']['connection_string_postgre']
# connection_string = os.getenv("sql_connection_string", data['db_connection']['sql_connection_string'])
# alarmLogurl = os.getenv("alarmLogurl", data['alarmLogurl'])
# eventLogurl = os.getenv("eventLogurl", data['eventLogurl'])
# # branch_id = os.getenv("branch_id", data['branch_id'])
# branch_id = os.getenv("branch_id", data['branch_id']).split(',') if os.getenv("branch_id", data['branch_id']) else []

# # Load the Excel file
# file_path = "RegistersList.xlsx"
# df = pd.read_excel(file_path)

# # Convert to YAML format
# registers = []
# for _, row in df.iterrows():
#     registers.append({
#         "node_id": row["node_id"],
#         "threshold": row['threshold'],
#         "message_high": row['message_high'],
#         "message_low": row['message_low']
#     })

def fetch_users_from_db(group_name = 'Support'):
    conn = psycopg2.connect(connection_string)
    cursor = conn.cursor(cursor_factory=DictCursor)

    cursor.execute("""
        SELECT user_name, ph_number, email_id, user_group 
        FROM user_details 
        WHERE user_group = %s
          AND (ph_number IS NOT NULL)
    """, (group_name,))

    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    recipients = []
    for row in rows:
        recipient = {
            "user_name": row["user_name"],
            "user_group": row["user_group"],
            "mobile_number": row["ph_number"]
        }

        # Add WhatsApp if phone number exists
        if row["ph_number"]:
            recipient["whatsapp"] = f"whatsapp:+{str(row['ph_number']).strip()}"

        # Add email if available
        if row["email_id"]:
            recipient["email"] = str(row["email_id"]).strip()

        recipients.append(recipient)
    
    return recipients

support_users = fetch_users_from_db('Support')

# Convert to YAML format (Reading from Excel File)
def fetch_registers_from_excel(register_file):
    df = pd.read_excel(register_file)
    registers = []
    for _, row in df.iterrows():
        registers.append({
            "node_id": row["Address"],
            "trigger_value": int(row["Trigger Value"] or 0),
            "normal_value": int(row["Normal Value"] or 0),
            "trigger_message": row["Trigger Message"],
            "normal_message": row["Normal Message"],
            "user_group": row["User Group"],
            "low_low": int(row["low_low"] or 0),
            "low": int(row["low"] or 0),
            "high": int(row["high"] or 0),
            "high_high": int(row["high_high"] or 0),
            "low_low_message": row["low_low_message"],
            "low_message": row["low_message"],
            "high_message": row["high_message"],
            "high_high_message": row["high_high_message"]
        })
    return registers

# Reading from Database
def fetch_registers_from_db():
    conn = psycopg2.connect(connection_string)
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("""
        SELECT address, trigger_value, normal_value, trigger_message, normal_message, user_group,
                low_low, low, high, high_high, low_low_message, low_message, high_message, high_high_message
        FROM registers_opcua;
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return [
        {
            "node_id": row["address"],
            "trigger_value": int(row["trigger_value"] or 0),
            "normal_value": int(row["normal_value"] or 0),
            "trigger_message": row["trigger_message"],
            "normal_message": row["normal_message"],
            "user_group": row["user_group"],
            "low_low": int(row["low_low"] or 0),
            "low": int(row["low"] or 0),
            "high": int(row["high"] or 0),
            "high_high": int(row["high_high"] or 0),
            "low_low_message": row["low_low_message"],
            "low_message": row["low_message"],
            "high_message": row["high_message"],
            "high_high_message": row["high_high_message"]
        }
        for row in rows
    ]

# Fetch registers either from Excel or DB
if register_file and os.path.exists(register_file):
    logger.info(f"Reading register data from file: {register_file}")
    registers = fetch_registers_from_excel(register_file)
else:
    logger.info("Reading register data from PostgreSQL database.")
    registers = fetch_registers_from_db()

# Save to register.yml
yaml_file = "registers.yml"
with open(yaml_file, "w") as file:
    yaml.dump({"registers": registers}, file, default_flow_style=False)

print(f"Successfully imported {len(registers)} registers into {yaml_file}")
logger.info(f"Successfully imported {len(registers)} registers into {yaml_file}")


# Load registers from register.yml
def load_registers():
    with open("registers.yml", "r") as file:
        return yaml.safe_load(file)["registers"]

REGISTERS = load_registers()
REGISTERS_DICT = {item["node_id"]: item for item in REGISTERS}
# breakpoint()

def insert_error_log(error_details):
    """Insert error log in to the database."""
    conn = psycopg2.connect(connection_string)
    cur = conn.cursor()
    error_details = "Rapid OPCUA Client : " + str(error_details)
    cur.execute("""
                INSERT INTO error_log (error_details)
                VALUES (%s);
            """, (error_details,))
    conn.commit()
    cur.close()
    conn.close()


# Separate the Node ID Only
node_ids = [tag["node_id"] for tag in REGISTERS]
directNode = {"directNodes": node_ids}
print(directNode)

# Track consecutive violations
counters = {
    node_id["node_id"]: {
        "high_high": 0,
        "high": 0, 
        "low": 0,
        "low_low": 0,
        "normal": 0,
        "state": "normal"
    } for node_id in REGISTERS
}

error_count = 0

def insert_sms_log(message, time, user_group, person_name = 'NA', mobile_number = 'NA'):
    try:
        # (INSERTING DATA TO POSTGRESQL DATABASE)
        conn = None
        cursor = None

        conn = psycopg2.connect(connection_string)
        cursor = conn.cursor()

        endUser_message = "TIME " + time + " " + message

        # Inserts single record based on Alarm Or Events 
        cursor.execute("""
                INSERT INTO sms_queue_opcua (message, person_name, mobile_number, user_group)
                VALUES (%s, %s, %s, %s);
            """, (endUser_message, person_name, mobile_number, user_group))

        conn.commit()

        # Close the cursor and connection
        if cursor:
            cursor.close()
        if conn:
            conn.close()
            
    except Exception as e:
        print("Error inserting SMS queue :", str(e))
        insert_error_log("Error inserting SMS queue : " + str(e))
        return None

# def insert_sms_log(message, value, tag_id, branch_name, aeType, branchId = branch_id):
#     try:
#         # Prepare payload
#         payload = {
#             "LogId": 0,
#             "TagId": tag_id,
#             "Values": str(value),
#             "aeType": aeType,
#             "QType": branch_name,   # "insertAlarm",
#             "SMS_Content": message,
#             # use a timezone-aware UTC datetime and keep the trailing 'Z' to match the previous format
#             "smsTime": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),  # e.g. 2025-09-16T03:30:04.957Z
#             "BranchId": branchId
#         }

#         # Make POST request
#         response = requests.post(alarmLogurl, json=payload)

#         # Raise error if status code is not 200
#         response.raise_for_status()

#         print("Alarm log inserted successfully:", response.json())
#         return response.json()

#     except Exception as e:
#         print("Error sending alarm log:", str(e))
#         return None

class SubHandler:
    def datachange_notification(self, node, val, data):
        # print(f"Data change on node {node}: {val}")

        node_id = str(node)
        if node_id not in directNode["directNodes"]:
            print(f"Node ID Not Found: {node}")
            return

        config = REGISTERS_DICT[node_id]
        # threshold = config.get("threshold", 0)

        status = counters[node_id]

        # Determine tag type based on value
        try:
            if val in (True, False, 0, 1, "0", "1"):
                is_digital = True
            else:
                try:
                    val = float(val)
                    is_digital = False
                except (TypeError, ValueError):
                    pass
            # val = float(val)
            # # Check if value is digital (0 or 1)
            # if val in [0, 1] or val in [True, False]:
            #     is_digital = True
            # else:
            #     is_digital = False
        except (ValueError, TypeError):
            print(f"Invalid value type for node {node}: {val}")
            return
        
        now_sgt = datetime.now(ZoneInfo("Asia/Singapore"))
        formatted_time = now_sgt.strftime("%Y-%m-%d %H:%M:%S")

        if is_digital:
            # last_states = {reg["node_id"]: None for reg in REGISTERS}
            # Digital tag handling
            val = round(float(val))

            node_id = node.nodeid.to_string()
            node_id_msg = split_node_id(node_id)

            if val in [1, True] and status["state"] != "high":
                # print(f"Digital HIGH: {config['trigger_message']}")
                msg = f"{node_id_msg}, Alarm Triggered."
                insert_sms_log(config['trigger_message'], formatted_time, config['user_group'])

                # insert_sms_log(msg, val, config["tag_id"], config["branch_name"], 1, config["branch_id"])
                # # insert_sms_log(config["trigger_message"], val, config["tag_id"], config["branch_name"], 1)
                status["state"] = "high"
            elif val in [0, False] and status["state"] != "low":
                # print(f"Digital LOW: {config['normal_message']}")
                msg = f"{node_id_msg}, Alarm Off."
                insert_sms_log(config['normal_message'], formatted_time, config['user_group'])

                # insert_sms_log(msg, val, config["tag_id"], config["branch_name"], 0, config["branch_id"])
                # # insert_sms_log(config["normal_message"], val, config["tag_id"], config["branch_name"], 0)
                status["state"] = "low"
        else:
            # Analog handling with 3-value hysteresis
            try:
                val_num = float(val)
                val_num = round(val_num, 2)
            except Exception:
                logger.warning("Non-numeric value for node %s: %s", node, val)
                return

            node_id = node.nodeid.to_string()
            node_id_msg = split_node_id(node_id)  # Remove the comma that creates a tuple

            if node_id not in directNode["directNodes"]:
                logger.debug("Node ID Not Found : %s", node_id)
                return

            config = REGISTERS_DICT.get(node_id)
            if not config:
                logger.debug("No config for node %s", node_id)
                return

            # status = counters[node_id]

            # Convert thresholds to float
            try:
                hh = float(config.get("high_high")) if config.get("high_high") else None
                h = float(config.get("high")) if config.get("high") else None
                l = float(config.get("low")) if config.get("low") else None
                ll = float(config.get("low_low")) if config.get("low_low") else None
            except (ValueError, TypeError):
                logger.error(f"Invalid threshold values for node {node_id}")
                return

            # reset other counters except the target
            def reset_except(target):
                for k in ("high_high", "high", "low", "low_low", "normal"):
                    if k == target:
                        continue
                    status[k] = 0

            # helper to send and log message (and persist to DB)
            def emit(msg, new_state, state = None):
                try:
                    if msg:
                        logger.info("Analog : " + msg)
                        # # insert_sms_log(msg, val_num, config["tag_id"], config["branch_name"], 1 if "Normal" not in msg else 0, config["branch_id"])
                        # insert_sms_log(msg, val_num, config["tag_id"], config["branch_name"], state, config["branch_id"])
                        insert_sms_log(msg, formatted_time, config['user_group'])
                        print("Analog : " + msg)
                finally:
                    status["state"] = new_state

            triggered = None
            # flags to know which threshold groups exist for this sensor
            has_high_cfg = (hh is not None) or (h is not None)
            has_low_cfg = (ll is not None) or (l is not None)

            # Clear counters for absent groups so "Off" messages won't be emitted later
            if not has_low_cfg:
                status["low"] = 0
                status["low_low"] = 0
            if not has_high_cfg:
                status["high"] = 0
                status["high_high"] = 0

            # Priority: HH > H > LL > L > normal. Only evaluate branches that actually have thresholds.
            if hh is not None and val_num >= hh:
                status["high_high"] += 1
                reset_except("high_high")
                triggered = "high_high"
            elif h is not None and val_num >= h:
                status["high"] += 1
                reset_except("high")
                triggered = "high"
            elif ll is not None and val_num <= ll:
                status["low_low"] += 1
                reset_except("low_low")
                triggered = "low_low"
            elif l is not None and val_num <= l:
                status["low"] += 1
                reset_except("low")
                triggered = "low"
            else:
                # treat as normal; increment only if any thresholds exist for this node
                if has_high_cfg or has_low_cfg:
                    status["normal"] += 1
                triggered = "normal"

            # require 3 consecutive readings to act
            prev_state = status.get("state", "normal")

            # Handle transitions with normalized messages
            if triggered == "high_high" and prev_state not in ("high_high", "high", "low_low", "low"):
                msg = f"{node_id_msg}, Value : {val_num}, Hi Hi Alarm (HH)"
                emit(msg, "high_high", 1)
                
            elif triggered == "high_high" and prev_state == "high":
                msg = f"{node_id_msg}, Value : {val_num}, High Warning (H) Off"
                emit(msg, "high_high", 0)
                msg = f"{node_id_msg}, Value : {val_num}, Hi Hi Alarm (HH)"
                emit(msg, "high_high", 1)

            elif triggered == "high_high" and prev_state == "low_low":
                msg = f"{node_id_msg}, Value : {val_num}, Lo Lo Alarm (LL) Off"
                emit(msg, "high_high", 0)
                msg = f"{node_id_msg}, Value : {val_num}, Hi Hi Alarm (HH)"
                emit(msg, "high_high", 1)

            elif triggered == "high_high" and prev_state == "low":
                msg = f"{node_id_msg}, Value : {val_num}, Low Warning (L) Off"
                emit(msg, "high_high", 0)
                msg = f"{node_id_msg}, Value : {val_num}, Hi Hi Alarm (HH)"
                emit(msg, "high_high", 1)
            
            elif triggered == "high" and prev_state == "high_high":
                msg = f"{node_id_msg}, Value : {val_num}, Hi Hi Alarm (HH) Off"
                emit(msg, "high", 0)
                msg = f"{node_id_msg}, Value : {val_num}, High Warning (H)"
                emit(msg, "high", 2)

            elif triggered == "high" and prev_state not in ("high", "high_high", "low_low", "low"):
                msg = f"{node_id_msg}, Value : {val_num}, High Warning (H)"
                emit(msg, "high", 2)

            elif triggered == "high" and prev_state == "low_low":
                msg = f"{node_id_msg}, Value : {val_num}, Lo Lo Alarm (LL) Off"
                emit(msg, "high", 0)
                msg = f"{node_id_msg}, Value : {val_num}, High Warning (H)"
                emit(msg, "high", 2)

            elif triggered == "high" and prev_state == "low":
                msg = f"{node_id_msg}, Value : {val_num}, Low Warning (L) Off"
                emit(msg, "high", 0)
                msg = f"{node_id_msg}, Value : {val_num}, High Warning (H)"
                emit(msg, "high", 2)

            elif triggered == "normal" and prev_state == "high":
                msg = f"{node_id_msg}, Value : {val_num}, High Warning (H) Off"
                emit(msg, "normal", 0)

            elif triggered == "low_low" and prev_state not in ("low_low", "low", "high", "high_high"):
                msg = f"{node_id_msg}, Value : {val_num}, Lo Lo Alarm (LL)"
                emit(msg, "low_low", 1)

            elif triggered == "low_low" and prev_state == "low":
                msg = f"{node_id_msg}, Value : {val_num}, Low Warning (L) Off"
                emit(msg, "low_low", 0)
                msg = f"{node_id_msg}, Value : {val_num}, Lo Lo Alarm (LL)"
                emit(msg, "low_low", 1)

            elif triggered == "low_low" and prev_state == "high":
                msg = f"{node_id_msg}, Value : {val_num}, High Warning (H) Off"
                emit(msg, "low_low", 0)
                msg = f"{node_id_msg}, Value : {val_num}, Lo Lo Alarm (LL)"
                emit(msg, "low_low", 1)

            elif triggered == "low_low" and prev_state == "high_high":
                msg = f"{node_id_msg}, Value : {val_num}, Hi Hi Alarm (HH) Off"
                emit(msg, "low_low", 0)
                msg = f"{node_id_msg}, Value : {val_num}, Lo Lo Alarm (LL)"
                emit(msg, "low_low", 1)

            elif triggered == "low" and prev_state not in ("low", "low_low", "high", "high_high"):
                msg = f"{node_id_msg}, Value : {val_num}, Low Warning (L)"
                emit(msg, "low", 2)

            elif triggered == "low" and prev_state == "high":
                msg = f"{node_id_msg}, Value : {val_num}, High Warning (H) Off"
                emit(msg, "low", 0)
                msg = f"{node_id_msg}, Value : {val_num}, Low Warning (L)"
                emit(msg, "low", 2)

            elif triggered == "low" and prev_state == "high_high":
                msg = f"{node_id_msg}, Value : {val_num}, Hi Hi Alarm (HH) Off"
                emit(msg, "low", 0)
                msg = f"{node_id_msg}, Value : {val_num}, Low Warning (L)"
                emit(msg, "low", 2)

            elif triggered == "low" and prev_state == "low_low":
                msg = f"{node_id_msg}, Value : {val_num}, Lo Lo Alarm (LL) Off"
                emit(msg, "low", 0)
                msg = f"{node_id_msg}, Value : {val_num}, Low Warning (L)"
                emit(msg, "low", 2)

            elif triggered == "normal" and prev_state == "low":
                msg = f"{node_id_msg}, Value : {val_num}, Low Warning (L) Off"
                emit(msg, "normal", 0)


def split_node_id(node_id):
    """Split node ID and return only the device.sensor part"""
    try:
        # Split on 's=' and take the second part
        # device_part = node_id.split('s=')[1]
        # Split by dots
        parts = node_id.split('.')
        # Combine device (index 1) and sensor (index 2)
        if len(parts) >= 3:
            device_sensor = f"{parts[1]}.{parts[2]}"
            return device_sensor
        return node_id
    except:
        return node_id  # Return original if splitting fails


def main():
    client = Client(OPC_SERVER_URL)
    # client.set_user("Administrator")  # Optional if using anonymous
    # client.set_password("Administrator*")
    try:
        nodeDatas = []
        client.connect()
        logger.info("Connected to OPC UA server")

        for id in directNode["directNodes"]:
            nodeDatas.append(client.get_node(id))

        # Get node objects for each node ID
        nodes = [client.get_node(node_id) for node_id in nodeDatas]

        # Create a subscription with a specified handler and monitoring interval (in ms)
        handler = SubHandler()
        subscription = client.create_subscription(500, handler)  # 500 ms interval

        # Subscribe to each node for data changes
        handles = []
        for node in nodes:
            handle = subscription.subscribe_data_change(node)
            handles.append(handle)
            # print(f"Subscribed to node: {node}")

        # Run the subscription indefinitely
        try:
            while True:
                time.sleep(5)  # Keep the script running to receive data changes
        except KeyboardInterrupt:
            print("Stopping subscription...")
            error_count += 1
            if error_count <= 3:
                insert_error_log("Error reading data : " + str(e))
                now_sgt = datetime.now(ZoneInfo("Asia/Singapore"))
                formatted_time = now_sgt.strftime("%Y-%m-%d %H:%M:%S") 
                for to_number in support_users:
                    ph_number = to_number['mobile_number']
                    user_name = to_number['user_name']
                    insert_sms_log("Error reading data : " + str(e), formatted_time, 'Support', user_name, ph_number)
            handle_error_and_reconnect(client)

        # Unsubscribe from each node and delete the subscription
        for handle in handles:
            subscription.unsubscribe(handle)
        subscription.delete()

    except Exception as e:
        logger.error(f"Error: {e}")
        error_count += 1
        if error_count <= 3:
            insert_error_log("Error reading data : " + str(e))
            now_sgt = datetime.now(ZoneInfo("Asia/Singapore"))
            formatted_time = now_sgt.strftime("%Y-%m-%d %H:%M:%S") 
            for to_number in support_users:
                ph_number = to_number['mobile_number']
                user_name = to_number['user_name']
                insert_sms_log("Error reading data : " + str(e), formatted_time, 'Support', user_name, ph_number)
        handle_error_and_reconnect(client)
    finally:
        client.disconnect()
        # print("Disconnected from OPC UA Server")
        # logger.info("Disconnected from OPC UA Server")
        gc.collect()

        # print("Reconnecting in 5 seconds...")
        # logger.info("Reconnecting in 5 seconds...")
        # time.sleep(5)
        # main()

def handle_error_and_reconnect(client):
    """Cleanly handle errors and reconnect."""
    try:
        client.disconnect()
    except Exception:
        pass

    logger.info("Reconnecting in 5 seconds...")
    print("Reconnecting in 5 seconds...")

    time.sleep(5)
    main()  # Restart


# if __name__ == "__main__":
#     logger.info("Monitor OPC UA Tags Module Started.")
#     main()

if __name__ == "__main__":
    while True:
        try:
            logger.info("Monitor OPC UA Tags Module Started.")
            main()  # or your main client logic
        except (UaStatusCodeError, BadSessionClosed) as e:
            print(f"OPC UA session error: {e}. Reconnecting in 5 seconds...")
            time.sleep(5)
            continue
        except Exception as e:
            print(f"Unexpected error: {e}. Reconnecting in 5 seconds...")
            time.sleep(5)
            continue