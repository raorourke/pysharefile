from __future__ import annotations

import logging
import os
import re
from collections import deque
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from typing import Type, Any, Callable, Union, List, Dict

import aiohttp
import asyncio
import dateparser
import dpath.util
from dateutil import parser
from http_requester.requester import Requester
from pydantic import HttpUrl, BaseModel, Extra, root_validator, validator

from .creds import get_sharefile_credentials, BASE_URL
from .helpers import to_snake, extract_attributes, get_key, to_pascal
from .models import ListModel, Collection

logging.basicConfig(level=os.environ.get('LOGLEVEL', 'WARNING'))

__all__ = [
    'Event',
    'MainClass',
    'File',
    'Folder',
    'FavoriteFolder',
    'ParentFolder',
    'TemplateFolder',
    'ProductionFolder'
]

sf_creds = get_sharefile_credentials()

SF_REQUESTER = Requester(
    BASE_URL,
    creds=sf_creds
)


class MetaConfig(BaseModel):
    class Config:
        arbitrary_types_allowed = True
        extra = Extra.allow
        alias_generator = to_pascal
        allow_population_by_field_name = True


class ConfigModel(MetaConfig):
    keys: List[str] = ['name', 'id']

    def __repr__(self):
        return f"{self.__class__.__name__}"

    def __str__(self):
        return repr(self)

    def __getitem__(self, key):
        return self.__getattribute__(to_snake(key))

    def __getattr__(self, key):
        return self.__getattribute__(to_snake(key))

    def __setattr__(self, key, value):
        return object.__setattr__(self, to_snake(key), value)

    @root_validator
    def validate_attributes(cls, values):
        if values.get('attributes') is None:
            attributes = extract_attributes(values)
            values.update(
                {
                    'attributes': attributes
                }
            )
        for key, value in values.items():
            if klasses := value:
                if isinstance(klasses, list) and all(isinstance(klass, BaseModel) for klass in klasses):
                    klass = klasses[0].__class__
                    values.update(
                        {
                            key: klass.s(*klasses)
                        }
                    )
        if values.get('requester') is None:
            values.update(
                {
                    'requester': SF_REQUESTER
                }
            )
        return values

    @classmethod
    def construct_list_class(cls):

        def __init__(
                self,
                *data,
                keys_override: List[str] = None,
                transform_func: Callable[[str], str] = None
        ):
            super(ListModel, self).__init__(
                klass=cls,
                klasses=data
            )

            def index_attributes(
                    klasses,
                    keys_override: List[str] = None,
                    transform_func: Callable[[str], str] = None
            ):
                keys = keys_override if keys_override else cls.__fields__.get('keys').default
                attributes = {}
                for klass in klasses:
                    for key in keys:
                        if attr := get_key(klass, key=key, transform_func=transform_func):
                            attributes.setdefault(
                                attr, []
                            ).append(klass)
                return {
                    name: _klass[0] if len(_klass) == 1 else _klass
                    for name, _klass in attributes.items()
                    if name not in self.__dict__
                }

            for name, attr in index_attributes(
                    klasses=self.klasses,
                    keys_override=keys_override,
                    transform_func=transform_func
            ).items():
                if isinstance(attr, list) and all(
                        isinstance(item, cls) for item in attr
                ):
                    SubList = type(
                        f"{cls.__name__}s",
                        (ListModel, MetaConfig),
                        {
                            '__annotations__': {
                                'klass': Type[cls],
                                'klasses': List[cls]
                            },
                            '__module__': cls.__module__
                        }
                    )
                    attr = SubList(cls, *attr)
                    for list_name, list_attr in index_attributes(
                            klasses=attr
                    ).items():
                        object.__setattr__(attr, list_name, list_attr)
                object.__setattr__(self, name, attr)

        return type(
            f"{cls.__name__}s",
            (ListModel, MetaConfig),
            {
                '__annotations__': {
                    'klass': Type[cls],
                    'klasses': List[cls]
                },
                '__module__': cls.__module__,
                '__init__': __init__
            }
        )

    @classmethod
    def s(
            cls,
            *klasses,
            keys_override: List[str] = None,
            transform_func: Callable[[str], str] = None
    ):
        ClassList = cls.construct_list_class()

        return ClassList(
            *klasses,
            keys_override=keys_override,
            transform_func=transform_func
        )


