import logging
import os
import json
from pathlib import Path
import sqlite3
import datetime
from typing import List, Union, Callable

from pysharefile.entities import Folder, Event

this = Path(__file__)
logger = logging.getLogger(f"logger.{this.stem}")


class Listener:
    def __init__(
            self, 
            folder_id: str,
            sql_path: Path,
            callback: Callable[[Event], None] = None
    ):
        self.folder = Folder(folder_id)
        self.sql_path = sql_path
        self.callback = callback

    def __enter__(self):
        self.connection = sqlite3.connect(self.sql_path)
        self.cursor = self.connection.cursor()
        self.events = self.folder.get_events()
        return self

    def __exit__(self, type, value, traceback):
        self.connection.commit()
        self.connection.close()

    def record_event(self, event: Event):
        sql = '''
            INSERT INTO uploads(event_id,timestamp,parent_id,path,filename,full_name,email)
            VALUES(?,?,?,?,?,?,?)  
            '''
        self.cursor.execute(sql, event.sql)
    
    def event_recorded(self, event: Event):
        sql = f"SELECT count(*) FROM uploads WHERE event_id = ?"
        self.cursor.execute(sql, (event.event_id,))
        data = self.cursor.fetchone()[0]
        return data != 0
    
    def run(self) -> None:
        for event in self.events:
            if self.event_recorded(event):
                logger.debug(f"Skipping already processed file: {event.upload_file_name}")
                continue
            logger.info(f"Processing file: {event.upload_file_name}")
            self.record_event(event)
            if (callback := self.callback):
                callback(
                    event
                )