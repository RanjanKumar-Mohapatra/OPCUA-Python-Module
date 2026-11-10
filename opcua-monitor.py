from opcua import Client, ua
import time
import yaml
import pandas as pd
import utilities
import psycopg2
from datetime import datetime
import logging
import gc
import os
# import pytz
from zoneinfo import ZoneInfo
from psycopg2.extras import DictCursor

opcua_url = os.getenv("OPCUA_URL", "opc.tcp://192.168.1.213:49320")
postgres_url = os.getenv("POSTGRES_URL", "postgresql://postgres:sa123@192.168.1.215:5432/RapidSMS_Db")
register_file = os.getenv("REGISTER_FILE")

print(f"OPC UA Server URL: {opcua_url}")
print(f"PostgreSQL DB Connection: {postgres_url}")
print(f"Register File Path: {register_file}")
# breakpoint()

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

# yamlfile = open(utilities.CONFIG_FILE_NAME, "r")
# # Loads data from config file
# data = yaml.load(yamlfile, Loader = yaml.FullLoader)
# # Access the list of mobile numbers directly from config file
# mobile_numbers = data.get('mobile_number', [])

connection_string = postgres_url
OPC_SERVER_URL = opcua_url

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
            "address": row["Address"],
            "trigger_value": int(row["Trigger Value"]),
            "normal_value": int(row["Normal Value"]),
            "trigger_message": row["Trigger Message"],
            "normal_message": row["Normal Message"],
            "user_group": row["User Group"]
        })
    return registers

# Reading from Database
def fetch_registers_from_db():
    conn = psycopg2.connect(connection_string)
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("""
        SELECT address, trigger_value, normal_value, trigger_message, normal_message, user_group
        FROM registers_opcua;
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return [
        {
            "address": row["address"],
            "trigger_value": int(row["trigger_value"]),
            "normal_value": int(row["normal_value"]),
            "trigger_message": row["trigger_message"],
            "normal_message": row["normal_message"],
            "user_group": row["user_group"]
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

error_count = 0

# OPC UA Subscription Handler
def monitor_opcua():
    client = Client(OPC_SERVER_URL)
    
    try:
        client.connect()
        print(f"Connected to OPC UA Server: {OPC_SERVER_URL}")
        logger.info(f"Connected to OPC UA Server: {OPC_SERVER_URL}")

        # # Check the Available Namespaces in WinCC
        # namespaces = client.get_namespace_array()
        # for i, ns in enumerate(namespaces):
        #     print(f"Namespace {i}: {ns}")

        # # Check To confirm the OPC UA server is working
        # root = client.get_root_node()
        # objects = client.get_objects_node()

        # for child in objects.get_children():
        #     print(child, child.get_display_name().Text)

        # # Trying to read a simple value
        # node = client.get_node("ns=0;i=2258")  # Server's current time
        # print(node.get_value())
        
        last_states = {reg["address"]: None for reg in REGISTERS}
        
        while True:
            for reg in REGISTERS:
                # TO SPLIT A NODE
                raw_node = reg["address"]
                if  " " in  raw_node:
                    ns_uri, identifier = raw_node.split(" ", 1)

                    ns_index = client.get_namespace_index(ns_uri)
                    node = client.get_node(ua.NodeId(identifier, ns_index))
                else:
                    # Use the below code if the Node format is "ns=2;s=Channel1.Device4.PressurePump1"
                    node = client.get_node(reg["address"])

                # value = node.get_value()
                try:
                    data_value = node.get_data_value()
                    status = data_value.StatusCode

                    if not status.is_good():
                        print(f"[{reg['address']}] Skipping due to bad status: {status}")
                        continue

                    value = data_value.Value.Value
                    timestamp = data_value.SourceTimestamp
                    if timestamp:    
                        now_sgt = datetime.now(ZoneInfo("Asia/Singapore"))
                        formatted_time = now_sgt.strftime("%Y-%m-%d %H:%M:%S")                     
                        # formatted_time = timestamp.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        formatted_time = "Unknown Time"

                except Exception as e:
                    print(f"[{reg['address']}] Error reading data: {e}")
                    error_count += 1
                    if error_count <= 3:
                        insert_error_log("Error reading data : " + str(e))
                        for to_number in support_users:
                            ph_number = to_number['mobile_number']
                            user_name = to_number['user_name']
                            insert_sms_log("Error reading data : " + str(e), formatted_time, 'Support', user_name, ph_number)
                    
                    handle_error_and_reconnect(client)
                    # continue


                if value == reg["trigger_value"] and last_states[reg["address"]] != value:
                    print(f"ALERT: {reg['trigger_message']}")
                    insert_sms_log(reg['trigger_message'], formatted_time, reg['user_group'])
                elif value == reg["normal_value"] and last_states[reg["address"]] != value:
                    print(f"INFO: {reg['normal_message']}")
                    insert_sms_log(reg['normal_message'], formatted_time, reg['user_group'])
                
                last_states[reg["address"]] = value
            
            time.sleep(1)  # Poll every second
    
    except Exception as e:
        print(f"Error: {e}")
        error_count += 1
        if error_count <= 3:
            now_sgt = datetime.now(ZoneInfo("Asia/Singapore"))
            formatted_time = now_sgt.strftime("%Y-%m-%d %H:%M:%S") 
            insert_error_log("Error : " + str(e))
            for to_number in support_users:
                ph_number = to_number['mobile_number']
                user_name = to_number['user_name']
                insert_sms_log("Error : " + str(e), formatted_time, 'Support', user_name, ph_number)
        logger.error(f"Error: {e}")
        handle_error_and_reconnect(client)
    finally:
        client.disconnect()
        # print("Disconnected from OPC UA Server")
        # insert_error_log("Disconnected from OPC UA Server")
        # logger.info("Disconnected from OPC UA Server")
        gc.collect()

        # print("Reconnecting in 5 seconds...")
        # logger.info("Reconnecting in 5 seconds...")
        # insert_error_log("Reconnecting in 5 seconds...")
        # time.sleep(5)
        error_count = 0
        # monitor_opcua()

def handle_error_and_reconnect(client):
    """Cleanly handle errors and reconnect."""
    try:
        client.disconnect()
    except Exception:
        pass

    insert_error_log("Disconnected from OPC UA Server")
    insert_error_log("Reconnecting in 5 seconds...")
    logger.info("Reconnecting in 5 seconds...")
    print("Reconnecting in 5 seconds...")

    time.sleep(5)
    monitor_opcua()  # Restart


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


        # # If want to insert same record multiple time based on mobile number list
        # for each_row in mobile_numbers:
        #     cursor.execute("""
        #         INSERT INTO sms_log (message, person_name, mobile_number)
        #         VALUES (%s, %s, %s);
        #     """, (message, each_row['name'], each_row['ph_number']))

        #     conn.commit()

        # Close the cursor and connection
        if cursor:
            cursor.close()
        if conn:
            conn.close()
            
    except Exception as e:
        print("Error inserting SMS queue :", str(e))
        insert_error_log("Error inserting SMS queue : " + str(e))
        return None


if __name__ == "__main__":
    logger.info("Monitor OPC UA Tags Module Started.")
    print("Monitor OPC UA Tags Module Started.")
    monitor_opcua()





