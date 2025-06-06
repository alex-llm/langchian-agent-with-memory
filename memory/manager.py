"""
Memory Manager Module for LangChain Agent

This module provides a centralized memory management system for LangChain agents,
supporting multiple memory types, session management, and memory persistence.

Features:
- Multiple memory types (conversation, buffer, summary, etc.)
- Session-based memory isolation
- Memory persistence and serialization
- Memory statistics and analysis
- Memory cleanup and optimization
"""

import os
import json
import pickle
import datetime
from typing import Dict, List, Optional, Any, Union
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from pathlib import Path

from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.runnables.history import RunnableWithMessageHistory

# Simple in-memory chat history implementation to avoid dependency issues
class SimpleChatMessageHistory(BaseChatMessageHistory):
    """Simple in-memory implementation of chat message history"""
    
    def __init__(self):
        self.messages: List[BaseMessage] = []
    
    def add_message(self, message: BaseMessage) -> None:
        """Add a message to the store"""
        self.messages.append(message)
    
    def clear(self) -> None:
        """Clear all messages"""
        self.messages = []


@dataclass
class MemoryStats:
    """Memory statistics data class"""
    session_id: str
    message_count: int
    total_tokens: int
    first_message_time: Optional[datetime.datetime]
    last_message_time: Optional[datetime.datetime]
    memory_size_bytes: int
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "session_id": self.session_id,
            "message_count": self.message_count,
            "total_tokens": self.total_tokens,
            "first_message_time": self.first_message_time.isoformat() if self.first_message_time else None,
            "last_message_time": self.last_message_time.isoformat() if self.last_message_time else None,
            "memory_size_bytes": self.memory_size_bytes
        }


class BaseMemoryStore(ABC):
    """Abstract base class for memory stores"""
    
    @abstractmethod
    def get_session_history(self, session_id: str) -> BaseChatMessageHistory:
        """Get or create session history"""
        pass
    
    @abstractmethod
    def clear_session(self, session_id: str) -> bool:
        """Clear session memory"""
        pass
    
    @abstractmethod
    def get_all_sessions(self) -> List[str]:
        """Get all session IDs"""
        pass
    
    @abstractmethod
    def get_memory_stats(self, session_id: str) -> MemoryStats:
        """Get memory statistics for a session"""
        pass


class InMemoryStore(BaseMemoryStore):
    """In-memory storage for chat history"""
    
    def __init__(self):
        self.store: Dict[str, SimpleChatMessageHistory] = {}
        self.metadata: Dict[str, Dict[str, Any]] = {}
    
    def get_session_history(self, session_id: str) -> BaseChatMessageHistory:
        """Get or create session history"""
        if session_id not in self.store:
            self.store[session_id] = SimpleChatMessageHistory()
            self.metadata[session_id] = {
                "created_at": datetime.datetime.now(),
                "last_accessed": datetime.datetime.now()
            }
        else:
            self.metadata[session_id]["last_accessed"] = datetime.datetime.now()
        
        return self.store[session_id]
    
    def clear_session(self, session_id: str) -> bool:
        """Clear session memory"""
        if session_id in self.store:
            self.store[session_id] = SimpleChatMessageHistory()
            self.metadata[session_id]["last_accessed"] = datetime.datetime.now()
            return True
        return False
    
    def get_all_sessions(self) -> List[str]:
        """Get all session IDs"""
        return list(self.store.keys())
    
    def get_memory_stats(self, session_id: str) -> MemoryStats:
        """Get memory statistics for a session"""
        if session_id not in self.store:
            return MemoryStats(
                session_id=session_id,
                message_count=0,
                total_tokens=0,
                first_message_time=None,
                last_message_time=None,
                memory_size_bytes=0
            )
        
        history = self.store[session_id]
        messages = history.messages
        
        # Calculate statistics
        message_count = len(messages)
        total_tokens = sum(len(msg.content.split()) for msg in messages)
        
        first_message_time = None
        last_message_time = None
        
        if messages:
            # Try to get timestamps from metadata
            metadata = self.metadata.get(session_id, {})
            first_message_time = metadata.get("created_at")
            last_message_time = metadata.get("last_accessed")
        
        # Estimate memory size
        memory_size = sum(len(msg.content.encode('utf-8')) for msg in messages)
        
        return MemoryStats(
            session_id=session_id,
            message_count=message_count,
            total_tokens=total_tokens,
            first_message_time=first_message_time,
            last_message_time=last_message_time,
            memory_size_bytes=memory_size
        )


