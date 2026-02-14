class BotException(Exception):
    """Базовый класс для всех исключений, связанных с работой бота."""
    pass

class UserInterruptError(BotException):
    """
    Исключение, выбрасываемое, когда пользователь прерывает выполнение
    (ставит на паузу или запрашивает перезапуск).
    Это ожидаемое поведение, а не ошибка.
    """
    pass

class ActionFailedError(BotException):
    """
    Исключение, выбрасываемое, когда какое-либо действие (например, клик)
    не может быть выполнено по техническим причинам.
    """
    def __init__(self, message="Не удалось выполнить действие."):
        self.message = message
        super().__init__(self.message)