class NotFoundException(Exception):
    """Объект не найден."""

    def __init__(self, detail: str | None = None):
        """Init."""
        self.detail = detail or 'Not found'
        super().__init__(self.detail)


class DuplicateException(Exception):
    """Повторная запись."""

    def __init__(self, detail: str | None = None):
        """Init."""
        self.detail = detail or 'Already exists'
        super().__init__(self.detail)


class NoFreeAccountError(Exception):
    """Нет свободного аккаунта под лот."""


class SteamModuleError(Exception):
    """Ошибка взаимодействия со Steam (логин, код, смена пароля)."""


class ProviderNotReadyError(Exception):
    """Провайдер аренды ещё не реализован (логика выдачи/деавторизации не подключена)."""


class ProcessingError(Exception):
    """Прочая ошибка обработки."""
