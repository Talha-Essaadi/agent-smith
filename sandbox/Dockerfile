ARG BASE_IMAGE=python:3.10-slim

FROM ${BASE_IMAGE}

WORKDIR /testbed

COPY sandbox/container/ipc_bridge.py /opt/agent/ipc_bridge.py
COPY sandbox/container/main.py /opt/agent/main.py
COPY sandbox/container/final_answer.py /opt/agent/final_answer.py
COPY sandbox/container/tool_wrapper.py /opt/agent/tool_wrapper.py

ENTRYPOINT ["python", "/opt/agent/main.py"]