class Event(ConfigModel):
    keys: List[str] = ['upload_file_name']
    parent_id: str = None
    additional_info: str = None
    event_id: str = None
    user_id: str = None
    time_stamp: datetime = None
    item_type: str = None
    browser: str = None
    path: str = None
    first_name: str = None
    last_name: str = None
    email: str = None
    full_name: str = None
    full_name_short: str = None
    account_id: str = None
    ip_address: str = None
    city: str = None
    country: str = None
    account_id: str = None
    url: HttpUrl = None
    odata_type: str = None
    odata_metadata: HttpUrl = None
    event_item_name: str = None
    event_item: Any = None
    requester: Requester = None

    def json(self, exclude: dict = None, by_alias: bool = True):
        exclude = exclude or {
            'requester': ...,
            'keys': ...,
            'attributes': ...,
            'event_item_name': ...,
            'event_item': ...
        }
        return super().json(
            exclude=exclude,
            by_alias=by_alias
        )

    @property
    def upload_product(self):
        return self.additional_info.split('/')[5]

    @property
    def new_project_name(self):
        project_name = self.additional_info.split('/')[6]
        for section in self.additional_info.split('/')[7:-1]:
            if to_snake(section) not in ['from_hcl', 'to_welocalize', 'for_translation']:
                for part in re.split(r'\s|\_|\-', section):
                    if part.lower() not in project_name.lower():
                        project_name = ' '.join((project_name, part))
        return project_name

    @property
    def sql(self):
        return (
            self.event_id,
            self.time_stamp,
            self.parent_id,
            self.path,
            self.event_item_name,
            self.full_name,
            self.email
        )

    @validator('event_item_name', pre=True, always=True)
    def extract_event_item_name(cls, v, values):
        return values.get('additional_info').split('/')[-1]

    @validator('event_item', pre=True, always=True)
    def get_event_item(cls, v, values) -> File:
        if not v:
            parent_folder_id = values.get('parent_id')
            parent_folder = Folder(parent_folder_id)
            if not parent_folder:
                return v
            items = [
                child
                for child in parent_folder.children
                if child.name == values.get('event_item_name')
            ]
            return items[0] if items else v
        return v

    @validator('event_id', pre=True)
    def validate_event_id(cls, v, values):
        if event_item := values.get('event_item'):
            v = event_item.id
        return v


class MainClass(ConfigModel):
    requester: Requester = None

    def get_favorites(self):
        self.requester(
            'GET',
            'Users', 'FavoriteFolders'
        )
        attributes = self.requester.json.get('value')
        return [FavoriteFolder(self.requester, self.requester.headers, folder_info, completed=True) for
                folder_info in attributes]

    @staticmethod
    def get_activity_log(
            item_id: Union[str, Folder] = None,
            last: str = None,
            activity: str = 'upload',
            is_deep: bool = True
    ):
        requester = SF_REQUESTER
        format = r'%Y-%m-%dT%H:%M:%S.000Z'
        item_id = item_id if isinstance(item_id, str) else item_id.id
        last = last or 'week'

        end_date = dateparser.parse('tomorrow').strftime(format)
        start_date = dateparser.parse(f"a {last} ago").strftime(format)

        activity_types = {
            'upload': ['Upload', 'ZipUpload'],
            'new_folder': ['NewFolder'],
            'zip': ['ZipUpload']
        }

        requester(
            'GET',
            'WebMvcActivityLog',
            params={
                '$skip': 0,
                '$top': 1000,
                'itemID': item_id,
                'userID': None,
                'activityTypes': activity_types.get(activity, ['Upload', 'ZipUpload']),
                'startDate': start_date,
                'endDate': end_date,
                'isDeep': is_deep
            }
        )
        events = {}
        for event in requester.json.get('value'):
            if 'welocalize' not in event.get('Email') and activity == 'upload':
                continue
            events.setdefault(event.get('AdditionalInfo'), []).append(event)
        new_events = [
            event
            for version in events.values()
            if (
                    (upload := max(version, key=lambda x: parser.parse(x.get('TimeStamp'))))
                    and (event := Event(**upload))
                    and event.event_item is not None
            )
        ]
        return Event.s(
            *new_events,
            keys_override=['last_name']
        )

    def search(self, query: str, item_type: str = None):
        self.requester(
            'POST',
            'Items', 'AdvancedSimpleSearch',
            payload={
                'Query': {
                    'ItemType': item_type,
                    'ParentID': None,
                    'CreatorID': None,
                    'SearchQuery': query,
                    'CreateStartDate': None,
                    'CreateEndDate': None,
                    'ItemNameOnly': False
                },
                'Sort': {
                    'SortBy': None,
                    'Ascending': False
                },
                'TimeoutInSeconde': 10
            }
        )
        print(f"{self.requester.json=}")


