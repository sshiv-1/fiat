from abc import ABC, abstractmethod
from typing import List, Callable, Generator, Dict, Any
import os
import json
import logging

class Provider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def configure(self, model: str, api_key: str):
        pass

    @abstractmethod
    def set_tools(self, tools: List[Callable]):
        pass

    @abstractmethod
    def stream(self, prompt: str) -> Generator[str, None, None]:
        pass

    @abstractmethod
    def supports_tools(self) -> bool:
        pass
