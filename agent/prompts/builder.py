from pathlib import Path
from schemas import MBPPTaskInput, SWEBenchTaskInput

_PROMPTS_DIR = Path(__file__).resolve().parent


class PromptBuilder:
    @staticmethod
    def build_mbpp_system_prompt(sandbox_manual: str) -> str:
        template = (_PROMPTS_DIR / "mbpp_system.txt").read_text()
        return template.replace("{sandbox_manual}", sandbox_manual)

    @staticmethod
    def build_mbpp_user_prompt(task: MBPPTaskInput) -> str:
        imports = "\n".join(task.test_imports) if task.test_imports else "None"
        tests = "\n".join(task.test_list)

        return (
            f"Task ID: {task.task_id}\n"
            f"Problem Description: {task.task_definition}\n"
            f"Required Function Signature / Definition:"
            f" {task.function_definition}\n"
            f"Test Imports: {imports}\n"
            f"Test Assertions: {tests}\n"
        )

    @staticmethod
    def build_swebench_system_prompt(sandbox_manual: str) -> str:
        template = (_PROMPTS_DIR / "swebench_system.txt").read_text()
        return template.replace("{sandbox_manual}", sandbox_manual)

    @staticmethod
    def build_swebench_user_prompt(task: SWEBenchTaskInput) -> str:
        hints = task.hints_text if task.hints_text else "None"

        return (
            f"Instance ID: {task.instance_id}\n"
            f"Repository: {task.repo}\n"
            f"Problem Statement:\n{task.problem_statement}\n"
            f"Hints:\n{hints}\n"
            f"Eval Script:\n{task.eval_script}\n"
        )