class FavoriteFolder(ConfigModel):
    sort_order: int = None
    folder_alias: str = None
    folder_name: str = None
    path: str = None
    file_size: int = None
    creation_date: str = None
    creator_first_name: str = None
    creator_last_name: str = None
    odata_metadata: HttpUrl = None
    odata_type: str = None
    id: str = None
    url: str = None

    def __repr__(self):
        return f"{self.__class__.__name__}({self.odata_type}: {self.folder_name})"


class ParentFolder(ConfigModel):
    id: str = None
    odata_metadata: HttpUrl = None
    odata_type: str = None
    url: HttpUrl = None


class Info(ConfigModel):
    has_v_root: bool = None
    is_system_root: bool = None
    is_account_root: bool = None
    is_v_root: bool = None
    is_my_folders: bool = None
    is_a_home_folder: bool = None
    is_my_home_folder: bool = None
    is_a_start_folder: bool = None
    is_shared_folder: bool = None
    is_passthrough: bool = None
    can_add_folder: bool = None
    can_add_node: bool = None
    can_view: bool = None
    can_download: bool = None
    can_upload: bool = None
    can_send: bool = None
    can_delete_current_item: bool = None
    can_delete_child_items: bool = None
    can_manage_permissions: bool = None
    can_create_office_documents: bool = None
    folder_pay_id: str = None
    show_folder_pay_buy_button: bool = None
    odata_metadata: HttpUrl = None
    odata_type: str = None
    url: HttpUrl = None


class Share(ConfigModel):
    keys: List[str] = ['alias_id']
    alias_id: str = None
    share_type: str = None
    title: str = None
    has_sent_message: bool = False
    sent_message_title: str = None
    require_login: bool = False
    require_user_info: bool = False
    share_access_level: str = None
    creation_date: datetime = None
    expiration_date: datetime = None
    max_downloads: float = None
    total_downloads: float = None
    is_view_only: bool = False
    track_until_date: datetime = None
    send_frequency: float = None
    send_interval: float = None
    last_date_sent: datetime = None
    is_consumed: bool = False
    is_read: bool = False
    is_archived: bool = False
    send_tool: str = None
    send_method: str = None
    uses_stream_ids: bool = False
    uri: HttpUrl = None
    signature: str = None
    share_sub_type: str = None
    share_access_right: dict = None
    odata_metadata: HttpUrl = None
    odata_type: str = None
    id: str = None
    url: HttpUrl = None

    @classmethod
    def create(cls, *args, share_name: str = None):
        requester = SF_REQUESTER
        share_name = share_name or 'ShareFile Share'
        items = [
            {'Id': arg}
            for arg in args
        ]
        requester(
            'POST',
            'Shares',
            params={
                'notify': False
            },
            payload={
                'ShareType': 'Send',
                'Title': share_name,
                'Items': items,
                'ShareAccessLevel': 'Anonymous'
            }
        )
        attributes = requester.json
        return cls(requester=requester, **attributes)


