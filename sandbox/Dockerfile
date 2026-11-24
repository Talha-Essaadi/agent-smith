ARG BASE_IMAGE=python:3.10-slim

FROM ${BASE_IMAGE}

RUN groupadd --gid 1000 agentuser \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/sh agentuser \
    && mkdir -p /opt/agent /testbed /tmp/agent \
    && chown 1000:1000 /testbed /tmp/agent

COPY sandbox/container/ipc_bridge.py /opt/agent/ipc_bridge.py
COPY sandbox/container/main.py /opt/agent/main.py
COPY sandbox/container/final_answer.py /opt/agent/final_answer.py
COPY sandbox/container/tool_wrapper.py /opt/agent/tool_wrapper.py
COPY sandbox/container/restrictions.py /opt/agent/restrictions.py

# Keep the agent code readable but read-only for the runtime user.
RUN chmod 0555 /opt/agent && chmod 0444 /opt/agent/*.py

WORKDIR /testbed
# Run without root privileges using the dedicated user's UID and GID.
USER 1000:1000

# Start Python directly for signal handling, with unbuffered output for live logs.
ENTRYPOINT ["python", "-u", "/opt/agent/main.py"]
