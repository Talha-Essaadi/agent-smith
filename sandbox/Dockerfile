FROM python:3.10-slim

WORKDIR /testbed

COPY sandbox/container/ipc_bridge.py /testbed/ipc_bridge.py
COPY sandbox/container/main.py /testbed/main.py
COPY sandbox/container/final_answer.py /testbed/final_answer.py
COPY sandbox/container/tool_wrapper.py /testbed/tool_wrapper.py

CMD ["python", "/testbed/main.py"]