class Note(ConfigModel):
    keys: List[str] = ['name', 'id']
    name: str = None
    file_name: str = None
    creation_date: datetime = None
    expiration_date: datetime = None
    description: str = None
    disk_space_limit: float = None
    is_hidden: bool = False
    bandwidth_limit_im_mb: float = None
    file_size_in_kb: float = None
    path: str = None
    creator_first_name: str = None
    creator_last_name: str = None
    expiration_days: float = None
    file_size_bytes: float = None
    has_pending_deletion: float = False
    associated_folder_template_id: str = None
    is_template_owned: bool = False
    has_permission_info: bool = False
    state: float = None
    stream_id: str = None
    creator_name_short: str = None
    has_pending_async_op: bool = False
    odata_metadata: HttpUrl = None
    odata_type: str = None
    id: str = None
    url: HttpUrl = None

    @classmethod
    def create(cls, parent_id: str, note: str, note_name: str = None):
        requester = SF_REQUESTER
        note_name = note_name or f"Note {datetime.today().strftime('%Y%m%d')}"
        requester(
            'POST',
            f"Items({parent_id})", 'Note',
            params={
                'notify': False
            },
            payload={
                'Name': note_name,
                'Description': note
            }
        )
        attributes = requester.json
        return cls(requester=requester, **attributes)


class File(ConfigModel):
    keys: List[str] = ['name']
    parent: ParentFolder = None
    hash: str = None
    virus_status: str = None
    name: str = None
    file_name: str = None
    creation_date: datetime = None
    expiration_date: datetime = None
    description: str = None
    disk_space_limit: int = None
    is_hidden: bool = None
    bandwidth_limit_in_mb: int = None
    file_size_in_kb: int = None
    path: str = None
    creator_first_name: str = None
    creator_last_name: str = None
    expiration_days: int = None
    file_size_bytes: int = None
    preview_status: str = None
    max_preview_size: int = None
    has_pending_deletion: bool = None
    associated_folder_template_id: str = None
    is_template_owned: bool = None
    has_permission_info: bool = None
    state: int = None
    stream_id: str = None
    creator_name_short: str = None
    has_multiple_versions: bool = None
    has_pending_async_op: bool = None
    odata_metadata: HttpUrl = None
    odata_type: str = None
    id: str = None
    url: HttpUrl = None
    requester: Requester = None
    attributes: dict = None

    @validator('requester', pre=True, always=True)
    def configure_requester(cls, v, values):
        if not v and (item_id := values.get('id')):
            return Requester(
                f"{BASE_URL}/Items({item_id})",
                creds=sf_creds
            )
        return v

    def __repr__(self):
        return f"{self.__class__.__name__}({self.odata_type}: {self.name})"

    def duplicate(self, target_folder_id: str):
        self.requester(
            'POST',
            'Copy',
            params={
                'targetid': target_folder_id,
                'overwrite': False
            }
        )

    def move(self, target_folder_id: str):
        self.requester(
            'PATCH',
            params={
                'overwrite': False
            },
            payload={
                'Parent': {
                    'Id': target_folder_id
                }
            }
        )

    def share(self):
        return Share.create(self.id)

    def download(self, path: Path = None):
        self.requester(
            'GET',
            'Download',
            params={
                'includeAllVersions': False,
                'includeDeleted': False
            }
        )
        path = path or this.parent / 'tmp'
        path.mkdir(exist_ok=True)
        dl = path / self.name
        with open(dl, 'wb') as f:
            f.write(self.requester.content)
        return dl

    def delete(self):
        self.requester(
            'DELETE',
            params={
                'singleversion': False,
                'forceSync': False
            }
        )


