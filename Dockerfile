# Use an official Python runtime as a base image
# FROM arm32v7/python:3.9.4-slim
FROM python:3.9.4-slim

# Set the working directory inside the container
WORKDIR /app
RUN apt update -y && apt install build-essential libssl-dev libffi-dev python-dev rustc -y && python -m ensurepip --upgrade

# Copy everything to the container
COPY . .

# Print the contents of the directory (debugging step)
RUN ls -l

# Print the contents of requirements.txt
RUN cat requirements.txt

# Copy only required files
# COPY requirements.txt ./
RUN pip install -r requirements.txt
# RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
# COPY . .

# Define the command to run the module
CMD ["python", "opcua-monitor.py"]
# CMD ["python3", "-u", "./opcua-monitor.py"]