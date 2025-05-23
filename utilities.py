from enum import Enum, auto
from datetime import datetime

CONFIG_FILE_NAME = "config.yml"

def generate_timestamp(region):
    """
    Returns a string of the current date and time in the desired format
    """
    timestr = datetime.strftime(datetime.now(tz=region), "%d/%m/%Y %H:%M:%S.%f")
    timestr = timestr[:-3]
    timestr = timestr + datetime.now(tz=region).strftime(":%z")
    return timestr