class Folder(File):
    id: str = None
    keys: List[str] = ['name']
    parent: ParentFolder = None
    file_count: int = None
    info: Info = None
    name: str = None
    file_name: str = None
    creation_date: datetime = None
    expiration_date: datetime = None
    description: str = None
    progeny_edit_date: datetime = None
    disk_space_limit: int = None
    is_hidden: bool = None
    bandwidth_limit_in_mb: int = None
    file_size_in_kb: int = None
    path: str = None
    creator_first_name: str = None
    creator_last_name: str = None
    expiration_days: int = None
    file_size_bytes: int = None
    preview_status: str = None
    max_preview_size: int = None
    has_pending_deletion: bool = None
    associated_folder_template_id: str = None
    is_template_owned: bool = None
    has_permission_info: bool = None
    state: int = None
    stream_id: str = None
    creator_name_short: str = None
    has_multiple_versions: bool = None
    has_pending_async_op: bool = None
    odata_metadata: HttpUrl = None
    odata_type: str = None
    url: HttpUrl = None
    requester: Requester = None
    attributes: dict = None
    children: Collection = None

    def __init__(
            self,
            folder_id: str = None,
            **attributes
    ):
        if folder_id and not attributes:
            requester = Requester(
                f"{BASE_URL}/Items({folder_id})",
                creds=sf_creds
            )
            requester(
                'GET',
                params={
                    'includeDeleted': False,
                    '$expand': ['Children', 'Parent']
                }
            )
            attributes = {
                **requester.json,
                'requester': requester
            }
        super().__init__(
            **attributes
        )

    def __repr__(self):
        return f"{self.__class__.__name__}({self.odata_type}: {self.name})"

    def __bool__(self):
        return bool(self.name)

    @validator('requester', always=True)
    def configure_requester(cls, requester, values):
        if (folder_id := values.get('id')):
            if not requester:
                return Requester(
                    f"{BASE_URL}/Items({folder_id})",
                    creds=sf_creds
                )
            if folder_id not in requester.base_url:
                requester.base_url = f"{BASE_URL}/Items({folder_id})"
        return requester

    def json(self, exclude: dict = None, by_alias: bool = True):
        extras = {
            'requester': ...,
            'keys': ...,
            'attributes': ...
        }
        exclude = exclude or {
            **extras,
            'children': ...,
            'parent': {
                **extras,
                'children': ...
            },
            'info': extras
        }
        return super().json(
            exclude=exclude,
            by_alias=by_alias
        )

    @validator('children', pre=True)
    def validate_children(cls, v):
        if attributes := v:
            return Folder.collect_children(attributes)
        return v

    @staticmethod
    def collect_children(attributes):
        matrix = {
            'ShareFile.Api.Models.Folder': Folder,
            'ShareFile.Api.Models.File': File,
            'ShareFile.Api.Models.Event': Event,
            'ShareFile.Api.Models.Note': Note
        }
        collect = lambda x: matrix.get(x.get('odata.type'))(**x)
        items = [collect(item) for item in attributes]
        return Collection(
            *items
        )

    def get_children(self):
        self.requester(
            'GET',
            'Children',
            params={
                'includeDeleted': False
            }
        )
        attributes = self.requester.json.get('value')
        super().__setattr__('children', self.collect_children(attributes))

    def get_child_folder(self, child_name: str, create_if_not_found: bool = True):
        if (
                (folders := getattr(self.children, 'folders', None))
                and (child := getattr(folders, child_name, None))
        ):
            return child
        if create_if_not_found:
            new_child = self.create_folder(child_name)
            self.get_children()
            return new_child

    @property
    def only_child(self):
        if self.folders is None:
            self.get_children()
        if (folders := self.folders) and len(folders) == 1:
            return folders[0]

    def draw_tree(self):
        tree = {self.name: {'Id': self.id}}
        children = deque()
        self.requester = sf_api.get_child_item_info(self.id, requester=self.requester)
        for kid in self.requester.json.get('value'):
            if 'Folder' not in kid.get('odata.type'):
                dpath.util.get(tree, self.name).update({kid.get('Name'): {'Id': kid.get('Id')}})
        children.extendleft(
            [(child.get('Id'), child.get('Name'), self.name) for child in self.requester.json.get('value') if
             'Folder' in child.get('odata.type')]
        )
        while len(children) > 0:
            item_id, name, path = children.pop()
            dpath.util.get(tree, path).update({name: {'Id': item_id}})
            self.requester.headers = sf_api.get_authorization()
            self.requester = sf_api.get_child_item_info(item_id, requester=self.requester)
            path = '/'.join([path, name])
            for kid in self.requester.json.get('value'):
                if 'Folder' not in kid.get('odata.type'):
                    dpath.util.get(tree, path).update({kid.get('Name'): {'Id': kid.get('Id')}})
            children.extendleft(
                [(child.get('Id'), child.get('Name'), path) for child in self.requester.json.get('value') if
                 'Folder' in child.get('odata.type')]
            )
        super().__setattr__('tree', tree)

    @property
    def folders(self):
        if children := getattr(self, 'children', None):
            return getattr(children, 'folders', None)

    @property
    def files(self):
        if children := getattr(self, 'children', None):
            return getattr(children, 'files', None)

    @property
    def notes(self):
        if children := getattr(self, 'children', None):
            return getattr(children, 'notes', None)

    def rename(self, new_name: str, overwrite: bool = False):
        self.requester(
            'PATCH',
            params={
                'overwrite': overwrite
            },
            payload={
                'Name': new_name
            }
        )
        self.name = new_name

    def create_folder(self, folder_name: str, overwrite: bool = False):
        self.requester(
            'POST',
            'Folder',
            params={
                'overwrite': overwrite,
                'passthrough': False
            },
            payload={
                'Name': folder_name
            }
        )
        attributes = self.requester.json
        return Folder(requester=self.requester, **attributes)

    def share(self, share_name: str = None):
        share_name = share_name or self.name
        return Share.create(
            *[child.id for child in self.children],
            share_name=share_name
        )

    def note(self, note: str, note_name: str = None):
        return Note.create(
            self.id, note, note_name
        )

    def delete(self):
        self.requester(
            'DELETE',
            params={
                'singleversion': False,
                'forceSync': False
            }
        )

    def duplicate(
            self,
            target_folder_id: str,
            new_folder_name: str = None,
            overwrite: bool = False):
        self.requester(
            'POST',
            'Copy',
            params={
                'targetid': target_folder_id,
                'overwrite': overwrite
            }
        )
        attributes = self.requester.json
        new_folder = Folder(requester=self.requester, **attributes)
        if new_folder_name is not None:
            new_folder.rename(new_folder_name, overwrite=overwrite)
        return new_folder

    def upload(
            self,
            *filenames: str
    ):

        async def async_upload(fnames):
            async def _upload(filenames):
                async with aiohttp.ClientSession() as session:
                    self.requester(
                        'GET',
                        'Upload',
                        params={
                            'Method': 'Standard'
                        }
                    )
                    chunk_uri = self.requester.json.get('ChunkUri')
                    with ExitStack() as stack:
                        self.requester.url = chunk_uri
                        self.requester.payload = {
                            f"File{i}": upfile
                            for i, f in enumerate(filenames, start=1)
                            if (upfile := stack.enter_context(open(f, 'rb')))
                        }
                        request = self.requester._prepare_request()
                        await self.requester.async_request(
                            'POST',
                            session,
                            request=request
                        )

            await _upload(fnames)

        return asyncio.run(async_upload(filenames))

    def get_events(
            self,
            last: str = None,
            activity: str = 'upload',
            is_deep: bool = True
    ):
        return MainClass.get_activity_log(
            item_id=self.id,
            last=last,
            activity=activity,
            is_deep=is_deep
        )

    def find_child_item(self, query: str):
        results = []
        for child in self.children:
            if query in child.name:
                results.append(child)
        return results[0] if len(results) == 1 else results


