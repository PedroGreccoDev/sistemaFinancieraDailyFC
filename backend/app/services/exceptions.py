class ServiceError(Exception):
    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(ServiceError):
    status_code = 404


class UnauthorizedError(ServiceError):
    status_code = 401


class ConflictError(ServiceError):
    status_code = 409


class GoneError(ServiceError):
    status_code = 410


class ValidationError(ServiceError):
    status_code = 422


class DatabaseWriteError(ServiceError):
    status_code = 500

