
.DEFAULT_GOAL := help

PYTHON := uv run
IMAGE := agent-sandbox:latest
DOCKERFILE := sandbox/Dockerfile

.PHONY: help install build run mbpp swebench \
        test lint format check clean fclean re \
        ps logs volumes

help:
	@echo "Agent Smith Commands:"
	@echo "  make install   - Install dependencies"
	@echo "  make build     - Build sandbox Docker image"
	@echo "  make run       - Start interactive sandbox"
	@echo "  make mbpp      - Start sandbox with MBPP MCP"
	@echo "  make swebench  - Start sandbox with SWE-bench MCP"
	@echo "  make test      - Run tests"
	@echo "  make lint      - Run flake8 and mypy"
	@echo "  make format    - Format Python code"
	@echo "  make check     - Run all checks"
	@echo "  make clean     - Remove Python caches"
	@echo "  make fclean    - Remove Docker resources"
	@echo "  make re        - Rebuild sandbox image"

install:
	uv sync

build:
	docker build -t $(IMAGE) -f $(DOCKERFILE) .

run:
	$(PYTHON) sandbox

mbpp:
	$(PYTHON) sandbox --mcp-stdio "python mcp_tools_mbpp.py"

swebench:
	$(PYTHON) sandbox --mcp-stdio "python mcp_tools_swebench.py"

test:
	$(PYTHON) pytest

lint:
	$(PYTHON) flake8 .
	$(PYTHON) mypy .

format:
	$(PYTHON) black .

check: lint test

ps:
	docker ps -a

logs:
	docker logs $(CONTAINER)

volumes:
	docker volume ls

clean:
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -prune -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -prune -exec rm -rf {} +

fclean: clean
	-docker image rm $(IMAGE)
	-docker volume rm agent-testbed agent-tmp

re: fclean build