class TemplateFolder(Folder):
    def __init__(self, folder_id: str = None, **attributes):
        super().__init__(folder_id, **attributes)
        self.get_children()
        for folder in self.folders:
            super().__setattr__(folder.name.split('_', 1)[1], folder)

    def duplicate(
            self,
            target_folder_id: str,
            new_folder_name: str = None,
            overwrite: bool = False):
        self.requester(
            'POST',
            'Copy',
            params={
                'targetid': target_folder_id,
                'overwrite': overwrite
            }
        )
        attributes = self.requester.json
        new_folder = TemplateFolder(**attributes)
        if new_folder_name is not None:
            new_folder.rename(new_folder_name, overwrite=overwrite)
        return new_folder


class ProductionFolder(Folder):
    pattern: str = None
    template: TemplateFolder = None
    production_folders: List[Folder]

    def __init__(
            self,
            pattern: str,
            folder_id: str = None,
            template_info: str = None,
            **attributes
    ):
        if folder_id:
            requester = Requester(
                f"{BASE_URL}/Items({folder_id})",
                creds=sf_creds
            )
            requester(
                'GET',
                params={
                    'includeDeleted': False,
                    '$expand': ['Children', 'Parent']
                }
            )
            attributes = {
                **requester.json,
                'requester': requester
            }
            production_folders = [
                child
                for child in attributes.get('Children')
                if self.is_prod_folder(child.get('Name'), pattern)
            ]
            template = [
                child
                for child in attributes.get('Children')
                if template_info in child.values()
            ][0]
        super().__init__(
            pattern=pattern,
            template=TemplateFolder(**template),
            production_folders=production_folders,
            **attributes
        )
        for folder in self.production_folders:
            super().__setattr__(folder.name, folder)

    @validator('children', pre=True)
    def validate_children(cls, v):
        if isinstance(v, list):
            matrix = {
                'ShareFile.Api.Models.Folder': Folder,
                'ShareFile.Api.Models.File': File,
                'ShareFile.Api.Models.Event': Event,
                'ShareFile.Api.Models.Note': Note
            }
            collect = lambda x: matrix.get(x.get('odata.type'))(**x)
            items = [collect(item) for item in v]
            return Collection(
                *items
            )
        return v

    def create_new(
            self,
            folder_name: str = None,
            target_folder_id: str = None,
            overwrite: bool = False
    ):
        if target_folder_id is None:
            prod_folder = datetime.today().strftime(self.pattern)
            target_folder_id = getattr(self, prod_folder).id
        project_folder = self.template.duplicate(
            target_folder_id, folder_name, overwrite=overwrite
        )
        return project_folder

    @staticmethod
    def is_prod_folder(folder_name: str, pattern: str):
        try:
            datetime.strptime(folder_name, pattern)
            return True
        except ValueError:
            return False


