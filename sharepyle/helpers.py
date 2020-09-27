import re
from typing import Callable


def to_snake(egg: str) -> str:
    if egg:
        return re.sub(
            r'^(\d+)$',
            r'_\1',
            '_'.join(
                word.lower()
                for word in re.split(
                    r'\.|(?<!^)\_|\s+|\-',
                    re.sub(
                        r'([A-Z]+)(\_?)',
                        r' \1',
                        re.sub(
                            r'(([A-Z])([a-z]+))(\_?)',
                            r' \1',
                            str(egg)
                        )
                    )
                )
                if word
            )
        )

def get_key(klass, key: str, transform_func: Callable[[str], str] = None):
    bool_keys = {
        'true': to_snake(key),
        'false': f"not_{to_snake(key)}"
    }
    attribute_key = to_snake(getattr(klass, key, None))
    if attribute_key in bool_keys:
        attribute_key = bool_keys[attribute_key]
    return transform_func(attribute_key) if transform_func else attribute_key


def extract_attributes(values):
    attributes = {}
    for key, value in values.items():
        if key != 'attributes':
            if isinstance(value, dict):
                attributes.update(
                    {
                        key: extract_attributes(value)
                    }
                )
            else:
                attributes.update(
                    {
                        key: value
                    }
                )
    return attributes


def to_pascal(snake):
    exceptions = {
        'id': 'Id',
        'odata_type': 'odata.type',
        'odata_metadata': 'odata.metadata'
    }
    if snake in exceptions:
        return exceptions[snake]
    if snake and (parts := str(snake).split('_')):
        return ''.join(
            part.upper() if part in ['id', 'ip', 'kb', 'mb'] else part.capitalize()
            for part in parts
        )