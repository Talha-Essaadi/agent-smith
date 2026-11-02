class FinalAnswerSignal(Exception):
    def __init__(self, value):
        self.value = value


def final_answer(value):
    raise FinalAnswerSignal(value)