class User(ConfigModel):
    company: str = None
    contacted: int = None
    date_created: datetime = None
    domain: str = None
    email: str = None
    email_addresses: List[Dict[str, Any]] = None
    emails: List[str] = None
    first_name: str = None
    full_name: str = None
    full_name_short: str = None
    id: str = None
    is_billing_contact: bool = False
    is_confirmed: bool = False
    is_deleted: bool = False
    last_name: str = False
    referred_by: str = None
    roles: List[str] = None
    total_shared_files: int = None
    username: str = None
    odata_metadata: HttpUrl = None
    odata_type: str = None
    url: HttpUrl = None
    requester: Requester = None
    attributes: Dict[str, Any] = None

    @classmethod
    def create(
            cls,
            first_name: str,
            last_name: str,
            email: str,
            company: str
    ):
        requester = SF_REQUESTER
        requester(
            'POST',
            'Users',
            params={
                'pushCreatorDefaultSettings': False,
                'addshared': True,
                'notify': True,
                'ifNecessary': True,
                'addPersonal': True
            },
            payload={
                'FirstName': first_name,
                'LastName': last_name,
                'Email': email,
                'Company': company
            }
        )
        attributes = requester.json
        requester.base_url = f"{requester.base_url}/Users({attributes.get('Id')})"
        return cls(requester=requester, **attributes)

    # def add_folder(self, folder_id):


Event.update_forward_refs()
