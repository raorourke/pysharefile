import logging
import sqlite3
from pathlib import Path
from typing import Union, Callable

from .entities import Folder, Event

this = Path(__file__)
logger = logging.getLogger(f"logger.{this.stem}")

__all__ = ['Listener', 'NewFolderListener', 'UploadListener']


class Listener:
    def __init__(
            self,
            folder: Union[Folder, str],
            sql_path: Path,
            activity: str = 'upload',
            is_deep: bool = True,
            callback: Callable[[Event], None] = None
    ):
        self.folder = Folder(folder) if isinstance(folder, str) else folder
        self.sql_path = sql_path
        self.activity = activity
        self.is_deep = is_deep
        self.callback = callback

    def __enter__(self):
        if not self.sql_path.exists():
            with open(self.sql_path, 'w') as f:
                f.write('')
            self.create_table()
        self.connection = sqlite3.connect(self.sql_path)
        self.cursor = self.connection.cursor()
        self.events = self.folder.get_events(
            activity=self.activity,
            is_deep=self.is_deep
        )
        return self

    def __exit__(self, type, value, traceback):
        self.connection.commit()
        self.connection.close()

    def create_table(self):
        connection = sqlite3.connect(self.sql_path)
        cursor = connection.cursor()
        sql = '''
            CREATE TABLE events(
            event_id TEXT NOT NULL UNIQUE PRIMARY KEY,
            timestamp TEXT NOT NULL,
            parent_id TEXT NOT NULL,
            path TEXT NOT NULL,
            item_name TEXT NOT NULL,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL)
            '''
        cursor.execute(sql)
        connection.commit()
        connection.close()

    def record_event(self, event: Event):
        sql = '''
            INSERT INTO events(event_id,timestamp,parent_id,path,item_name,full_name,email)
            VALUES(?,?,?,?,?,?,?)  
            '''
        self.cursor.execute(sql, event.sql)

    def event_recorded(self, event: Event):
        sql = f"SELECT count(*) FROM events WHERE event_id = ?"
        self.cursor.execute(sql, (event.event_id,))
        data = self.cursor.fetchone()[0]
        return data != 0

    def run(self) -> None:
        for event in self.events:
            if self.event_recorded(event):
                logger.info(f"Skipping already processed event: {event.event_item_name}")
                continue
            logger.info(f"Processing event: {event.event_item_name}")
            self.record_event(event)
            if (callback := self.callback):
                callback(
                    event
                )


class NewFolderListener(Listener):
    def __init__(
            self,
            folder: Union[Folder, str],
            sql_path: Path,
            callback: Callable[[Event], None] = None,
            is_deep: bool = False
    ):
        super().__init__(
            folder,
            sql_path,
            activity='new_folder',
            is_deep=is_deep,
            callback=callback
        )


class UploadListener(Listener):
    def __init__(
            self,
            folder: Union[Folder, str],
            sql_path: Path,
            callback: Callable[[Event], None] = None,
            is_deep: bool = True
    ):
        super().__init__(
            folder,
            sql_path,
            activity='upload',
            is_deep=is_deep,
            callback=callback
        )