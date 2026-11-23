class FinalAnswerSignal(Exception):
    """Control-flow signal raised by
     final_answer() to submit the final answer."""

    def __init__(self, value):
        super().__init__(str(value))
        self.value = value


def final_answer(answer=None, *, value=None):
    """Submit the final answer and terminate the agent loop.

    Accepts positional `final_answer("...")` as well as keyword
    `final_answer(answer="...")` or `final_answer(value="...")`.
    """
    payload = value if (answer is None and value is not None) else answer
    raise FinalAnswerSignal(payload)
