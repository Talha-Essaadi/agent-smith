class FinalAnswerSignal(BaseException):
    """Control-flow signal raised by final_answer() to end the agent loop."""

    def __init__(self, value):
        super().__init__(str(value))
        self.value = value


def final_answer(value):
    raise FinalAnswerSignal(value)
