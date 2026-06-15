from app.rental.models.extension import Extension
from app.rental.repositories.base import Repository


class ExtensionRepository(Repository[Extension]):
    model = Extension
