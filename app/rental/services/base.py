from functools import cached_property
from typing import TypeVar


T = TypeVar('T')


def get_repository[T](repo_cls: type[T]) -> T:
    """Get repository bound to the service session."""

    def _get_repository(self) -> T:
        return repo_cls(self.session)  # type: ignore

    return cached_property(_get_repository)  # type: ignore


def get_service[T](service_cls: type[T]) -> T:
    """Get service bound to the same session."""

    def _get_service(self) -> T:
        return service_cls(self.session)  # type: ignore

    return cached_property(_get_service)  # type: ignore