class FileBasedMemoryStore(BaseMemoryStore):
    """File-based persistent storage for chat history"""
    
    def __init__(self, storage_dir: str = "memory_storage"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(exist_ok=True)
        self.cache: Dict[str, SimpleChatMessageHistory] = {}
        self.metadata_file = self.storage_dir / "metadata.json"
        self.metadata = self._load_metadata()
    
    def _load_metadata(self) -> Dict[str, Dict[str, Any]]:
        """Load metadata from file"""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Convert datetime strings back to datetime objects
                    for session_id, meta in data.items():
                        if meta.get("created_at"):
                            meta["created_at"] = datetime.datetime.fromisoformat(meta["created_at"])
                        if meta.get("last_accessed"):
                            meta["last_accessed"] = datetime.datetime.fromisoformat(meta["last_accessed"])
                    return data
            except Exception as e:
                print(f"Warning: Could not load metadata: {e}")
        return {}
    
    def _save_metadata(self):
        """Save metadata to file"""
        try:
            # Convert datetime objects to strings for JSON serialization
            serializable_metadata = {}
            for session_id, meta in self.metadata.items():
                serializable_metadata[session_id] = {}
                for key, value in meta.items():
                    if isinstance(value, datetime.datetime):
                        serializable_metadata[session_id][key] = value.isoformat()
                    else:
                        serializable_metadata[session_id][key] = value
            
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(serializable_metadata, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Warning: Could not save metadata: {e}")
    
    def _get_session_file(self, session_id: str) -> Path:
        """Get file path for session"""
        safe_session_id = "".join(c for c in session_id if c.isalnum() or c in "._-")
        return self.storage_dir / f"session_{safe_session_id}.pkl"
    
    def get_session_history(self, session_id: str) -> BaseChatMessageHistory:
        """Get or create session history"""
        if session_id in self.cache:
            self.metadata[session_id]["last_accessed"] = datetime.datetime.now()
            self._save_metadata()
            return self.cache[session_id]
        
        session_file = self._get_session_file(session_id)
        
        if session_file.exists():
            try:
                with open(session_file, 'rb') as f:
                    history = pickle.load(f)
                self.cache[session_id] = history
            except Exception as e:
                print(f"Warning: Could not load session {session_id}: {e}")
                history = SimpleChatMessageHistory()
                self.cache[session_id] = history
        else:
            history = SimpleChatMessageHistory()
            self.cache[session_id] = history
            self.metadata[session_id] = {
                "created_at": datetime.datetime.now(),
                "last_accessed": datetime.datetime.now()
            }
        
        self.metadata[session_id]["last_accessed"] = datetime.datetime.now()
        self._save_metadata()
        return history
    
    def clear_session(self, session_id: str) -> bool:
        """Clear session memory"""
        session_file = self._get_session_file(session_id)
        
        # Clear from cache
        if session_id in self.cache:
            self.cache[session_id] = SimpleChatMessageHistory()
        
        # Clear file
        try:
            if session_file.exists():
                session_file.unlink()
            self.metadata[session_id]["last_accessed"] = datetime.datetime.now()
            self._save_metadata()
            return True
        except Exception as e:
            print(f"Warning: Could not clear session file {session_id}: {e}")
            return False
    
    def save_session(self, session_id: str):
        """Save session to file"""
        if session_id not in self.cache:
            return
        
        session_file = self._get_session_file(session_id)
        try:
            with open(session_file, 'wb') as f:
                pickle.dump(self.cache[session_id], f)
        except Exception as e:
            print(f"Warning: Could not save session {session_id}: {e}")
    
    def get_all_sessions(self) -> List[str]:
        """Get all session IDs"""
        sessions = set()
        
        # Add sessions from cache
        sessions.update(self.cache.keys())
        
        # Add sessions from files
        for file in self.storage_dir.glob("session_*.pkl"):
            session_id = file.stem.replace("session_", "")
            sessions.add(session_id)
        
        # Add sessions from metadata
        sessions.update(self.metadata.keys())
        
        return list(sessions)
    
    def get_memory_stats(self, session_id: str) -> MemoryStats:
        """Get memory statistics for a session"""
        history = self.get_session_history(session_id)
        messages = history.messages
        
        # Calculate statistics
        message_count = len(messages)
        total_tokens = sum(len(msg.content.split()) for msg in messages)
        
        first_message_time = None
        last_message_time = None
        
        if messages:
            # Try to get timestamps from metadata
            metadata = self.metadata.get(session_id, {})
            first_message_time = metadata.get("created_at")
            last_message_time = metadata.get("last_accessed")
        
        # Estimate memory size
        memory_size = sum(len(msg.content.encode('utf-8')) for msg in messages)
        
        return MemoryStats(
            session_id=session_id,
            message_count=message_count,
            total_tokens=total_tokens,
            first_message_time=first_message_time,
            last_message_time=last_message_time,
            memory_size_bytes=memory_size
        )


class MemoryManager:
    """
    Central memory manager that coordinates different memory stores and provides
    a unified interface for memory operations.
    """
    
    def __init__(self, 
                 store_type: str = "memory",
                 storage_dir: Optional[str] = None,
                 max_messages_per_session: int = 1000,
                 auto_save: bool = True):
        """
        Initialize the memory manager
        
        Args:
            store_type: Type of memory store ("memory", "file")
            storage_dir: Directory for file-based storage
            max_messages_per_session: Maximum messages to keep per session
            auto_save: Whether to auto-save sessions (file store only)
        """
        self.store_type = store_type
        self.max_messages_per_session = max_messages_per_session
        self.auto_save = auto_save
        
        # Create the appropriate store
        if store_type == "memory":
            self.store = InMemoryStore()
        elif store_type == "file":
            storage_dir = storage_dir or "memory_storage"
            self.store = FileBasedMemoryStore(storage_dir)
        else:
            raise ValueError(f"Unknown store type: {store_type}")
    
    def get_session_history(self, session_id: str) -> BaseChatMessageHistory:
        """Get or create session history"""
        return self.store.get_session_history(session_id)
    
    def clear_session(self, session_id: str) -> bool:
        """Clear session memory"""
        return self.store.clear_session(session_id)
    
    def clear_all_sessions(self) -> int:
        """Clear all sessions and return count of cleared sessions"""
        sessions = self.get_all_sessions()
        cleared_count = 0
        
        for session_id in sessions:
            if self.clear_session(session_id):
                cleared_count += 1
        
        return cleared_count
    
    def get_all_sessions(self) -> List[str]:
        """Get all session IDs"""
        return self.store.get_all_sessions()
    
    def get_memory_stats(self, session_id: str) -> MemoryStats:
        """Get memory statistics for a session"""
        return self.store.get_memory_stats(session_id)
    
    def get_all_memory_stats(self) -> List[MemoryStats]:
        """Get memory statistics for all sessions"""
        return [self.get_memory_stats(session_id) for session_id in self.get_all_sessions()]
    
    def cleanup_old_sessions(self, days_old: int = 30) -> int:
        """Clean up sessions older than specified days"""
        cutoff_date = datetime.datetime.now() - datetime.timedelta(days=days_old)
        cleaned_count = 0
        
        for session_id in self.get_all_sessions():
            stats = self.get_memory_stats(session_id)
            if stats.last_message_time and stats.last_message_time < cutoff_date:
                if self.clear_session(session_id):
                    cleaned_count += 1
        
        return cleaned_count
    
    def trim_session_messages(self, session_id: str, max_messages: Optional[int] = None) -> int:
        """Trim session to keep only recent messages"""
        max_messages = max_messages or self.max_messages_per_session
        
        history = self.get_session_history(session_id)
        current_count = len(history.messages)
        
        if current_count <= max_messages:
            return 0
        
        # Keep only the most recent messages
        messages_to_keep = history.messages[-max_messages:]
        history.messages = messages_to_keep
        
        return current_count - max_messages
    
    def export_session(self, session_id: str, format: str = "json") -> str:
        """Export session data"""
        history = self.get_session_history(session_id)
        stats = self.get_memory_stats(session_id)
        
        data = {
            "session_id": session_id,
            "exported_at": datetime.datetime.now().isoformat(),
            "stats": stats.to_dict(),
            "messages": []
        }
        
        for msg in history.messages:
            msg_data = {
                "type": msg.__class__.__name__,
                "content": msg.content
            }
            if hasattr(msg, 'additional_kwargs'):
                msg_data["additional_kwargs"] = msg.additional_kwargs
            data["messages"].append(msg_data)
        
        if format.lower() == "json":
            return json.dumps(data, indent=2, ensure_ascii=False)
        else:
            raise ValueError(f"Unsupported export format: {format}")
    
    def import_session(self, session_id: str, data: str, format: str = "json") -> bool:
        """Import session data"""
        try:
            if format.lower() == "json":
                imported_data = json.loads(data)
            else:
                raise ValueError(f"Unsupported import format: {format}")
            
            # Clear existing session
            self.clear_session(session_id)
            history = self.get_session_history(session_id)
            
            # Import messages
            for msg_data in imported_data.get("messages", []):
                msg_type = msg_data.get("type", "HumanMessage")
                content = msg_data.get("content", "")
                
                if msg_type == "HumanMessage":
                    message = HumanMessage(content=content)
                elif msg_type == "AIMessage":
                    message = AIMessage(content=content)
                elif msg_type == "SystemMessage":
                    message = SystemMessage(content=content)
                else:
                    # Default to HumanMessage for unknown types
                    message = HumanMessage(content=content)
                
                history.add_message(message)
            
            # Save if using file store
            if isinstance(self.store, FileBasedMemoryStore):
                self.store.save_session(session_id)
            
            return True
            
        except Exception as e:
            print(f"Error importing session: {e}")
            return False
    
    def create_runnable_with_history(self, runnable) -> RunnableWithMessageHistory:
        """Create a runnable with message history"""
        return RunnableWithMessageHistory(
            runnable,
            self.get_session_history,
            input_messages_key="input",
            history_messages_key="chat_history",
        )
    
    def save_all_sessions(self):
        """Save all sessions (file store only)"""
        if isinstance(self.store, FileBasedMemoryStore):
            for session_id in self.get_all_sessions():
                self.store.save_session(session_id)
    
    def get_memory_summary(self) -> Dict[str, Any]:
        """Get overall memory summary"""
        all_stats = self.get_all_memory_stats()
        
        total_sessions = len(all_stats)
        total_messages = sum(stats.message_count for stats in all_stats)
        total_memory_bytes = sum(stats.memory_size_bytes for stats in all_stats)
        
        average_messages_per_session = total_messages / total_sessions if total_sessions > 0 else 0
        
        sessions_data = []
        for stats in all_stats:
            sessions_data.append({
                "session_id": stats.session_id,
                "message_count": stats.message_count,
                "memory_size_bytes": stats.memory_size_bytes,
                "last_message_time": stats.last_message_time.isoformat() if stats.last_message_time else None
            })
        
        return {
            "total_sessions": total_sessions,
            "total_messages": total_messages,
            "total_memory_bytes": total_memory_bytes,
            "average_messages_per_session": average_messages_per_session,
            "sessions": sessions_data
        }


def create_memory_manager(store_type: str = "memory", **kwargs) -> MemoryManager:
    """Create a memory manager with the specified store type"""
    return MemoryManager(store_type=store_type, **kwargs)


def get_default_memory_manager() -> MemoryManager:
    """Get the default memory manager instance"""
    return create_memory_manager(store_type="memory") 