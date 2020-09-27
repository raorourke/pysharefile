from pydantic import BaseModel
from typing import List, Type
from pathlib import Path
import logging

from .helpers import to_snake

this = Path(__file__)
logger = logging.getLogger(f"logger.{this.stem}")


class ListModel(BaseModel):
    klass: Type[BaseModel]
    klasses: List[BaseModel]

    def __init__(
            self,
            klass,
            *klasses,
            keys_override: List[str] = None,
    ):
        logger.debug(
            f"[ListModel|{self.__class__.__name__}] __init__({klass=}, {len(klasses)=}, {keys_override=})")
        super().__init__(klass=klass, klasses=klasses)

    @property
    def attributes(self):
        return tuple(klass.attributes for klass in self.klasses)

    @property
    def deep_attributes(self):
        return tuple(klass.deep_attributes for klass in self.klasses)

    def __setattr__(self, name, value):
        self.__dict__[name] = value

    def __repr__(self):
        if self.klasses:
            if len(self.klasses) > 1:
                return f"{self.__class__.__name__}({', '.join(f'{klass}' for klass in self.klasses)})"
            return f"{self.__class__.__name__}({repr(self.klasses[0])})"
        return f"{self.__class__.__name__}"

    def __str__(self):
        if self.klasses:
            if len(self.klasses) > 1:
                return f"{self.__class__.__name__}({', '.join(f'{klass}' for klass in self.klasses)})"
            return f"{self.__class__.__name__}({self.klasses[0]})"
        return f"{self.__class__.__name__}"

    def __iter__(self):
        yield from self.klasses

    def sort(self, key):
        yield from sorted(
            self.klasses,
            key=key
        )

    def __delitem__(self, key):
        attr = getattr(self.klasses[key], self.key) or getattr(self.klasses[key], self.alt)
        self.__delattr__(attr)

    def __getitem__(self, key):
        if isinstance(key, int) and key <= len(self.klasses):
            return self.klasses[key]
        return self.__getattribute__(to_snake(key))

    def __getattr__(self, key):
        if isinstance(key, int) and key <= len(self.klasses):
            return self.klasses[key]
        return self.__getattribute__(to_snake(key))

    def __setitem__(self, key, value):
        attr = getattr(self.klasses[key], self.key) or getattr(self.klasses[key], self.alt)
        self.__setattr__(attr, value)

    def __len__(self):
        return len(self.klasses)

    def get_member_by_attribute(self, attribute: str, value: str):
        matches = [
            member
            for member in self.klasses
            if getattr(member, attribute, None) == value
        ]
        if matches:
            return matches[0] if len(matches) == 1 else matches

    def get_child_by_attribute(self, child_group: str, attribute: str, value: str):
        matches = [
            child
            for member in self.klasses
            for child in getattr(member, child_group, [])
            if getattr(child, attribute, None) == value
        ]
        if matches:
            return matches[0] if len(matches) == 1 else matches


class Collection(BaseModel):
    collection: List[Type[BaseModel]]
    items: List[BaseModel]

    def __init__(self, *items):
        collection = {item.__class__ for item in items}
        super().__init__(
            collection=collection,
            items=items
        )
        attributes = {}
        for item in self.items:
            attributes.setdefault(
                item.__class__, []
            ).append(item)
        for klass, _items in attributes.items():
            object.__setattr__(
                self,
                f"{to_snake(klass.__name__)}s",
                klass.s(
                    *_items
                )
            )

    def __iter__(self):
        yield from self.items

    def __len__(self):
        return len(self.items)