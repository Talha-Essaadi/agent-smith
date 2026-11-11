
import json
import docker


def close_attachment(connection):
    """
    Close the Docker attachment and its underlying
    HTTP response in the correct order.
    """
    if connection is None:
        return

    # Docker SDK SocketIO wrapper may retain
    # the HTTP response in a private attribute.
    response = getattr(connection, "_response", None)

    if response is not None:
        response.close()

    connection.close()


def main():
    client = docker.from_env()

    code = """
print("Hello from Docker!")
print(10 + 20)
"""

    container_script = """
import sys
import json
import traceback

try:
    message = json.loads(sys.stdin.readline())
    exec(message["code"], {"__name__": "__main__"})
except Exception:
    traceback.print_exc()
    sys.exit(1)
"""

    container = None
    connection = None

    try:
        # 1. Create container
        container = client.containers.create(
            image="python:3.10-slim",
            command=["python", "-u", "-c", container_script],
            stdin_open=True,
            tty=False,
            detach=True,
            network_mode="none",
        )

        print("Container created:", container.short_id)

        # 2. Attach socket before starting
        connection = container.attach_socket(
            params={
                "stdin": 1,
                "stream": 1,
            }
        )

        # 3. Start container
        container.start()
        print("Container started")

        # 4. Send code as one JSON line
        message = json.dumps({"code": code}) + "\n"

        connection._sock.sendall(
            message.encode("utf-8")
        )

        print("Code sent successfully")

        # 5. Wait for execution
        result = container.wait(timeout=30)

        print("Exit code:", result["StatusCode"])

        # 6. Retrieve output
        print("STDOUT / STDERR:")
        print(container.logs().decode("utf-8"))

    finally:
        # 7. Close attachment
        if connection is not None:
            try:
                close_attachment(connection)
            except Exception as exc:
                print("Attachment cleanup error:", exc)

        # 8. Remove container
        if container is not None:
            try:
                container.remove(force=True)
            except docker.errors.DockerException:
                pass

        # 9. Close Docker client
        client.close()


if __name__ == "__main__":
    main()
